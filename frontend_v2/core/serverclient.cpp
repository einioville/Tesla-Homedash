#include "serverclient.hh"

#include <QCryptographicHash>
#include <QJsonObject>
#include <QSslConfiguration>
#include <QSysInfo>
#include <QtConcurrent>
#include <QtEndian>
#include <utility>

#include "logger.hh"
#include "protocol.hh"

namespace {
const Logger logger = Logger::get("server_client");

const QString kNoPasswordMessage = QStringLiteral(
    "Palvelimelle ei ole asetettu salasanaa. Lisää TESLA_HOMEDASH_PASSWORD palvelimen "
    ".env-tiedostoon ja käynnistä palvelin uudelleen.");
}  // namespace

ServerClient::ServerClient(QString host, quint16 port, QObject *parent)
    : QObject(parent),
      m_socket(new QSslSocket(this)),
      m_host(std::move(host)),
      m_port(port),
      m_endpoint(QStringLiteral("%1:%2").arg(m_host).arg(m_port)),
      m_reconnectTimer(new QTimer(this)),
      m_proofWatcher(new QFutureWatcher<std::optional<scram::ClientFinal>>(this)) {
    m_reconnectTimer->setInterval(10'000);

    // TLS 1.3, as the backend requires. QueryPeer asks for the certificate without
    // validating it against a CA: it is self-signed by design, and this side checks
    // it by its hash instead — the pin, or SCRAM's channel binding at login. (Qt
    // still emits sslErrors for it — self-signed, host name — which mean nothing
    // here, so nothing listens.)
    QSslConfiguration tls = QSslConfiguration::defaultConfiguration();
    tls.setProtocol(QSsl::TlsV1_3OrLater);
    tls.setPeerVerifyMode(QSslSocket::QueryPeer);
    m_socket->setSslConfiguration(tls);
}

QString ServerClient::stateText() const {
    switch (m_state) {
        case State::Disconnected: return QStringLiteral("Disconnected");
        case State::Connecting:   return QStringLiteral("Connecting");
        case State::Connected:    return QStringLiteral("Connected");
        case State::Reconnecting: return QStringLiteral("Reconnecting");
    }
    return QStringLiteral("Disconnected");
}

QString ServerClient::authState() const {
    switch (m_auth) {
        case Auth::Offline:        return QStringLiteral("offline");
        case Auth::Authenticating: return QStringLiteral("authenticating");
        case Auth::LoginRequired:  return QStringLiteral("loginRequired");
        case Auth::NoPassword:     return QStringLiteral("noPassword");
        case Auth::Authenticated:  return QStringLiteral("authenticated");
    }
    return QStringLiteral("offline");
}

bool ServerClient::loginPromptVisible() const {
    return !m_promptDismissed &&
           (m_auth == Auth::LoginRequired || m_auth == Auth::NoPassword || m_loginInFlight);
}

QString ServerClient::deviceId() const {
    const auto credential = m_credentials.find(m_endpoint);
    return credential ? credential->deviceId : QString();
}

void ServerClient::start() {
    connect(m_socket, &QSslSocket::encrypted, this, &ServerClient::onEncrypted);
    connect(m_socket, &QSslSocket::readyRead, this, &ServerClient::onReadyRead);
    connect(m_socket, &QSslSocket::disconnected, this, &ServerClient::onDisconnect);
    connect(m_socket, &QSslSocket::errorOccurred, this, &ServerClient::onError);
    connect(m_reconnectTimer, &QTimer::timeout, this, &ServerClient::connectToServer);
    connect(m_proofWatcher, &QFutureWatcherBase::finished, this, &ServerClient::onProofReady);

    if (!QSslSocket::supportsSsl()) {
        logger.error(QStringLiteral("No TLS backend is available (OpenSSL 3 missing?): "
                                    "the backend cannot be reached"));
    }
    connectToServer();
}

void ServerClient::connectToServer() {
    if (m_socket->state() == QAbstractSocket::UnconnectedState) {
        logger.info(QStringLiteral("Connecting to %1").arg(m_endpoint));
        setState(State::Connecting);
        m_buffer.clear();
        m_phase = Phase::Hello;
        m_socket->connectToHostEncrypted(m_host, m_port);
    }
}

void ServerClient::onEncrypted() {
    m_peerSha256 = QCryptographicHash::hash(m_socket->peerCertificate().toDer(),
                                            QCryptographicHash::Sha256);
    logger.info(QStringLiteral("TLS session with %1, certificate %2…")
                    .arg(m_endpoint, QString::fromLatin1(m_peerSha256.toHex(':').left(23))));
    m_reconnectTimer->stop();
}

void ServerClient::onDisconnect() {
    m_socket->readAll();
    connectionLost();
}

void ServerClient::onError(QAbstractSocket::SocketError error) {
    logger.warning(QStringLiteral("Socket error: %1 (%2)")
                       .arg(static_cast<int>(error))
                       .arg(m_socket->errorString()));
    if (m_loginInFlight) {
        requireLogin(QStringLiteral("Palvelimeen ei saada yhteyttä: %1")
                         .arg(m_socket->errorString()));
        return;
    }
    // A backend that ends the session cleanly (a revoked login, a shutdown) sends
    // a TLS close_notify, which arrives here as RemoteHostClosedError while the
    // socket still reads as connected — and stays so, since nothing answers it,
    // so `disconnected` would never come and nothing would reconnect.
    if (m_socket->state() != QAbstractSocket::UnconnectedState) {
        m_socket->abort();
    }
    connectionLost();
}

void ServerClient::connectionLost() {
    m_buffer.clear();
    m_phase = Phase::Hello;
    if (m_loginInFlight) {
        requireLogin(QStringLiteral("Yhteys palvelimeen katkesi kirjautumisen aikana"));
        return;
    }
    if (m_auth == Auth::LoginRequired) {
        // Nothing to retry until the user has typed the password.
        setState(State::Disconnected);
        return;
    }
    if (m_auth != Auth::NoPassword) {
        setAuth(Auth::Offline);
    }
    // Both onError and onDisconnect report one loss; say it once.
    if (!m_reconnectTimer->isActive()) {
        logger.warning(QStringLiteral("Disconnected - reconnect armed (10s)"));
    }
    setState(State::Reconnecting);
    m_reconnectTimer->start();
}

void ServerClient::setState(State state) {
    if (m_state == state) {
        return;
    }
    const bool wasConnected = (m_state == State::Connected);
    m_state = state;
    emit stateTextChanged();
    if ((state == State::Connected) != wasConnected) {
        emit connectedChanged();
    }
}

void ServerClient::setAuth(Auth auth, const QString &message) {
    m_auth = auth;
    m_authMessage = message;
    emit authChanged();
}

void ServerClient::sendPacket(const QByteArray &framed) {
    // Non-blocking write. Qt drains the kernel send buffer on the next event-loop
    // iteration; outbound packets are commands and short JSON requests, so
    // back-pressure never builds. Do NOT add flush()/waitForBytesWritten: it
    // stalls the GUI (and every click) for up to 1 s on a slow network.
    m_socket->write(framed);
    logger.debug(QStringLiteral("Sent outbound packet | size=%1").arg(framed.size()));
}

void ServerClient::sendJson(quint8 type, const QJsonObject &body) {
    sendPacket(protocol::frame(type, protocol::jsonRequestBody(body)));
}

void ServerClient::onReadyRead() {
    m_buffer.append(m_socket->readAll());

    while (true) {
        // Wait for the full 4-byte length prefix.
        if (m_buffer.size() < 4) {
            return;
        }

        quint32 packetLength;
        {
            const QByteArray slice = m_buffer.left(4);
            packetLength = qFromBigEndian<quint32>(slice.constData());
        }

        // Defensive bound (protocol::MAX_PACKET_LENGTH): a corrupt or hostile
        // length prefix must not wrap the size arithmetic or grow the buffer
        // without limit. Reset the connection on violation so the reconnect
        // timer re-establishes a clean, frame-aligned stream.
        if (packetLength == 0 || static_cast<qint64>(packetLength) > protocol::MAX_PACKET_LENGTH) {
            logger.warning(QStringLiteral("Invalid packet length %1 - resetting connection").arg(packetLength));
            m_buffer.clear();
            m_socket->abort();
            return;
        }

        // Wait for the whole frame (64-bit comparison so the add cannot overflow).
        if (m_buffer.size() < static_cast<qint64>(packetLength) + 4) {
            return;
        }

        quint8 packetType;
        {
            const QByteArray slice = m_buffer.mid(4, 1);
            packetType = qFromBigEndian<quint8>(slice.constData());
        }

        // Payload = frame minus the 1 type byte; advance past [length][type][payload].
        const QByteArray payload = m_buffer.mid(5, packetLength - 1);
        m_buffer.remove(0, 4 + packetLength);

        logger.debug(QStringLiteral("Received packet | type=0x%1 | size=%2")
                         .arg(QString::number(packetType, 16))
                         .arg(payload.size()));

        if (m_phase == Phase::Session) {
            emit packetReceived(packetType, payload);
            continue;
        }
        // The login is this class's own business; the snapshot that follows a
        // successful one may already be in the buffer, and goes out as usual.
        handleLoginPacket(packetType, payload);
        if (m_socket->state() != QAbstractSocket::ConnectedState) {
            m_buffer.clear();
            return;
        }
    }
}

// ── Login ──────────────────────────────────────────────────────────────────

void ServerClient::handleLoginPacket(quint8 type, const QByteArray &payload) {
    const auto reply = protocol::readJsonReply(payload);
    const bool expected =
        reply && ((m_phase == Phase::Hello && type == protocol::AUTH_HELLO) ||
                  (m_phase == Phase::Challenge && (type == protocol::AUTH_SCRAM_CHALLENGE ||
                                                   type == protocol::AUTH_RESULT)) ||
                  (m_phase == Phase::Result && type == protocol::AUTH_RESULT));
    if (!expected) {
        logger.warning(QStringLiteral("Unexpected message 0x%1 during login - closing")
                           .arg(QString::number(type, 16)));
        if (m_loginInFlight) {
            requireLogin(QStringLiteral("Kirjautuminen epäonnistui"));
        } else {
            m_socket->abort();
        }
        return;
    }
    const QJsonObject &body = reply->body;
    if (type == protocol::AUTH_HELLO) {
        onHello(body.value(QStringLiteral("passwordSet")).toBool());
    } else if (type == protocol::AUTH_SCRAM_CHALLENGE) {
        onChallenge(body.value(QStringLiteral("message")).toString().toUtf8());
    } else {
        onResult(body);
    }
}

void ServerClient::onHello(bool passwordSet) {
    if (!passwordSet) {
        // Once, not on every 10 s retry.
        if (m_auth != Auth::NoPassword) {
            logger.error(QStringLiteral("The backend has no password set (TESLA_HOMEDASH_PASSWORD)"));
        }
        m_loginInFlight = false;
        m_password.clear();
        setAuth(Auth::NoPassword, kNoPasswordMessage);
        // Retried on the usual timer: setting the password restarts the backend.
        m_socket->abort();
        return;
    }
    if (m_loginInFlight) {
        startPasswordLogin();
        return;
    }
    const auto credential = m_credentials.find(m_endpoint);
    if (!credential) {
        logger.info(QStringLiteral("No login for %1 yet - waiting for the password").arg(m_endpoint));
        requireLogin(QString());
        return;
    }
    if (credential->certSha256 != m_peerSha256) {
        // Never trusted silently: it may be a new certificate on the same backend,
        // or someone else's. The password login proves which.
        logger.warning(QStringLiteral("%1 presented another certificate than at login - "
                                      "asking for the password").arg(m_endpoint));
        requireLogin(QStringLiteral("Palvelimen varmenne on vaihtunut. Kirjaudu uudelleen."));
        return;
    }
    setAuth(Auth::Authenticating);
    m_phase = Phase::Result;
    sendJson(protocol::AUTH_TOKEN, {{QStringLiteral("deviceId"), credential->deviceId},
                                    {QStringLiteral("token"), credential->token}});
}

void ServerClient::startPasswordLogin() {
    setAuth(Auth::Authenticating);
    m_scramStart = scram::start();
    m_phase = Phase::Challenge;
    sendJson(protocol::AUTH_SCRAM_START,
             {{QStringLiteral("message"), QString::fromLatin1(m_scramStart.first)}});
}

void ServerClient::onChallenge(const QByteArray &serverFirst) {
    m_phase = Phase::Deriving;
    // PBKDF2 takes seconds on a Raspberry Pi, so it runs off the GUI thread. The
    // password goes with it and is dropped here.
    m_proofWatcher->setFuture(QtConcurrent::run(
        [password = std::exchange(m_password, QString()), start = m_scramStart, serverFirst,
         binding = m_peerSha256]() { return scram::answer(password, start, serverFirst, binding); }));
}

void ServerClient::onProofReady() {
    // The connection may have ended while the key was being derived.
    if (m_phase != Phase::Deriving || m_socket->state() != QAbstractSocket::ConnectedState) {
        return;
    }
    const std::optional<scram::ClientFinal> final = m_proofWatcher->result();
    if (!final) {
        logger.warning(QStringLiteral("The backend's login challenge was not acceptable"));
        requireLogin(QStringLiteral("Palvelimen vastaus kirjautumiseen oli virheellinen"));
        return;
    }
    m_expectedServerFinal = final->expectedServerFinal;
    m_phase = Phase::Result;
    const QString host = QSysInfo::machineHostName();
    sendJson(protocol::AUTH_SCRAM_PROOF,
             {{QStringLiteral("message"), QString::fromLatin1(final->message)},
              {QStringLiteral("name"), host.isEmpty() ? QStringLiteral("Näyttö") : host}});
}

void ServerClient::onResult(const QJsonObject &result) {
    if (result.value(QStringLiteral("ok")).toBool()) {
        if (m_loginInFlight) {
            // The backend's proof that it knows the password — and so that the
            // certificate this exchange was bound to is really its own.
            const QByteArray serverFinal =
                result.value(QStringLiteral("serverFinal")).toString().toLatin1();
            if (serverFinal != m_expectedServerFinal) {
                logger.warning(QStringLiteral("%1 did not prove it knows the password - "
                                              "not trusting it").arg(m_endpoint));
                requireLogin(QStringLiteral("Palvelimen tunnistus epäonnistui. "
                                            "Yhteys ei ole turvallinen."));
                return;
            }
            m_credentials.store(m_endpoint,
                                {result.value(QStringLiteral("deviceId")).toString(),
                                 result.value(QStringLiteral("token")).toString(), m_peerSha256});
            logger.info(QStringLiteral("Logged in to %1 as %2 - login saved to %3")
                            .arg(m_endpoint, result.value(QStringLiteral("name")).toString(),
                                 m_credentials.path()));
        } else {
            logger.info(QStringLiteral("Logged in to %1").arg(m_endpoint));
        }
        m_loginInFlight = false;
        m_phase = Phase::Session;
        m_promptDismissed = false;
        setAuth(Auth::Authenticated);
        setState(State::Connected);
        return;
    }

    const QString reason = result.value(QStringLiteral("reason")).toString();
    QString message = result.value(QStringLiteral("message")).toString();
    logger.warning(QStringLiteral("Login to %1 refused: %2").arg(m_endpoint, reason));
    if (reason == QLatin1String(protocol::AUTH_REASON_NO_PASSWORD)) {
        m_loginInFlight = false;
        setAuth(Auth::NoPassword, kNoPasswordMessage);
        m_socket->abort();
        return;
    }
    if (reason == QLatin1String(protocol::AUTH_REASON_TOKEN)) {
        // Revoked, expired, or the password changed: this login is gone for good.
        m_credentials.forget(m_endpoint);
        m_promptDismissed = false;
        message += QStringLiteral(". Kirjaudu uudelleen.");
    } else if (reason == QLatin1String(protocol::AUTH_REASON_THROTTLED)) {
        message = QStringLiteral("Liian monta väärää salasanaa. Yritä uudelleen %1 s kuluttua.")
                      .arg(result.value(QStringLiteral("retryAfter")).toInt());
    }
    requireLogin(message.isEmpty() ? QStringLiteral("Kirjautuminen epäonnistui") : message);
}

void ServerClient::requireLogin(const QString &message) {
    m_loginInFlight = false;
    m_password.clear();
    m_phase = Phase::Hello;
    m_reconnectTimer->stop();
    setAuth(Auth::LoginRequired, message);
    m_socket->abort();
    setState(State::Disconnected);
}

void ServerClient::login(const QString &password) {
    if (password.isEmpty()) {
        setAuth(m_auth, QStringLiteral("Anna salasana"));
        return;
    }
    // The prompt offers a password only while the socket is down (requireLogin
    // closed it); anything else is a double tap or a race with a reconnect.
    if (m_loginInFlight || m_socket->state() != QAbstractSocket::UnconnectedState) {
        logger.info(QStringLiteral("Login ignored: a connection is already in progress"));
        return;
    }
    logger.info(QStringLiteral("Logging in to %1 with the password").arg(m_endpoint));
    m_password = password;
    m_loginInFlight = true;
    m_promptDismissed = false;
    m_reconnectTimer->stop();
    setAuth(Auth::Authenticating);
    connectToServer();
}

void ServerClient::dismissLoginPrompt() {
    m_promptDismissed = true;
    emit authChanged();
}

void ServerClient::showLoginPrompt() {
    m_promptDismissed = false;
    emit authChanged();
}

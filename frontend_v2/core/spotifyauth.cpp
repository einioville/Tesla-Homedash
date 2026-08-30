#include "spotifyauth.hh"

#include <QJsonDocument>
#include <QtEndian>

#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("spotify.auth");

// Reads a status(1B) + len(4B) + UTF-8 JSON body, the CONFIG_*/SPOTIFY_AUTH_*
// shape. Leaves *ok false on any truncation, so a malformed frame is refused
// rather than half-parsed.
QJsonObject readStatusJson(const QByteArray &payload, quint8 *status, bool *ok) {
    *ok = false;
    if (payload.size() < 5) {
        return {};
    }
    *status = static_cast<quint8>(payload.at(0));
    const quint32 length = qFromBigEndian<quint32>(payload.constData() + 1);
    if (static_cast<qint64>(payload.size()) < 5 + static_cast<qint64>(length)) {
        return {};
    }
    QJsonParseError error{};
    const QJsonDocument doc =
        QJsonDocument::fromJson(payload.mid(5, static_cast<int>(length)), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject()) {
        return {};
    }
    *ok = true;
    return doc.object();
}
}  // namespace

SpotifyAuth::SpotifyAuth(QObject *parent) : QObject(parent) {}

void SpotifyAuth::attachServer(ServerClient *client) {
    m_server = client;
    connect(client, &ServerClient::packetReceived, this, &SpotifyAuth::onPacket);
    // The backend snapshots SPOTIFY_AUTH_STATUS to every new client, so the
    // authorized/reason pair simply arrives — nothing to request here.
}

void SpotifyAuth::begin() {
    if (m_server == nullptr || !m_server->connected()) {
        setPhase(QStringLiteral("error"), QStringLiteral("Ei yhteyttä palvelimeen"));
        return;
    }
    m_flowActive = true;
    // Acting on the prompt counts as dismissing it: if this flow fails the user
    // already has the progress dialog's error in front of them, and re-raising the
    // prompt the moment they close it would trap them in a loop.
    m_alertDismissed = true;
    setPhase(QStringLiteral("requesting"));
    m_server->sendPacket(protocol::frame(protocol::SPOTIFY_AUTH_GET_URL));
}

void SpotifyAuth::dismissAlert() {
    m_alertDismissed = true;
    updateAlert();
}

void SpotifyAuth::updateAlert() {
    const bool visible = m_needsReauth && !m_alertDismissed &&
                         m_phase == QStringLiteral("idle");
    if (visible == m_alertVisible) {
        return;
    }
    m_alertVisible = visible;
    emit alertVisibleChanged();
}

void SpotifyAuth::cancel() {
    // Fences every reply still in flight. The backend is told nothing: its pending
    // flow expires on its own, and a code is worthless spent or unspent.
    m_flowActive = false;
    setPhase(QStringLiteral("idle"));
}

void SpotifyAuth::setPhase(const QString &phase, const QString &message) {
    if (phase == m_phase && message == m_message) {
        return;
    }
    m_phase = phase;
    m_message = message;
    emit phaseChanged();
    // The prompt must not sit under the progress dialog, and must come back if a
    // flow ends with the grant still broken.
    updateAlert();
}

void SpotifyAuth::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::SPOTIFY_AUTH_STATUS && type != protocol::SPOTIFY_AUTH_URL &&
        type != protocol::SPOTIFY_AUTH_RESULT) {
        return;
    }

    quint8 status = protocol::SPOTIFY_AUTH_ERROR;
    bool ok = false;
    const QJsonObject body = readStatusJson(payload, &status, &ok);
    if (!ok) {
        logger.warning(QStringLiteral("Malformed Spotify auth packet 0x%1")
                           .arg(type, 2, 16, QLatin1Char('0')));
        return;
    }

    switch (type) {
    case protocol::SPOTIFY_AUTH_STATUS: {
        // Deliberately NOT fenced by m_flowActive: this is the backend's snapshot
        // of the grant, sent on every connect, and the card must always show it.
        m_authorized = body.value(QStringLiteral("authorized")).toBool();
        m_reason = body.value(QStringLiteral("reason")).toString();
        m_scope = body.value(QStringLiteral("scope")).toString();
        m_cachePath = body.value(QStringLiteral("cachePath")).toString();
        const bool needs = body.value(QStringLiteral("needsReauth")).toBool();
        if (needs != m_needsReauth) {
            m_needsReauth = needs;
            // Arm the prompt afresh each time the grant goes bad, so a dismissal
            // silences this outage rather than every future one.
            if (!needs) {
                m_alertDismissed = false;
            }
        }
        emit statusChanged();
        updateAlert();
        break;
    }
    case protocol::SPOTIFY_AUTH_URL: {
        // A reply that arrives after the user cancelled must not reopen the dialog
        // for a flow nobody is running any more.
        if (!m_flowActive) {
            return;
        }
        if (status != protocol::SPOTIFY_AUTH_OK) {
            setPhase(QStringLiteral("error"),
                     body.value(QStringLiteral("message")).toString());
            return;
        }
        // The backend has opened the page in the host browser and is listening
        // for the redirect; there is nothing to do here but wait for the RESULT.
        logger.info(QStringLiteral("Spotify consent page opened in the host browser; "
                                   "awaiting the callback"));
        setPhase(QStringLiteral("consent"));
        break;
    }
    case protocol::SPOTIFY_AUTH_RESULT: {
        if (!m_flowActive) {
            return;
        }
        m_flowActive = false;
        const bool succeeded = status == protocol::SPOTIFY_AUTH_OK &&
                               body.value(QStringLiteral("ok")).toBool();
        const QString message = body.value(QStringLiteral("message")).toString();
        // The authorization code is single-use, so a failure means starting over
        // rather than retrying — the dialog says so and offers the button again.
        setPhase(succeeded ? QStringLiteral("done") : QStringLiteral("error"), message);
        logger.info(QStringLiteral("Spotify authorization %1")
                        .arg(succeeded ? QStringLiteral("succeeded")
                                       : QStringLiteral("failed: ") + message));
        break;
    }
    default:
        break;
    }
}

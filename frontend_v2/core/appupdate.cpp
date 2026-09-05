#include "appupdate.hh"

#include <QJsonDocument>
#include <QJsonObject>
#include <QtEndian>

#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("app.update");

// Reads a status(1B) + len(4B) + UTF-8 JSON body — the CONFIG_* / SPOTIFY_* /
// SYSTEM_STATUS shape. Leaves *ok false on any truncation so a malformed frame
// is refused rather than half-parsed.
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

// Frames a JSON request body as len(4B) + UTF-8, the CONFIG_SET payload shape.
QByteArray jsonRequestBody(const QJsonObject &object) {
    const QByteArray json = QJsonDocument(object).toJson(QJsonDocument::Compact);
    QByteArray body;
    body.resize(4);
    qToBigEndian<quint32>(static_cast<quint32>(json.size()), body.data());
    body.append(json);
    return body;
}
}  // namespace

AppUpdate::AppUpdate(QObject *parent) : QObject(parent) {}

void AppUpdate::attachServer(ServerClient *client) {
    m_server = client;
    connect(client, &ServerClient::packetReceived, this, &AppUpdate::onPacket);
    // The backend snapshots UPDATE_STATE to every connecting client, so a
    // reconnect repopulates the card on its own. What it cannot do is clear a
    // "checking" spinner for a request whose reply died with the old socket.
    connect(client, &ServerClient::connectedChanged, this, [this, client]() {
        if (!client->connected()) {
            setChecking(false);
        } else if (m_active) {
            check(true);
        }
    });
}

bool AppUpdate::available() const {
    return m_state.value(QStringLiteral("available")).toBool();
}

QString AppUpdate::reason() const {
    return m_state.value(QStringLiteral("reason")).toString();
}

QString AppUpdate::buildCommit() const {
#ifdef FRONTEND_V2_BUILD_COMMIT
    return QString::fromLatin1(FRONTEND_V2_BUILD_COMMIT);
#else
    return {};
#endif
}

bool AppUpdate::restartPending() const {
    // Only meaningful when both halves are known and nothing is in flight: a run
    // moves the checkout well before it restarts anything, so during one this
    // would be true for entirely expected reasons.
    const QString built = buildCommit();
    if (built.isEmpty() || busy()) {
        return false;
    }
    const QString head =
        m_state.value(QStringLiteral("current")).toMap()
            .value(QStringLiteral("commit")).toString();
    return !head.isEmpty() && head != built;
}

bool AppUpdate::busy() const {
    const QVariantMap job = m_state.value(QStringLiteral("job")).toMap();
    return !job.isEmpty() && !job.value(QStringLiteral("finished")).toBool();
}

void AppUpdate::setActive(bool active) {
    if (active == m_active) {
        return;
    }
    m_active = active;
    emit activeChanged();
    if (m_active) {
        // Opening the card IS the check. The backend rate-limits the network
        // half, so tapping between sections costs nothing beyond a local read.
        check(true);
    }
}

void AppUpdate::check(bool fetch) {
    if (m_server == nullptr || !m_server->connected()) {
        return;
    }
    QJsonObject request;
    request.insert(QStringLiteral("fetch"), fetch);
    setChecking(true);
    m_server->sendPacket(
        protocol::frame(protocol::UPDATE_GET_STATE, jsonRequestBody(request)));
}

void AppUpdate::apply(const QString &channel, const QString &commit) {
    if (m_server == nullptr || !m_server->connected() || commit.isEmpty()) {
        return;
    }
    QJsonObject request;
    request.insert(QStringLiteral("channel"), channel);
    request.insert(QStringLiteral("commit"), commit);
    logger.info(QStringLiteral("Requesting update to %1 (%2)")
                    .arg(commit.left(7), channel));
    m_server->sendPacket(protocol::frame(protocol::UPDATE_APPLY, jsonRequestBody(request)));
}

void AppUpdate::cancel() {
    if (m_server == nullptr || !m_server->connected()) {
        return;
    }
    logger.info(QStringLiteral("Cancelling the running update"));
    m_server->sendPacket(protocol::frame(protocol::UPDATE_CANCEL));
}

void AppUpdate::setChecking(bool checking) {
    if (checking == m_checking) {
        return;
    }
    m_checking = checking;
    emit checkingChanged();
}

void AppUpdate::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::UPDATE_STATE) {
        return;
    }
    quint8 status = protocol::SPOTIFY_AUTH_ERROR;
    bool ok = false;
    const QJsonObject document = readStatusJson(payload, &status, &ok);
    if (!ok) {
        logger.warning(QStringLiteral("Malformed UPDATE_STATE"));
        return;
    }
    if (status != protocol::CONFIG_STATUS_OK) {
        logger.warning(QStringLiteral("Backend could not report the update state"));
        setChecking(false);
        return;
    }
    applyDocument(document.toVariantMap());
}

void AppUpdate::applyDocument(const QVariantMap &document) {
    m_state = document;
    m_loaded = true;
    setChecking(false);
    emit stateChanged();

    // The backend has written a new binary and is about to restart itself; this
    // process is still running the file it replaced, and only a restart picks
    // the new one up. Fenced because the job keeps being broadcast after this
    // flag is set — the restart step's own progress lines arrive behind it — and
    // re-emitting would fire the restart repeatedly.
    const QVariantMap job = m_state.value(QStringLiteral("job")).toMap();
    if (job.isEmpty() || !job.value(QStringLiteral("restartFrontend")).toBool()) {
        return;
    }
    const qint64 startedMs = job.value(QStringLiteral("startedMs")).toLongLong();
    if (startedMs == 0 || startedMs == m_restartedForJobStart) {
        return;
    }
    m_restartedForJobStart = startedMs;
    logger.info(QStringLiteral("Update complete; restarting to run the new build"));
    emit restartRequested();
}

#include "appupdate.hh"

#include <QJsonObject>
#include <QVariantList>

#include "appversion.hh"
#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("app.update");
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

QString AppUpdate::appVersion() const { return appversion::label(); }

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
        check(true);
    }
}

void AppUpdate::setShowPrereleases(bool show) {
    if (show == m_showPrereleases) {
        return;
    }
    m_showPrereleases = show;
    emit showPrereleasesChanged();
    updateNewRelease();
}

void AppUpdate::updateNewRelease() {
    // The backend sends the list newest first.
    QString found;
    const QVariantList releases = m_state.value(QStringLiteral("releases")).toList();
    for (const QVariant &entry : releases) {
        const QVariantMap release = entry.toMap();
        if (release.value(QStringLiteral("prerelease")).toBool() && !m_showPrereleases) {
            continue;
        }
        if (release.value(QStringLiteral("direction")).toString() != QStringLiteral("update")) {
            break;
        }
        if (release.value(QStringLiteral("installable")).toBool()) {
            found = release.value(QStringLiteral("tag")).toString();
            break;
        }
    }
    if (found != m_newRelease) {
        m_newRelease = found;
        emit newReleaseChanged();
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
        protocol::frame(protocol::UPDATE_GET_STATE, protocol::jsonRequestBody(request)));
}

void AppUpdate::apply(const QString &tag) {
    if (m_server == nullptr || !m_server->connected() || tag.isEmpty()) {
        return;
    }
    QJsonObject request;
    request.insert(QStringLiteral("tag"), tag);
    logger.info(QStringLiteral("Requesting the install of %1").arg(tag));
    m_server->sendPacket(
        protocol::frame(protocol::UPDATE_APPLY, protocol::jsonRequestBody(request)));
}

void AppUpdate::cancel() {
    if (m_server == nullptr || !m_server->connected()) {
        return;
    }
    logger.info(QStringLiteral("Cancelling the running install"));
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
    const auto reply = protocol::readJsonReply(payload);
    if (!reply) {
        logger.warning(QStringLiteral("Malformed UPDATE_STATE"));
        return;
    }
    setChecking(false);
    if (reply->status != protocol::CONFIG_STATUS_OK) {
        logger.warning(QStringLiteral("Backend could not report the update state"));
        return;
    }
    m_state = reply->body.toVariantMap();
    m_loaded = true;
    emit stateChanged();
    updateNewRelease();
}

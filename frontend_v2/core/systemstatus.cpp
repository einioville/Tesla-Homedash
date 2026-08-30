#include "systemstatus.hh"

#include <QJsonDocument>
#include <QJsonObject>
#include <QtEndian>

#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("system.status");

// Slow enough not to matter, fast enough that CPU and network read as "now".
// The backend measures its rates over the gap between requests, so this is also
// the averaging window the user sees.
constexpr int kPollMs = 5000;
}  // namespace

SystemStatus::SystemStatus(QObject *parent) : QObject(parent) {
    m_timer.setInterval(kPollMs);
    connect(&m_timer, &QTimer::timeout, this, &SystemStatus::refresh);
}

void SystemStatus::attachServer(ServerClient *client) {
    m_server = client;
    connect(client, &ServerClient::packetReceived, this, &SystemStatus::onPacket);
    // A reconnect while the panel is open should resume immediately rather than
    // wait out a poll interval.
    connect(client, &ServerClient::connectedChanged, this, [this, client]() {
        if (client->connected() && m_active) {
            refresh();
        }
    });
}

void SystemStatus::setActive(bool active) {
    if (active == m_active) {
        return;
    }
    m_active = active;
    emit activeChanged();
    if (m_active) {
        refresh();
        m_timer.start();
    } else {
        m_timer.stop();
    }
}

void SystemStatus::refresh() {
    if (m_server == nullptr || !m_server->connected()) {
        return;
    }
    m_server->sendPacket(protocol::frame(protocol::SYSTEM_GET_STATUS));
}

void SystemStatus::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::SYSTEM_STATUS) {
        return;
    }
    if (payload.size() < 5) {
        logger.warning(QStringLiteral("SYSTEM_STATUS: payload too short"));
        return;
    }
    const quint8 status = static_cast<quint8>(payload.at(0));
    const quint32 length = qFromBigEndian<quint32>(payload.constData() + 1);
    if (static_cast<qint64>(payload.size()) < 5 + static_cast<qint64>(length)) {
        logger.warning(QStringLiteral("SYSTEM_STATUS: truncated body"));
        return;
    }
    if (status != protocol::CONFIG_STATUS_OK) {
        logger.warning(QStringLiteral("Backend could not build the system status"));
        return;
    }

    QJsonParseError error{};
    const QJsonDocument doc =
        QJsonDocument::fromJson(payload.mid(5, static_cast<int>(length)), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject()) {
        logger.warning(QStringLiteral("Malformed SYSTEM_STATUS: %1").arg(error.errorString()));
        return;
    }
    m_data = doc.object().toVariantMap();
    m_loaded = true;
    emit dataChanged();
}

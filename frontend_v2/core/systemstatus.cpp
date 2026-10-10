#include "systemstatus.hh"

#include <QJsonArray>
#include <QJsonObject>

#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("system.status");

// Each poll runs every backend service's health probe, so this is slow; the
// fast-moving host metrics are SystemHistory's.
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
        if (client->connected() && active()) {
            refresh();
        }
    });
}

void SystemStatus::retain() {
    if (++m_consumers == 1) {
        emit activeChanged();
        refresh();
        m_timer.start();
    }
}

void SystemStatus::release() {
    if (m_consumers == 0) {
        logger.warning(QStringLiteral("release() without a matching retain()"));
        return;
    }
    if (--m_consumers == 0) {
        m_timer.stop();
        emit activeChanged();
    }
}

void SystemStatus::openLog(const QString &service, const QString &label) {
    m_logOpen = true;
    m_logService = service;
    m_logLabel = label;
    m_logEntries.clear();
    m_logLoading = m_server != nullptr && m_server->connected();
    emit logChanged();
    if (!m_logLoading) {
        return;
    }
    const QJsonObject request{{QStringLiteral("service"), service}};
    m_server->sendPacket(
        protocol::frame(protocol::SYSTEM_GET_LOG, protocol::jsonRequestBody(request)));
}

void SystemStatus::closeLog() {
    if (!m_logOpen) {
        return;
    }
    m_logOpen = false;
    m_logLoading = false;
    m_logEntries.clear();
    emit logChanged();
}

void SystemStatus::onLogPacket(const QByteArray &payload) {
    const auto reply = protocol::readJsonReply(payload);
    if (!reply) {
        return;
    }
    const QJsonObject &doc = reply->body;
    // A reply for a list since closed, or for another card, is stale.
    if (!m_logOpen || doc.value(QStringLiteral("service")).toString() != m_logService) {
        return;
    }
    m_logEntries = doc.value(QStringLiteral("entries")).toArray().toVariantList();
    m_logLoading = false;
    emit logChanged();
}

void SystemStatus::refresh() {
    if (m_server == nullptr || !m_server->connected()) {
        return;
    }
    m_server->sendPacket(protocol::frame(protocol::SYSTEM_GET_STATUS));
}

void SystemStatus::onPacket(quint8 type, const QByteArray &payload) {
    if (type == protocol::SYSTEM_LOG) {
        onLogPacket(payload);
        return;
    }
    if (type != protocol::SYSTEM_STATUS) {
        return;
    }
    const auto reply = protocol::readJsonReply(payload);
    if (!reply) {
        logger.warning(QStringLiteral("Malformed SYSTEM_STATUS"));
        return;
    }
    if (reply->status != protocol::CONFIG_STATUS_OK) {
        logger.warning(QStringLiteral("Backend could not build the system status"));
        return;
    }
    m_data = reply->body.toVariantMap();
    m_loaded = true;
    emit dataChanged();
}

#include "systemstatus.hh"

#include <QJsonArray>
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
    const QByteArray body =
        QJsonDocument(QJsonObject{{QStringLiteral("service"), service}}).toJson(QJsonDocument::Compact);
    QByteArray payload(4, '\0');
    qToBigEndian<quint32>(static_cast<quint32>(body.size()), payload.data());
    payload.append(body);
    m_server->sendPacket(protocol::frame(protocol::SYSTEM_GET_LOG, payload));
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
    if (payload.size() < 5) {
        return;
    }
    const quint32 length = qFromBigEndian<quint32>(payload.constData() + 1);
    const QJsonObject doc = QJsonDocument::fromJson(payload.mid(5, static_cast<int>(length))).object();
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

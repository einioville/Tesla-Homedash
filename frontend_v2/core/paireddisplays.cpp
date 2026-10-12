#include "paireddisplays.hh"

#include <QJsonArray>
#include <QJsonObject>

#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("paired_displays");
}  // namespace

PairedDisplays::PairedDisplays(QObject *parent) : QObject(parent) {}

void PairedDisplays::attachServer(ServerClient *client) {
    m_server = client;
    connect(client, &ServerClient::packetReceived, this, &PairedDisplays::onPacket);
    connect(client, &ServerClient::connectedChanged, this, [this, client]() {
        if (client->connected() && m_wanted) {
            refresh();
        }
    });
}

void PairedDisplays::refresh() {
    m_wanted = true;
    if (m_server == nullptr || !m_server->connected()) {
        return;
    }
    m_server->sendPacket(protocol::frame(protocol::AUTH_GET_DISPLAYS));
}

void PairedDisplays::revoke(const QString &id) {
    if (m_server == nullptr || !m_server->connected()) {
        return;
    }
    logger.info(QStringLiteral("AUTH_REVOKE %1").arg(id));
    m_server->sendPacket(protocol::frame(
        protocol::AUTH_REVOKE, protocol::jsonRequestBody({{QStringLiteral("id"), id}})));
}

void PairedDisplays::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::AUTH_DISPLAYS) {
        return;
    }
    const auto reply = protocol::readJsonReply(payload);
    if (!reply) {
        logger.warning(QStringLiteral("Malformed AUTH_DISPLAYS"));
        return;
    }
    m_displays = reply->body.value(QStringLiteral("displays")).toArray().toVariantList();
    m_loaded = true;
    emit displaysChanged();
}

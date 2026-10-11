#include "teslafieldeditor.hh"

#include <QJsonArray>
#include <QJsonObject>

#include "../logger.hh"
#include "../protocol.hh"
#include "../serverclient.hh"

namespace {
const Logger logger = Logger::get("tesla.fields");
}  // namespace

TeslaFieldEditor::TeslaFieldEditor(QObject *parent) : QObject(parent) {}

void TeslaFieldEditor::attachServer(ServerClient *client) {
    m_server = client;
    connect(client, &ServerClient::packetReceived, this, &TeslaFieldEditor::onPacket);
    // A backend restart while the card is open must not leave it on a stale
    // table — or on none at all, if it was opened while disconnected.
    connect(client, &ServerClient::connectedChanged, this, [this, client]() {
        if (client->connected() && m_wanted) {
            refresh();
        }
    });
}

void TeslaFieldEditor::refresh() {
    m_wanted = true;
    if (m_server == nullptr || !m_server->connected()) {
        return;
    }
    m_server->sendPacket(protocol::frame(protocol::TESLA_GET_PROPERTY_TABLE));
}

void TeslaFieldEditor::setField(const QString &id, const QString &field, const QVariant &value) {
    if (m_server == nullptr || !m_server->connected()) {
        setLastError(QStringLiteral("Ei yhteyttä palvelimeen"));
        return;
    }
    setLastError(QString());
    QJsonObject request;
    request.insert(QStringLiteral("id"), id);
    request.insert(QStringLiteral("field"), field);
    request.insert(QStringLiteral("value"), QJsonValue::fromVariant(value));
    m_server->sendPacket(
        protocol::frame(protocol::TESLA_SET_PROPERTY, protocol::jsonRequestBody(request)));
    logger.info(QStringLiteral("TESLA_SET_PROPERTY %1.%2 = %3")
                    .arg(id, field, value.toString()));
}

void TeslaFieldEditor::onPacket(quint8 type, const QByteArray &payload) {
    if (type == protocol::TESLA_PROPERTY_TABLE) {
        const auto reply = protocol::readJsonReply(payload);
        if (!reply) {
            logger.warning(QStringLiteral("Malformed TESLA_PROPERTY_TABLE"));
            return;
        }
        if (reply->status != protocol::CONFIG_STATUS_OK) {
            logger.warning(QStringLiteral("Backend could not build the telemetry-field table"));
            return;
        }
        m_fields = reply->body.value(QStringLiteral("properties")).toArray().toVariantList();
        m_loaded = true;
        emit fieldsChanged();
    } else if (type == protocol::TESLA_SET_PROPERTY_RESULT) {
        const auto reply = protocol::readJsonReply(payload);
        if (!reply) {
            logger.warning(QStringLiteral("Malformed TESLA_SET_PROPERTY_RESULT"));
            return;
        }
        const QJsonObject &result = reply->body;
        if (!result.value(QStringLiteral("ok")).toBool()) {
            const QString message = result.value(QStringLiteral("message")).toString();
            logger.warning(QStringLiteral("TESLA_SET_PROPERTY refused: %1").arg(message));
            setLastError(message);
        }
    }
}

void TeslaFieldEditor::setLastError(const QString &message) {
    if (message == m_lastError) {
        return;
    }
    m_lastError = message;
    emit lastErrorChanged();
}

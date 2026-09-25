#include "teslafieldeditor.hh"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QtEndian>

#include "../logger.hh"
#include "../protocol.hh"
#include "../serverclient.hh"

namespace {
const Logger logger = Logger::get("tesla.fields");

// status(1B) + len(4B) + UTF-8 JSON, the shape of both replies. Returns an empty
// document (and logs) for anything malformed.
QJsonDocument readBody(const QByteArray &payload, const QString &what, quint8 *status) {
    if (payload.size() < 5) {
        logger.warning(QStringLiteral("%1: payload too short").arg(what));
        return {};
    }
    *status = static_cast<quint8>(payload.at(0));
    const quint32 length = qFromBigEndian<quint32>(payload.constData() + 1);
    if (static_cast<qint64>(payload.size()) < 5 + static_cast<qint64>(length)) {
        logger.warning(QStringLiteral("%1: truncated body").arg(what));
        return {};
    }
    QJsonParseError error{};
    const QJsonDocument doc =
        QJsonDocument::fromJson(payload.mid(5, static_cast<int>(length)), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject()) {
        logger.warning(QStringLiteral("Malformed %1: %2").arg(what, error.errorString()));
        return {};
    }
    return doc;
}
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
    const QByteArray json = QJsonDocument(request).toJson(QJsonDocument::Compact);
    QByteArray body(4, Qt::Uninitialized);
    qToBigEndian<quint32>(static_cast<quint32>(json.size()), body.data());
    body.append(json);
    m_server->sendPacket(protocol::frame(protocol::TESLA_SET_PROPERTY, body));
    logger.info(QStringLiteral("TESLA_SET_PROPERTY %1.%2 = %3")
                    .arg(id, field, value.toString()));
}

void TeslaFieldEditor::onPacket(quint8 type, const QByteArray &payload) {
    if (type == protocol::TESLA_PROPERTY_TABLE) {
        quint8 status = protocol::CONFIG_STATUS_ERROR;
        const QJsonDocument doc = readBody(payload, QStringLiteral("TESLA_PROPERTY_TABLE"), &status);
        if (!doc.isObject()) {
            return;
        }
        if (status != protocol::CONFIG_STATUS_OK) {
            logger.warning(QStringLiteral("Backend could not build the telemetry-field table"));
            return;
        }
        m_fields = doc.object().value(QStringLiteral("properties")).toArray().toVariantList();
        m_loaded = true;
        emit fieldsChanged();
    } else if (type == protocol::TESLA_SET_PROPERTY_RESULT) {
        quint8 status = protocol::CONFIG_STATUS_ERROR;
        const QJsonDocument doc =
            readBody(payload, QStringLiteral("TESLA_SET_PROPERTY_RESULT"), &status);
        if (!doc.isObject()) {
            return;
        }
        const QJsonObject result = doc.object();
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

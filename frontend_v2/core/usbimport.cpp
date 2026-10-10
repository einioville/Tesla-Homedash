#include "usbimport.hh"

#include <QJsonObject>

#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("usbimport");
}  // namespace

UsbImport::UsbImport(QObject *parent) : QObject(parent) {}

void UsbImport::attachServer(ServerClient *client) {
    m_server = client;
    connect(client, &ServerClient::packetReceived, this, &UsbImport::onPacket);
    connect(client, &ServerClient::connectedChanged, this, &UsbImport::onConnectionChanged);
}

void UsbImport::begin() {
    ++m_flowId;
    m_state.clear();
    listDrives();
}

void UsbImport::listDrives() {
    if (m_server == nullptr || !m_server->connected()) {
        setLocal(QStringLiteral("error"), QStringLiteral("Ei yhteyttä palvelimeen"));
        return;
    }
    setLocal(QStringLiteral("listing"));
    send(protocol::USB_IMPORT_LIST);
}

void UsbImport::scan(const QString &device) {
    QJsonObject fields;
    fields.insert(QStringLiteral("device"), device);
    setLocal(QStringLiteral("scanning"));
    send(protocol::USB_IMPORT_SCAN, fields);
}

void UsbImport::start() {
    QJsonObject fields;
    fields.insert(QStringLiteral("device"), device().value(QStringLiteral("device")).toString());
    logger.info(QStringLiteral("Importing %1 photos from %2")
                    .arg(count())
                    .arg(device().value(QStringLiteral("device")).toString()));
    send(protocol::USB_IMPORT_START, fields);
}

void UsbImport::close() {
    if (m_phase == QLatin1String("idle")) {
        return;
    }
    send(protocol::USB_IMPORT_CLOSE);
    // Advanced so a state already in flight cannot reopen the dialog.
    ++m_flowId;
    m_state.clear();
    setLocal(QStringLiteral("idle"));
}

void UsbImport::send(quint8 type, const QJsonObject &fields) {
    if (m_server == nullptr || !m_server->connected()) {
        return;
    }
    QJsonObject request = fields;
    request.insert(QStringLiteral("flowId"), static_cast<qint64>(m_flowId));
    m_server->sendPacket(protocol::frame(type, protocol::jsonRequestBody(request)));
}

void UsbImport::setLocal(const QString &phase, const QString &message) {
    if (phase == m_phase && message == m_message) {
        return;
    }
    m_phase = phase;
    m_message = message;
    emit stateChanged();
}

void UsbImport::onConnectionChanged() {
    if (m_server == nullptr || m_server->connected() || m_phase == QLatin1String("idle")) {
        return;
    }
    logger.warning(QStringLiteral("Connection lost during a USB import"));
    ++m_flowId;
    setLocal(QStringLiteral("error"), QStringLiteral("Yhteys palvelimeen katkesi"));
}

void UsbImport::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::USB_IMPORT_STATE || m_phase == QLatin1String("idle")) {
        return;
    }
    // The status byte is always OK.
    const auto reply = protocol::readJsonReply(payload);
    if (!reply) {
        logger.warning(QStringLiteral("Malformed USB import state"));
        return;
    }
    const QJsonObject &state = reply->body;
    if (state.value(QStringLiteral("flowId")).toInteger(0) != static_cast<qint64>(m_flowId)) {
        return;
    }
    m_state = state.toVariantMap();
    m_phase = state.value(QStringLiteral("phase")).toString();
    m_message = state.value(QStringLiteral("message")).toString();
    emit stateChanged();
}

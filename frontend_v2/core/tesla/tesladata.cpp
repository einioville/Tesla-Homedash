#include "tesladata.hh"

#include "../protocol.hh"
#include "../serverclient.hh"

#include <QDataStream>
#include <QIODevice>
#include <QLoggingCategory>
#include <QVariantMap>

namespace {
Q_LOGGING_CATEGORY(lcTesla, "frontend_v2.tesla")
}

TeslaData::TeslaData(ServerClient *server, QObject *parent)
    : TeslaDataGen(parent), m_server(server) {
    connect(server, &ServerClient::packetReceived, this, &TeslaData::onPacket);
}

void TeslaData::switchClimate() {
    m_server->sendPacket(protocol::frame(protocol::TESLA_SWITCH_CLIMATE_STATE));
    qCInfo(lcTesla) << "Climate switch command issued";
}

void TeslaData::plusTemp() {
    m_server->sendPacket(protocol::frame(protocol::TESLA_PLUS_TARGET_TEMP));
    qCInfo(lcTesla) << "Target temperature +1 command issued";
}

void TeslaData::minusTemp() {
    m_server->sendPacket(protocol::frame(protocol::TESLA_MINUS_TARGET_TEMP));
    qCInfo(lcTesla) << "Target temperature -1 command issued";
}

void TeslaData::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::MSG_STREAM) {
        return;  // not ours — other datahandlers consume their own types
    }

    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    quint16 streamId;
    stream >> streamId;
    quint8 valueType;
    stream >> valueType;

    const int expected = TeslaDataGen::valueTypeForStream(streamId);
    if (expected < 0) {
        qCWarning(lcTesla) << "No route for stream id" << streamId;
        return;
    }
    if (expected != valueType) {
        qCWarning(lcTesla) << "value_type mismatch for stream" << streamId
                           << "expected" << expected << "got" << valueType;
        return;
    }

    switch (valueType) {
        case protocol::VALUE_TYPE_FLOAT: {
            double value;
            stream >> value;
            quint64 timestamp;
            stream >> timestamp;
            applyValue(streamId, value);
            break;
        }
        case protocol::VALUE_TYPE_STRING: {
            quint16 length;
            stream >> length;
            // Bounds-check the length prefix against the bytes actually present
            // so a malformed frame can't read past the buffer.
            if (device && device->bytesAvailable() < length) {
                qCWarning(lcTesla) << "Truncated string payload for stream" << streamId;
                return;
            }
            QByteArray raw(length, Qt::Uninitialized);
            stream.readRawData(raw.data(), length);
            quint64 timestamp;
            stream >> timestamp;
            applyValue(streamId, QString::fromUtf8(raw));
            break;
        }
        case protocol::VALUE_TYPE_BOOL: {
            quint8 raw;
            stream >> raw;
            quint64 timestamp;
            stream >> timestamp;
            applyValue(streamId, raw == 1);
            break;
        }
        case protocol::VALUE_TYPE_DICT: {
            double latitude;
            stream >> latitude;
            double longitude;
            stream >> longitude;
            quint64 timestamp;
            stream >> timestamp;
            QVariantMap location;
            location.insert(QStringLiteral("latitude"), latitude);
            location.insert(QStringLiteral("longitude"), longitude);
            applyValue(streamId, location);
            break;
        }
        default:
            break;
    }
}

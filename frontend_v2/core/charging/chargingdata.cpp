#include "chargingdata.hh"

#include "../logger.hh"
#include "../protocol.hh"
#include "../serverclient.hh"

#include <QDataStream>
#include <QDateTime>
#include <QIODevice>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPointF>
#include <QString>
#include <limits>

namespace {
const Logger logger = Logger::get("charging");
}

ChargingData::ChargingData(ServerClient *server, QObject *parent)
    : QObject(parent), m_server(server) {
    connect(server, &ServerClient::packetReceived, this, &ChargingData::onPacket);
    // Self-heal: a request written into a disconnected socket is silently dropped, so
    // re-issue any still-pending request when the connection is (re)established.
    connect(server, &ServerClient::connectedChanged, this, &ChargingData::onConnectedChanged);
}

void ChargingData::onPacket(quint8 type, const QByteArray &payload) {
    switch (type) {
        case protocol::CHARGER_STREAM:
            parseStream(payload);
            break;
        case protocol::CHARGING_MONTH:
            parseMonth(payload);
            break;
        case protocol::CHARGER_HISTORY:
            parseChargerHistory(payload);
            break;
        default:
            break;  // not ours
    }
}

void ChargingData::parseStream(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    // A sequence of (sub_id + value) pairs. Unlike the weather frame these values are
    // NOT all one byte wide, so an UNKNOWN sub-id can't be skipped safely (its width is
    // unknown) — stop parsing at one instead of desyncing. All current sub-ids are known
    // and CHARGER_RAW_JSON is last, so version skew only drops trailing new fields.
    while (device->bytesAvailable() >= 1) {
        quint8 subId;
        stream >> subId;
        bool stop = false;
        switch (subId) {
            case protocol::CHARGER_STATUS:
                if (device->bytesAvailable() < 1) { stop = true; break; }
                { quint8 v; stream >> v; m_status = v; }
                break;
            case protocol::CHARGER_PLUG_STATUS:
                if (device->bytesAvailable() < 1) { stop = true; break; }
                { quint8 v; stream >> v; m_plugStatus = v; }
                break;
            case protocol::CHARGER_MODE:
                if (device->bytesAvailable() < 1) { stop = true; break; }
                { quint8 v; stream >> v; m_mode = v; }
                break;
            case protocol::CHARGER_L1_PHASE:
                if (device->bytesAvailable() < 1) { stop = true; break; }
                { quint8 v; stream >> v; m_l1Phase = v; }
                break;
            case protocol::CHARGER_SUPPLY_VOLTAGE:
                if (device->bytesAvailable() < 2) { stop = true; break; }
                { quint16 v; stream >> v; m_supplyVoltage = v; }
                break;
            case protocol::CHARGER_CHARGE_POWER:
                if (device->bytesAvailable() < 8) { stop = true; break; }
                { double v; stream >> v; m_chargePowerW = v; }
                break;
            case protocol::CHARGER_SESSION_ENERGY:
                if (device->bytesAvailable() < 8) { stop = true; break; }
                { double v; stream >> v; m_sessionEnergyKwh = v; }
                break;
            case protocol::CHARGER_GRID_POWER:
                if (device->bytesAvailable() < 8) { stop = true; break; }
                { double v; stream >> v; m_gridPowerW = v; }
                break;
            case protocol::CHARGER_GENERATED_POWER:
                if (device->bytesAvailable() < 8) { stop = true; break; }
                { double v; stream >> v; m_generatedPowerW = v; }
                break;
            case protocol::CHARGER_SUPPLY_FREQUENCY:
                if (device->bytesAvailable() < 8) { stop = true; break; }
                { double v; stream >> v; m_supplyFrequency = v; }
                break;
            case protocol::CHARGER_RAW_JSON: {
                if (device->bytesAvailable() < 4) { stop = true; break; }
                quint32 len;
                stream >> len;
                if (static_cast<quint32>(device->bytesAvailable()) < len) { stop = true; break; }
                QByteArray rawBytes(static_cast<int>(len), Qt::Uninitialized);
                stream.readRawData(rawBytes.data(), static_cast<int>(len));
                const QJsonDocument doc = QJsonDocument::fromJson(rawBytes);
                if (doc.isObject()) {
                    m_raw = doc.object().toVariantMap();
                }
                break;
            }
            default:
                stop = true;  // unknown width — cannot skip, stop the frame
                break;
        }
        if (stop) {
            break;
        }
    }

    m_hasLiveState = true;
    emit liveStateChanged();

    // Extend the rolling power graphs from this frame while the view is live.
    if (m_graphLive) {
        const qint64 now = QDateTime::currentMSecsSinceEpoch();
        appendLive(m_grid, m_gridPowerW, now);
        emit gridChanged();
        emit gridTick();
        appendLive(m_charge, m_chargePowerW, now);
        emit chargeChanged();
        emit chargeTick();
    }
}

void ChargingData::parseMonth(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    // status(1) + 13*double(8) = 105 bytes.
    if (device->bytesAvailable() < 105) {
        logger.warning(QStringLiteral("Charging-month frame too short"));
        setMonthLoading(false);
        return;
    }
    quint8 status;
    stream >> status;
    double chargerKwh;
    double carKwh;
    double wastedKwh;
    double efficiencyPct;
    double carWhPerKm;
    double chargerWhPerKm;
    double drivingKwh;
    double kmMonth;
    double sessionCount;
    double totalChargeS;
    double chargingCostEur;
    double homeGridKwh;
    double homeCostEur;
    stream >> chargerKwh >> carKwh >> wastedKwh >> efficiencyPct >> carWhPerKm
           >> chargerWhPerKm >> drivingKwh >> kmMonth >> sessionCount >> totalChargeS
           >> chargingCostEur >> homeGridKwh >> homeCostEur;

    QVariantMap month;
    month.insert(QStringLiteral("valid"), status == 1);
    month.insert(QStringLiteral("chargerKwh"), chargerKwh);
    month.insert(QStringLiteral("carKwh"), carKwh);
    month.insert(QStringLiteral("wastedKwh"), wastedKwh);
    month.insert(QStringLiteral("efficiencyPct"), efficiencyPct);
    month.insert(QStringLiteral("carWhPerKm"), carWhPerKm);
    month.insert(QStringLiteral("chargerWhPerKm"), chargerWhPerKm);
    month.insert(QStringLiteral("drivingKwh"), drivingKwh);
    month.insert(QStringLiteral("kmMonth"), kmMonth);
    month.insert(QStringLiteral("sessionCount"), sessionCount);
    month.insert(QStringLiteral("totalChargeS"), totalChargeS);
    month.insert(QStringLiteral("chargingCostEur"), chargingCostEur);
    month.insert(QStringLiteral("homeGridKwh"), homeGridKwh);
    month.insert(QStringLiteral("homeCostEur"), homeCostEur);

    m_month = month;
    m_monthRequested = false;
    setMonthLoading(false);
    emit monthChanged();
    emit monthReady();
    logger.debug(QStringLiteral("Charging-month applied | status=%1").arg(status));
}

void ChargingData::parseChargerHistory(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    if (device->bytesAvailable() < 2) {
        logger.warning(QStringLiteral("Charger-history frame too short (id)"));
        return;
    }
    quint16 idLen;
    stream >> idLen;
    if (device->bytesAvailable() < idLen) {
        logger.warning(QStringLiteral("Charger-history frame too short (id body)"));
        return;
    }
    QByteArray idBytes(idLen, '\0');
    stream.readRawData(idBytes.data(), idLen);
    const QString id = QString::fromUtf8(idBytes);

    if (device->bytesAvailable() < 5) {
        logger.warning(QStringLiteral("Charger-history frame too short (header)"));
        return;
    }
    quint8 status;
    stream >> status;
    quint32 count;
    stream >> count;

    QVariantList points;
    if (status == 1) {
        points.reserve(static_cast<int>(count));
        for (quint32 i = 0; i < count; ++i) {
            if (device->bytesAvailable() < 16) {
                logger.warning(QStringLiteral("Truncated charger-history points at %1").arg(i));
                break;
            }
            qint64 ts;
            double value;
            stream >> ts >> value;
            points.append(QVariant::fromValue(QPointF(static_cast<double>(ts), value)));
        }
    }

    const qint64 now = QDateTime::currentMSecsSinceEpoch();
    if (id == QStringLiteral("GridPower")) {
        seedSeries(m_grid, points, now);
        emit gridChanged();
        emit gridReady();
    } else if (id == QStringLiteral("ChargePower")) {
        seedSeries(m_charge, points, now);
        emit chargeChanged();
        emit chargeReady();
    } else {
        return;  // a series this view doesn't graph
    }
    // Both series are requested together; clear the indicator once either lands.
    setHistoryLoading(false);
    logger.debug(QStringLiteral("Charger history applied | id=%1 points=%2 status=%3")
                     .arg(id)
                     .arg(points.size())
                     .arg(status));
}

void ChargingData::seedSeries(Series &s, const QVariantList &points, qint64 nowMs) {
    s.points = points;
    // Show the whole 1 h window on the axis (not just the seeded data extent), matching
    // TeslaHistory's live seed; live appends then roll it forward.
    rollBounds(s, nowMs);
}

void ChargingData::appendLive(Series &s, double value, qint64 nowMs) {
    // Store a real point only when the value changed since the last sample; between
    // changes the step line holds the previous value flat to the advancing right edge.
    const bool changed =
        s.points.isEmpty() || s.points.last().toPointF().y() != value;
    if (changed) {
        s.points.append(QVariant::fromValue(QPointF(static_cast<double>(nowMs), value)));
    }
    rollBounds(s, nowMs);
}

void ChargingData::rollBounds(Series &s, qint64 nowMs) {
    const double left = static_cast<double>(nowMs - kWindowMs);
    // Drop points older than the left edge, but keep the last one before it as the
    // boundary so the value held at the edge is still known (the step line needs it).
    int firstInside = 0;
    while (firstInside < s.points.size() && s.points[firstInside].toPointF().x() < left) {
        ++firstInside;
    }
    const int dropCount = firstInside > 0 ? firstInside - 1 : 0;
    if (dropCount > 0) {
        s.points.remove(0, dropCount);
    }
    s.minX = left;
    s.maxX = static_cast<double>(nowMs);
    double minY = std::numeric_limits<double>::max();
    double maxY = std::numeric_limits<double>::lowest();
    for (const QVariant &p : s.points) {
        const double y = p.toPointF().y();
        minY = qMin(minY, y);
        maxY = qMax(maxY, y);
    }
    if (s.points.isEmpty()) {
        s.minY = 0.0;
        s.maxY = 1.0;
    } else {
        s.minY = minY;
        s.maxY = maxY;
    }
}

QVariantMap ChargingData::seriesMap(const Series &s) {
    QVariantMap m;
    m.insert(QStringLiteral("points"), s.points);
    m.insert(QStringLiteral("minX"), s.minX);
    m.insert(QStringLiteral("maxX"), s.maxX);
    m.insert(QStringLiteral("minY"), s.minY);
    m.insert(QStringLiteral("maxY"), s.maxY);
    m.insert(QStringLiteral("count"), static_cast<int>(s.points.size()));
    return m;
}

void ChargingData::sendHistoryRequest(const QString &id) {
    QByteArray payload;
    QDataStream stream(&payload, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::BigEndian);
    stream << static_cast<quint8>(protocol::HISTORY_RANGE_1H);
    const QByteArray idBytes = id.toUtf8();
    stream << static_cast<quint16>(idBytes.size());
    stream.writeRawData(idBytes.constData(), static_cast<int>(idBytes.size()));
    // Preset range ignores the bounds; send zeros to keep the fixed wire layout.
    stream << static_cast<qint64>(0) << static_cast<qint64>(0);
    m_server->sendPacket(protocol::frame(protocol::CHARGER_GET_HISTORY, payload));
}

void ChargingData::startLive() {
    m_graphLive = true;
    setHistoryLoading(true);
    sendHistoryRequest(QStringLiteral("GridPower"));
    sendHistoryRequest(QStringLiteral("ChargePower"));
    logger.info(QStringLiteral("Charger power history requested (grid + charge)"));
}

void ChargingData::stopLive() {
    m_graphLive = false;
}

void ChargingData::requestMonth() {
    m_monthRequested = true;
    setMonthLoading(true);
    m_server->sendPacket(protocol::frame(protocol::CHARGING_GET_MONTH));
    logger.info(QStringLiteral("Month charging summary requested"));
}

void ChargingData::onConnectedChanged() {
    if (!m_server->connected()) {
        return;
    }
    if (m_graphLive) {
        logger.info(QStringLiteral("Reconnected — re-requesting charger power history"));
        setHistoryLoading(true);
        sendHistoryRequest(QStringLiteral("GridPower"));
        sendHistoryRequest(QStringLiteral("ChargePower"));
    }
    if (m_monthRequested) {
        logger.info(QStringLiteral("Reconnected — re-requesting month charging summary"));
        m_server->sendPacket(protocol::frame(protocol::CHARGING_GET_MONTH));
    }
}

void ChargingData::setMonthLoading(bool loading) {
    if (m_monthLoading == loading) {
        return;
    }
    m_monthLoading = loading;
    emit monthLoadingChanged();
}

void ChargingData::setHistoryLoading(bool loading) {
    if (m_historyLoading == loading) {
        return;
    }
    m_historyLoading = loading;
    emit historyLoadingChanged();
}

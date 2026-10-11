#include "chargingdata.hh"

#include "../logger.hh"
#include "../protocol.hh"
#include "../seriesbounds.hh"
#include "../serverclient.hh"

#include <QDataStream>
#include <QDateTime>
#include <QIODevice>
#include <QPointF>
#include <QString>

namespace {
const Logger logger = Logger::get("charging");
}

ChargingData::ChargingData(ServerClient *server, QObject *parent)
    : QObject(parent), m_server(server) {
    connect(server, &ServerClient::packetReceived, this, &ChargingData::onPacket);
    connect(server, &ServerClient::connectedChanged, this, &ChargingData::onConnectedChanged);
}

void ChargingData::onPacket(quint8 type, const QByteArray &payload) {
    switch (type) {
        case protocol::CHARGER_STREAM:
            parseStream(payload);
            break;
        case protocol::SPOT_PRICE_STREAM:
            parseSpotPrice(payload);
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
            // Sent but not shown: read past them.
            case protocol::CHARGER_PLUG_STATUS:
            case protocol::CHARGER_MODE:
            case protocol::CHARGER_L1_PHASE:
                stop = stream.skipRawData(1) != 1;
                break;
            case protocol::CHARGER_SUPPLY_VOLTAGE:
                stop = stream.skipRawData(2) != 2;
                break;
            case protocol::CHARGER_GENERATED_POWER:
            case protocol::CHARGER_SUPPLY_FREQUENCY:
                stop = stream.skipRawData(8) != 8;
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
            case protocol::CHARGER_RAW_JSON:
                // The last field, so nothing after it needs reaching.
                stop = true;
                break;
            default:
                stop = true;  // unknown width — cannot skip, stop the frame
                break;
        }
        if (stop) {
            break;
        }
    }

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

void ChargingData::parseSpotPrice(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    // status(1) + hour_start_ms(8) + spot(8) + all_in(8) = 25 bytes.
    if (device->bytesAvailable() < 25) {
        logger.warning(QStringLiteral("Spot-price frame too short"));
        return;
    }
    quint8 status;
    qint64 hourStartMs;
    double spot;
    double allIn;
    stream >> status >> hourStartMs >> spot >> allIn;

    // status 0 => no price this hour (fetch failed / unpublished): drop to "no price" so
    // the tile shows "—" rather than a stale value.
    m_hasSpotPrice = (status == 1);
    m_spotPriceEurPerKwh = allIn;
    emit spotPriceChanged();
}

void ChargingData::parseMonth(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    // status(1) + 13*double(8) = 105 bytes.
    if (device->bytesAvailable() < 105) {
        logger.warning(QStringLiteral("Charging-month frame too short"));
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
    emit monthChanged();
    emit monthReady();
    logger.debug(QStringLiteral("Charging-month applied | status=%1").arg(status));
}

void ChargingData::parseChargerHistory(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);

    QString id;
    if (!protocol::readString(stream, id)) {
        logger.warning(QStringLiteral("Charger-history frame too short (id)"));
        return;
    }
    const auto series = protocol::readSeries(stream);
    if (!series) {
        logger.warning(QStringLiteral("Charger-history frame too short (header)"));
        return;
    }
    if (series->truncated) {
        logger.warning(
            QStringLiteral("Truncated charger-history points at %1").arg(series->points.size()));
    }
    const quint8 status = series->status;
    QVariantList points;
    points.reserve(series->points.size());
    for (const QPointF &point : series->points) {
        points.append(QVariant::fromValue(point));
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
    const SeriesBounds bounds = rollLiveWindow(s.points, kWindowMs, nowMs);
    s.minX = bounds.minX;
    s.maxX = bounds.maxX;
    s.minY = bounds.minY;
    s.maxY = bounds.maxY;
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
    m_server->sendPacket(protocol::frame(
        protocol::CHARGER_GET_HISTORY,
        protocol::historyRequestBody(protocol::HISTORY_RANGE_1H, id, 0, 0)));
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

void ChargingData::setHistoryLoading(bool loading) {
    if (m_historyLoading == loading) {
        return;
    }
    m_historyLoading = loading;
    emit historyLoadingChanged();
}

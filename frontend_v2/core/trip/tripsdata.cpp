#include "tripsdata.hh"

#include "../logger.hh"
#include "../protocol.hh"
#include "../serverclient.hh"

#include <QDataStream>
#include <QIODevice>
#include <QString>
#include <QVariantMap>
#include <limits>

namespace {
const Logger logger = Logger::get("trips");
}

TripsData::TripsData(ServerClient *server, QObject *parent)
    : QObject(parent), m_server(server) {
    connect(server, &ServerClient::packetReceived, this, &TripsData::onPacket);
    // Self-heal: a request sent while the socket was down is silently dropped, so
    // re-issue any still-pending request when the connection is (re)established.
    connect(server, &ServerClient::connectedChanged, this, &TripsData::onConnectedChanged);
}

void TripsData::sendTripListRequest(qint64 startMs, qint64 endMs) {
    QByteArray payload;
    QDataStream stream(&payload, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::BigEndian);
    stream << startMs << endMs;
    m_server->sendPacket(protocol::frame(protocol::TRIP_GET_LIST, payload));
    logger.info(QStringLiteral("Trip list requested | window=[%1,%2]").arg(startMs).arg(endMs));
}

void TripsData::sendTripDetailRequest(qint64 startMs, qint64 endMs) {
    QByteArray payload;
    QDataStream stream(&payload, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::BigEndian);
    stream << startMs << endMs;
    m_server->sendPacket(protocol::frame(protocol::TRIP_GET_DETAIL, payload));
    logger.info(QStringLiteral("Trip route requested | id=%1").arg(startMs));
}

void TripsData::sendTripSummaryRequest(qint64 startMs, qint64 endMs) {
    QByteArray payload;
    QDataStream stream(&payload, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::BigEndian);
    stream << startMs << endMs;
    m_server->sendPacket(protocol::frame(protocol::TRIP_GET_SUMMARY, payload));
    logger.info(QStringLiteral("Trip summary requested | id=%1").arg(startMs));
}

void TripsData::sendTripSeriesRequest(qint64 startMs, qint64 endMs, const QString &propertyId) {
    QByteArray payload;
    QDataStream stream(&payload, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::BigEndian);
    stream << startMs << endMs;
    // 2-byte length + raw UTF-8 (NOT `stream << idBytes`, which would prefix a 4-byte
    // QByteArray length and break the id_len(2B)+UTF-8 wire format the backend parses).
    const QByteArray idBytes = propertyId.toUtf8();
    stream << static_cast<quint16>(idBytes.size());
    stream.writeRawData(idBytes.constData(), static_cast<int>(idBytes.size()));
    m_server->sendPacket(protocol::frame(protocol::TRIP_GET_SERIES, payload));
    logger.info(QStringLiteral("Trip series requested | id=%1 property=%2")
                    .arg(startMs)
                    .arg(propertyId));
}

void TripsData::requestTrips(double startMs, double endMs) {
    // A new week means no trip is selected yet — drop any route on screen so the
    // map doesn't keep showing the previous week's trip.
    clearRoute();
    m_reqListStart = static_cast<qint64>(startMs);
    m_reqListEnd = static_cast<qint64>(endMs);
    setTripsLoading(true);
    sendTripListRequest(m_reqListStart, m_reqListEnd);
}

void TripsData::requestRoute(double startMs, double endMs) {
    m_currentTripId = static_cast<qint64>(startMs);
    m_routeEndMs = static_cast<qint64>(endMs);
    setRouteLoading(true);
    sendTripDetailRequest(m_currentTripId, m_routeEndMs);
}

void TripsData::requestSummary(double startMs, double endMs) {
    m_summaryTripId = static_cast<qint64>(startMs);
    m_summaryEndMs = static_cast<qint64>(endMs);
    setSummaryLoading(true);
    sendTripSummaryRequest(m_summaryTripId, m_summaryEndMs);
}

void TripsData::requestSeries(double startMs, double endMs, const QString &propertyId) {
    m_seriesTripId = static_cast<qint64>(startMs);
    m_seriesEndMs = static_cast<qint64>(endMs);
    m_seriesReqPropertyId = propertyId;
    setSeriesLoading(true);
    sendTripSeriesRequest(m_seriesTripId, m_seriesEndMs, propertyId);
}

void TripsData::requestWeekCounts(const QVariantList &weeks) {
    QByteArray payload;
    QDataStream stream(&payload, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::BigEndian);
    stream << static_cast<quint16>(weeks.size());
    for (const QVariant &week : weeks) {
        const QVariantMap entry = week.toMap();
        stream << static_cast<qint64>(entry.value(QStringLiteral("startMs")).toDouble());
        stream << static_cast<qint64>(entry.value(QStringLiteral("endMs")).toDouble());
    }
    // Remember the request so a drop while disconnected can be re-issued on reconnect.
    m_lastWeekCountsPayload = payload;
    m_weekCountsPending = true;
    m_server->sendPacket(protocol::frame(protocol::TRIP_GET_WEEK_COUNTS, payload));
    logger.info(QStringLiteral("Week counts requested | weeks=%1").arg(weeks.size()));
}

void TripsData::onConnectedChanged() {
    if (!m_server->connected())
        return;
    // A pending loading flag means the earlier request never got a reply — most
    // likely it was written into a disconnected socket and dropped. Re-send the raw
    // packet (not requestTrips/requestRoute, which would reset state); the loading
    // flag and tracked window/trip are already set.
    if (m_tripsLoading && m_reqListStart != 0) {
        logger.info(QStringLiteral("Reconnected — re-requesting trip list"));
        sendTripListRequest(m_reqListStart, m_reqListEnd);
    }
    if (m_routeLoading && m_currentTripId != 0) {
        logger.info(QStringLiteral("Reconnected — re-requesting trip route"));
        sendTripDetailRequest(m_currentTripId, m_routeEndMs);
    }
    if (m_weekCountsPending && !m_lastWeekCountsPayload.isEmpty()) {
        logger.info(QStringLiteral("Reconnected — re-requesting week counts"));
        m_server->sendPacket(
            protocol::frame(protocol::TRIP_GET_WEEK_COUNTS, m_lastWeekCountsPayload));
    }
    if (m_summaryLoading && m_summaryTripId != 0) {
        logger.info(QStringLiteral("Reconnected — re-requesting trip summary"));
        sendTripSummaryRequest(m_summaryTripId, m_summaryEndMs);
    }
    if (m_seriesLoading && m_seriesTripId != 0 && !m_seriesReqPropertyId.isEmpty()) {
        logger.info(QStringLiteral("Reconnected — re-requesting trip series"));
        sendTripSeriesRequest(m_seriesTripId, m_seriesEndMs, m_seriesReqPropertyId);
    }
}

void TripsData::clearRoute() {
    m_currentTripId = 0;
    m_route.clear();
    m_routeStart.clear();
    m_routeEnd.clear();
    m_minLat = m_maxLat = m_minLon = m_maxLon = 0.0;
    setRouteLoading(false);
    emit routeChanged();
    // A new week has no trip selected, so the stats panel + graph clear too.
    clearSummaryAndSeries();
}

void TripsData::clearSummaryAndSeries() {
    m_summaryTripId = 0;
    m_summaryEndMs = 0;
    m_summary.clear();
    setSummaryLoading(false);
    emit summaryChanged();

    m_seriesTripId = 0;
    m_seriesEndMs = 0;
    m_seriesReqPropertyId.clear();
    m_seriesPropertyId.clear();
    m_seriesPoints.clear();
    // Neutral (non-degenerate) axis bounds — see parseTripSeries: a zero-width range
    // crashes QtGraphs when the (empty) graph resets its view on clear.
    m_seriesMinX = 0.0;
    m_seriesMaxX = 1.0;
    m_seriesMinY = 0.0;
    m_seriesMaxY = 1.0;
    setSeriesLoading(false);
    emit seriesChanged();
    // seriesReady drives the graph card's reloadFull(); fire it on clear too so the
    // graph empties its line (not just the placeholder) when the week/trip is dropped.
    emit seriesReady();
}

void TripsData::onPacket(quint8 type, const QByteArray &payload) {
    switch (type) {
        case protocol::TRIP_LIST:
            parseTripList(payload);
            break;
        case protocol::TRIP_DETAIL:
            parseTripDetail(payload);
            break;
        case protocol::TRIP_WEEK_COUNTS:
            parseWeekCounts(payload);
            break;
        case protocol::TRIP_SUMMARY:
            parseTripSummary(payload);
            break;
        case protocol::TRIP_SERIES:
            parseTripSeries(payload);
            break;
        default:
            break;  // not ours
    }
}

void TripsData::parseTripList(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    // req_start_ms(8) + req_end_ms(8) + count(2)
    if (device->bytesAvailable() < 18) {
        logger.warning(QStringLiteral("Trip-list frame too short"));
        setTripsLoading(false);
        return;
    }
    qint64 reqStart;
    qint64 reqEnd;
    stream >> reqStart >> reqEnd;
    // Drop a reply for a week the user has already switched away from (a superseded,
    // out-of-order request — the backend dispatches each request as its own task, so
    // two week queries can finish in either order). The current request is still in
    // flight, so leave the loading flag set.
    if (reqStart != m_reqListStart || reqEnd != m_reqListEnd) {
        logger.debug(QStringLiteral("Dropping stale trip-list reply for [%1,%2]")
                         .arg(reqStart)
                         .arg(reqEnd));
        return;
    }
    quint16 count;
    stream >> count;

    QVariantList trips;
    trips.reserve(count);
    for (quint16 i = 0; i < count; ++i) {
        // start_ms(8) + end_ms(8) + distance_km(8) = 24 bytes per record.
        if (device->bytesAvailable() < 24) {
            logger.warning(QStringLiteral("Truncated trip-list frame at entry %1").arg(i));
            break;
        }
        qint64 startMs;
        qint64 endMs;
        double distanceKm;
        stream >> startMs >> endMs >> distanceKm;

        QVariantMap entry;
        // Epoch ms is exactly representable as a double (well under 2^53), so the
        // round-trip back through requestRoute is lossless.
        entry.insert(QStringLiteral("tripId"), static_cast<double>(startMs));
        entry.insert(QStringLiteral("startMs"), static_cast<double>(startMs));
        entry.insert(QStringLiteral("endMs"), static_cast<double>(endMs));
        entry.insert(QStringLiteral("distanceKm"), distanceKm);
        trips.append(entry);
    }

    m_trips = trips;
    setTripsLoading(false);
    emit tripsChanged();
    emit tripsReady();
    logger.debug(QStringLiteral("Trip list applied | trips=%1").arg(trips.size()));
}

void TripsData::parseTripDetail(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    if (device->bytesAvailable() < 8) {
        logger.warning(QStringLiteral("Trip-detail frame too short (id)"));
        setRouteLoading(false);
        return;
    }
    qint64 tripId;
    stream >> tripId;
    // Discard a reply for a trip the user has already switched away from.
    if (tripId != m_currentTripId) {
        logger.debug(QStringLiteral("Dropping stale trip-detail reply for %1").arg(tripId));
        return;
    }
    if (device->bytesAvailable() < 5) {
        logger.warning(QStringLiteral("Trip-detail frame too short (header)"));
        setRouteLoading(false);
        return;
    }
    quint8 status;
    stream >> status;
    quint32 count;
    stream >> count;

    QVariantList route;
    double minLat = std::numeric_limits<double>::max();
    double maxLat = std::numeric_limits<double>::lowest();
    double minLon = std::numeric_limits<double>::max();
    double maxLon = std::numeric_limits<double>::lowest();

    if (status == 1) {
        route.reserve(static_cast<int>(count));
        for (quint32 i = 0; i < count; ++i) {
            // ts(8) + lat(8) + lon(8) + speed(8) = 32 bytes per point.
            if (device->bytesAvailable() < 32) {
                logger.warning(QStringLiteral("Truncated trip-detail points at %1").arg(i));
                break;
            }
            qint64 ts;
            double lat;
            double lon;
            double speed;
            stream >> ts >> lat >> lon >> speed;

            QVariantMap point;
            point.insert(QStringLiteral("latitude"), lat);
            point.insert(QStringLiteral("longitude"), lon);
            point.insert(QStringLiteral("speed"), speed);
            // Timestamp retained (epoch ms as a double) so the graph's inspect cursor
            // can map an inspected time back to the fix's position on the map.
            point.insert(QStringLiteral("ts"), static_cast<double>(ts));
            route.append(point);

            minLat = qMin(minLat, lat);
            maxLat = qMax(maxLat, lat);
            minLon = qMin(minLon, lon);
            maxLon = qMax(maxLon, lon);
        }
    }

    m_route = route;
    m_routeStart.clear();
    m_routeEnd.clear();
    if (route.isEmpty()) {
        m_minLat = m_maxLat = m_minLon = m_maxLon = 0.0;
    } else {
        m_minLat = minLat;
        m_maxLat = maxLat;
        m_minLon = minLon;
        m_maxLon = maxLon;
        // First/last fix drive the start/end markers.
        const QVariantMap first = route.first().toMap();
        const QVariantMap last = route.last().toMap();
        m_routeStart.insert(QStringLiteral("latitude"), first.value(QStringLiteral("latitude")));
        m_routeStart.insert(QStringLiteral("longitude"), first.value(QStringLiteral("longitude")));
        m_routeEnd.insert(QStringLiteral("latitude"), last.value(QStringLiteral("latitude")));
        m_routeEnd.insert(QStringLiteral("longitude"), last.value(QStringLiteral("longitude")));
    }
    setRouteLoading(false);
    emit routeChanged();
    emit routeReady();
    logger.debug(QStringLiteral("Trip route applied | id=%1 points=%2 status=%3")
                     .arg(tripId)
                     .arg(route.size())
                     .arg(status));
}

void TripsData::parseWeekCounts(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    if (device->bytesAvailable() < 2) {
        logger.warning(QStringLiteral("Week-counts frame too short"));
        return;
    }
    quint16 count;
    stream >> count;

    QVariantMap counts;
    for (quint16 i = 0; i < count; ++i) {
        // week_start_ms(8) + trip_count(2) = 10 bytes per week.
        if (device->bytesAvailable() < 10) {
            logger.warning(QStringLiteral("Truncated week-counts frame at entry %1").arg(i));
            break;
        }
        qint64 weekStart;
        quint16 tripCount;
        stream >> weekStart >> tripCount;
        // Keyed by week start (as a string, QVariantMap's key type) so the QML
        // WeekSelector can look up each week's count by its own startMs.
        counts.insert(QString::number(weekStart), static_cast<int>(tripCount));
    }

    m_weekCounts = counts;
    m_weekCountsPending = false;
    emit weekCountsChanged();
    logger.debug(QStringLiteral("Week counts applied | weeks=%1").arg(counts.size()));
}

void TripsData::setTripsLoading(bool loading) {
    if (m_tripsLoading == loading) {
        return;
    }
    m_tripsLoading = loading;
    emit tripsLoadingChanged();
}

void TripsData::setRouteLoading(bool loading) {
    if (m_routeLoading == loading) {
        return;
    }
    m_routeLoading = loading;
    emit routeLoadingChanged();
}

void TripsData::parseTripSummary(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    // trip_id(8) + status(1) + start_ms(8) + end_ms(8) + 7*double(8) = 81 bytes.
    if (device->bytesAvailable() < 81) {
        logger.warning(QStringLiteral("Trip-summary frame too short"));
        setSummaryLoading(false);
        return;
    }
    qint64 tripId;
    stream >> tripId;
    // Discard a reply for a trip the user has already switched away from.
    if (tripId != m_summaryTripId) {
        logger.debug(QStringLiteral("Dropping stale trip-summary reply for %1").arg(tripId));
        return;
    }
    quint8 status;
    stream >> status;
    qint64 startMs;
    qint64 endMs;
    stream >> startMs >> endMs;
    double distanceKm;
    double avgSpeed;
    double maxSpeed;
    double energyWh;
    double whPerKm;
    double startSoc;
    double endSoc;
    stream >> distanceKm >> avgSpeed >> maxSpeed >> energyWh >> whPerKm >> startSoc >> endSoc;

    QVariantMap summary;
    summary.insert(QStringLiteral("valid"), status == 1);
    summary.insert(QStringLiteral("startMs"), static_cast<double>(startMs));
    summary.insert(QStringLiteral("endMs"), static_cast<double>(endMs));
    summary.insert(QStringLiteral("distanceKm"), distanceKm);
    summary.insert(QStringLiteral("avgSpeed"), avgSpeed);
    summary.insert(QStringLiteral("maxSpeed"), maxSpeed);
    summary.insert(QStringLiteral("energyWh"), energyWh);
    summary.insert(QStringLiteral("whPerKm"), whPerKm);
    summary.insert(QStringLiteral("startSoc"), startSoc);
    summary.insert(QStringLiteral("endSoc"), endSoc);
    // SoC used (percentage points), derived from the endpoints; NaN if either is NaN.
    summary.insert(QStringLiteral("socUsed"), startSoc - endSoc);

    m_summary = summary;
    setSummaryLoading(false);
    emit summaryChanged();
    emit summaryReady();
    logger.debug(QStringLiteral("Trip summary applied | id=%1 status=%2").arg(tripId).arg(status));
}

void TripsData::parseTripSeries(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    // trip_id(8) + id_len(2)
    if (device->bytesAvailable() < 10) {
        logger.warning(QStringLiteral("Trip-series frame too short (header)"));
        setSeriesLoading(false);
        return;
    }
    qint64 tripId;
    stream >> tripId;
    quint16 idLen;
    stream >> idLen;
    if (device->bytesAvailable() < idLen) {
        logger.warning(QStringLiteral("Trip-series frame too short (id)"));
        setSeriesLoading(false);
        return;
    }
    QByteArray idBytes(idLen, '\0');
    stream.readRawData(idBytes.data(), idLen);
    const QString propertyId = QString::fromUtf8(idBytes);

    // Drop a reply for a trip/property the user has already switched away from (either
    // key mismatching means a superseded request).
    if (tripId != m_seriesTripId || propertyId != m_seriesReqPropertyId) {
        logger.debug(QStringLiteral("Dropping stale trip-series reply for %1/%2")
                         .arg(tripId)
                         .arg(propertyId));
        return;
    }
    if (device->bytesAvailable() < 5) {
        logger.warning(QStringLiteral("Trip-series frame too short (status)"));
        setSeriesLoading(false);
        return;
    }
    quint8 status;
    stream >> status;
    quint32 count;
    stream >> count;

    QVariantList points;
    double minX = std::numeric_limits<double>::max();
    double maxX = std::numeric_limits<double>::lowest();
    double minY = std::numeric_limits<double>::max();
    double maxY = std::numeric_limits<double>::lowest();

    if (status == 1) {
        points.reserve(static_cast<int>(count));
        for (quint32 i = 0; i < count; ++i) {
            // ts(8) + value(8) = 16 bytes per point.
            if (device->bytesAvailable() < 16) {
                logger.warning(QStringLiteral("Truncated trip-series points at %1").arg(i));
                break;
            }
            qint64 ts;
            double value;
            stream >> ts >> value;
            const double x = static_cast<double>(ts);
            QVariantMap point;
            point.insert(QStringLiteral("x"), x);
            point.insert(QStringLiteral("y"), value);
            points.append(point);

            minX = qMin(minX, x);
            maxX = qMax(maxX, x);
            minY = qMin(minY, value);
            maxY = qMax(maxY, value);
        }
    }

    m_seriesPoints = points;
    m_seriesPropertyId = propertyId;
    if (points.isEmpty()) {
        // Neutral, valid axis bounds so the empty graph still renders. A ValueAxis with
        // min == max divides by zero mapping data to pixels and crashes QtGraphs, so an
        // empty series (a property with no records in the trip window) must NOT leave a
        // zero-width range (mirrors TeslaHistory's empty-bounds handling).
        m_seriesMinX = 0.0;
        m_seriesMaxX = 1.0;
        m_seriesMinY = 0.0;
        m_seriesMaxY = 1.0;
    } else {
        m_seriesMinX = minX;
        m_seriesMaxX = maxX;
        m_seriesMinY = minY;
        m_seriesMaxY = maxY;
        // A single point (or several sharing one timestamp) leaves minX == maxX — a
        // zero-width x-range that also crashes QtGraphs. Pad to a non-zero span centred
        // on the point (y is padded by HistoryGraph's yPad, so only x needs guarding).
        if (m_seriesMaxX <= m_seriesMinX) {
            m_seriesMinX -= 60000.0;  // +/- 1 min in ms
            m_seriesMaxX += 60000.0;
        }
    }
    setSeriesLoading(false);
    emit seriesChanged();
    emit seriesReady();
    logger.debug(QStringLiteral("Trip series applied | id=%1 property=%2 points=%3 status=%4")
                     .arg(tripId)
                     .arg(propertyId)
                     .arg(points.size())
                     .arg(status));
}

void TripsData::setSummaryLoading(bool loading) {
    if (m_summaryLoading == loading) {
        return;
    }
    m_summaryLoading = loading;
    emit summaryLoadingChanged();
}

void TripsData::setSeriesLoading(bool loading) {
    if (m_seriesLoading == loading) {
        return;
    }
    m_seriesLoading = loading;
    emit seriesLoadingChanged();
}

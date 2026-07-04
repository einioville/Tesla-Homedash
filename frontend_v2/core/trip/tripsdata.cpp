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
}

void TripsData::clearRoute() {
    m_currentTripId = 0;
    m_route.clear();
    m_routeStart.clear();
    m_routeEnd.clear();
    m_minLat = m_maxLat = m_minLon = m_maxLon = 0.0;
    setRouteLoading(false);
    emit routeChanged();
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
            // ts is read to consume the field but the map colours by speed and
            // positions by lat/lon, so the timestamp itself is not retained.
            stream >> ts >> lat >> lon >> speed;

            QVariantMap point;
            point.insert(QStringLiteral("latitude"), lat);
            point.insert(QStringLiteral("longitude"), lon);
            point.insert(QStringLiteral("speed"), speed);
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

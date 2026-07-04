#ifndef FRONTEND_V2_TRIPSDATA_HH
#define FRONTEND_V2_TRIPSDATA_HH

#include <QByteArray>
#include <QObject>
#include <QVariantList>
#include <QVariantMap>

class ServerClient;

/**
 * TripsData — the Trips-view datahandler, exposed to QML as the `Trips` singleton.
 * Request/response like TeslaHistory: requestTrips()/requestRoute() send a request
 * and the backend replies to this client only (TRIP_LIST / TRIP_DETAIL).
 *
 *  - `trips` lists the detected trips in the selected week (for the trip dropdown):
 *    each entry is { tripId, startMs, endMs, distanceKm } (epoch ms as doubles;
 *    distanceKm may be NaN for a trip whose distance could not be computed).
 *  - `route` is the selected trip's GPS path: each entry is { latitude, longitude,
 *    speed } (speed in km/h), consumed by the map's colour-graded polyline.
 *  - `routeMinLat/…MaxLon` bound the route so the map can fit its viewport to it.
 *
 * A TRIP_DETAIL reply echoes its trip id (== start_ms); a reply whose id no longer
 * matches the trip last requested is discarded, so quickly switching trips can't
 * draw a stale route. Parsing runs on the GUI thread (the bound properties are not
 * thread-safe); malformed/truncated frames are dropped.
 */
class TripsData : public QObject {
    Q_OBJECT
    Q_PROPERTY(QVariantList trips READ trips NOTIFY tripsChanged)
    Q_PROPERTY(QVariantList route READ route NOTIFY routeChanged)
    Q_PROPERTY(bool hasRoute READ hasRoute NOTIFY routeChanged)
    Q_PROPERTY(double routeMinLat READ routeMinLat NOTIFY routeChanged)
    Q_PROPERTY(double routeMaxLat READ routeMaxLat NOTIFY routeChanged)
    Q_PROPERTY(double routeMinLon READ routeMinLon NOTIFY routeChanged)
    Q_PROPERTY(double routeMaxLon READ routeMaxLon NOTIFY routeChanged)
    // First/last GPS fix of the drawn route ({ latitude, longitude }), empty when no
    // route — the map's start/end markers bind to these.
    Q_PROPERTY(QVariantMap routeStart READ routeStart NOTIFY routeChanged)
    Q_PROPERTY(QVariantMap routeEnd READ routeEnd NOTIFY routeChanged)
    // Per-week trip counts for the week-selector dropdown, keyed by week_start_ms (as
    // a string, since QVariantMap keys are strings) -> int count.
    Q_PROPERTY(QVariantMap weekCounts READ weekCounts NOTIFY weekCountsChanged)
    Q_PROPERTY(bool tripsLoading READ tripsLoading NOTIFY tripsLoadingChanged)
    Q_PROPERTY(bool routeLoading READ routeLoading NOTIFY routeLoadingChanged)

public:
    explicit TripsData(ServerClient *server, QObject *parent = nullptr);

    QVariantList trips() const { return m_trips; }
    QVariantList route() const { return m_route; }
    bool hasRoute() const { return !m_route.isEmpty(); }
    double routeMinLat() const { return m_minLat; }
    double routeMaxLat() const { return m_maxLat; }
    double routeMinLon() const { return m_minLon; }
    double routeMaxLon() const { return m_maxLon; }
    QVariantMap routeStart() const { return m_routeStart; }
    QVariantMap routeEnd() const { return m_routeEnd; }
    QVariantMap weekCounts() const { return m_weekCounts; }
    bool tripsLoading() const { return m_tripsLoading; }
    bool routeLoading() const { return m_routeLoading; }

    // Ask the backend for the trips whose driving falls within [startMs, endMs]
    // (a week). Clears any drawn route first — a fresh week has no trip selected.
    Q_INVOKABLE void requestTrips(double startMs, double endMs);
    // Ask the backend for one trip's GPS+speed route. startMs (the trip id) and
    // endMs are echoed from the chosen `trips` entry.
    Q_INVOKABLE void requestRoute(double startMs, double endMs);
    // Ask the backend for the trip count of each given week (for the dropdown). Each
    // entry is a { startMs, endMs } map; the reply is matched back by week start.
    Q_INVOKABLE void requestWeekCounts(const QVariantList &weeks);
    // Drop the drawn route (e.g. when the week selection changes).
    Q_INVOKABLE void clearRoute();

signals:
    void tripsChanged();
    void routeChanged();
    void weekCountsChanged();
    void tripsReady();   // fired after a TRIP_LIST reply is applied
    void routeReady();   // fired after a matching TRIP_DETAIL reply is applied
    void tripsLoadingChanged();
    void routeLoadingChanged();

private slots:
    void onPacket(quint8 type, const QByteArray &payload);
    // Re-issue a request that was dropped while the socket was down (sendPacket is a
    // non-blocking write that silently no-ops when disconnected). Fires on the
    // ServerClient connection state changing.
    void onConnectedChanged();

private:
    void parseTripList(const QByteArray &payload);
    void parseTripDetail(const QByteArray &payload);
    void parseWeekCounts(const QByteArray &payload);
    void sendTripListRequest(qint64 startMs, qint64 endMs);
    void sendTripDetailRequest(qint64 startMs, qint64 endMs);
    void setTripsLoading(bool loading);
    void setRouteLoading(bool loading);

    ServerClient *m_server;
    QVariantList m_trips;
    QVariantList m_route;
    QVariantMap m_routeStart;
    QVariantMap m_routeEnd;
    QVariantMap m_weekCounts;
    double m_minLat = 0.0;
    double m_maxLat = 0.0;
    double m_minLon = 0.0;
    double m_maxLon = 0.0;
    // The list window last requested. Echoed back in TRIP_LIST; a reply whose window
    // differs is a stale/out-of-order reply (a superseded week) and is dropped. Also
    // used to re-issue the request on reconnect. 0 = none requested yet.
    qint64 m_reqListStart = 0;
    qint64 m_reqListEnd = 0;
    // Trip id (start_ms) + end of the route last requested; a TRIP_DETAIL echoing a
    // different id is a stale reply and is dropped. Also used for reconnect retry.
    qint64 m_currentTripId = 0;
    qint64 m_routeEndMs = 0;
    // Last week-counts request payload + pending flag, so a request dropped while the
    // socket was down is re-issued on reconnect (mirrors the list/route self-heal).
    QByteArray m_lastWeekCountsPayload;
    bool m_weekCountsPending = false;
    bool m_tripsLoading = false;
    bool m_routeLoading = false;
};

#endif  // FRONTEND_V2_TRIPSDATA_HH

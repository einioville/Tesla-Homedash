#ifndef FRONTEND_V2_CURRENTDRIVE_HH
#define FRONTEND_V2_CURRENTDRIVE_HH

#include <QByteArray>
#include <QGeoCoordinate>
#include <QList>
#include <QObject>
#include <QTimer>

#include "routebands.hh"

class ServerClient;
class TeslaData;

/**
 * CurrentDrive — the drive under way, or the last trip while the car is parked, for the maps'
 * route layer (QML `CurrentDrive`). The backend finds it with the Trips view's own detection
 * (TRIP_GET_CURRENT, TripLoader.current_trip: a drive counts from the first metres, a finished
 * trip only past the minimum distance); this side adds each live fix to a drive under way, so
 * the line grows behind the car between requests.
 *
 *  - `route` is the drive's fixes up to the one before the newest, with the speed at each,
 *    as the geometry the maps draw (RouteBands). The car arrow eases from one fix to the next
 *    over a second, so the map draws `route` and a tail from `tailStart` (its last point) to
 *    the arrow itself, and the line never runs ahead of the car. A live fix extends the
 *    route; a reply replaces it.
 *  - `live` is true while a drive is under way: the backend reports one, or the car is out of
 *    Park before the backend has logged it. `active` is true while there is a route at all —
 *    a drive, or the last trip. A finished trip is drawn whole, its last fix included, and
 *    the car leaving Park starts the next drive empty.
 *
 * Asked only while `watched` — while a map on screen draws the route, each holding it with
 * retain() and letting go with release(), since the dashboard's map and the Kartta view's can
 * overlap as one view is built and another left. Asked on becoming watched, on reconnect, a
 * moment after the gear changes, and every minute while a drive is active, which is how its end
 * is noticed.
 */
class CurrentDrive : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool watched READ watched NOTIFY watchedChanged)
    Q_PROPERTY(bool active READ active NOTIFY activeChanged)
    Q_PROPERTY(bool live READ live NOTIFY liveChanged)
    Q_PROPERTY(RouteBands *route READ route CONSTANT)
    Q_PROPERTY(QGeoCoordinate tailStart READ tailStart NOTIFY tailStartChanged)

public:
    CurrentDrive(ServerClient *server, TeslaData *tesla, QObject *parent = nullptr);

    bool watched() const { return m_watched; }
    Q_INVOKABLE void retain();
    Q_INVOKABLE void release();
    bool active() const { return m_active; }
    bool live() const { return m_live; }
    RouteBands *route() { return &m_route; }
    QGeoCoordinate tailStart() const;

signals:
    void watchedChanged();
    void activeChanged();
    void liveChanged();
    void tailStartChanged();

private:
    void setWatched(bool watched);
    void request();
    void onPacket(quint8 type, const QByteArray &payload);
    void onLocation();
    void onGear();
    // Takes `fix` as the newest; the one before it joins the path unless it is too
    // close to the path's end to be worth a point (a parked car's GPS jitter). True
    // when it joined.
    bool addFix(const QGeoCoordinate &fix, qreal speed);
    // Takes the path as the route drawn.
    void resetRoute();
    void clear();
    bool parked() const;
    QGeoCoordinate liveFix() const;
    void updateState();

    ServerClient *m_server;
    TeslaData *m_tesla;
    bool m_watched = false;
    int m_watchers = 0;
    // The last reply named a drive under way.
    bool m_backendLive = false;
    // The path is a finished trip, drawn while the car is parked.
    bool m_showingLast = false;
    bool m_active = false;
    bool m_live = false;
    QList<RouteBands::Fix> m_path;
    RouteBands m_route;
    QGeoCoordinate m_head;
    qreal m_headSpeed = 0;
    QTimer m_poll;
    QTimer m_gearSettle;
};

#endif  // FRONTEND_V2_CURRENTDRIVE_HH

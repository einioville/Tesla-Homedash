#ifndef FRONTEND_V2_CURRENTDRIVE_HH
#define FRONTEND_V2_CURRENTDRIVE_HH

#include <QByteArray>
#include <QGeoCoordinate>
#include <QList>
#include <QObject>
#include <QTimer>

class ServerClient;
class TeslaData;

/**
 * CurrentDrive — the drive under way, for the Kartta view's route layer (QML `CurrentDrive`).
 * The backend finds it with the Trips view's own detection (TRIP_GET_CURRENT: the last trip
 * of the past day, unless the car has been parked longer than a stop merged into a trip);
 * this side adds each live fix to it, so the line grows behind the car between requests.
 *
 *  - `path` is the drive's fixes up to the one before the newest, `speeds` the speed at each
 *    (km/h). The car arrow eases from one fix to the next over a second, so the map draws
 *    `path` and a tail from `tailStart` (its last point) to the arrow itself, and the line
 *    never runs ahead of the car. A live fix extends `path`; a reply replaces it and bumps
 *    `generation`, so a view can build on what it drew while the path only grows.
 *  - `active` is true while a drive is under way: the backend reports one, or the car is out
 *    of Park — a drive shorter than the backend's minimum distance is not a trip yet, but it
 *    is being driven, and its fixes are kept from the moment it shifted.
 *
 * Asked only while `watched`: on becoming watched, on reconnect, a moment after the gear
 * changes, and every minute while a drive is active, which is how its end is noticed.
 */
class CurrentDrive : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool watched READ watched WRITE setWatched NOTIFY watchedChanged)
    Q_PROPERTY(bool active READ active NOTIFY activeChanged)
    Q_PROPERTY(QList<QGeoCoordinate> path READ path NOTIFY pathChanged)
    Q_PROPERTY(QList<qreal> speeds READ speeds NOTIFY pathChanged)
    Q_PROPERTY(int generation READ generation NOTIFY pathChanged)
    Q_PROPERTY(QGeoCoordinate tailStart READ tailStart NOTIFY pathChanged)

public:
    CurrentDrive(ServerClient *server, TeslaData *tesla, QObject *parent = nullptr);

    bool watched() const { return m_watched; }
    void setWatched(bool watched);
    bool active() const { return m_active; }
    QList<QGeoCoordinate> path() const { return m_path; }
    QList<qreal> speeds() const { return m_speeds; }
    int generation() const { return m_generation; }
    QGeoCoordinate tailStart() const { return m_path.isEmpty() ? QGeoCoordinate() : m_path.last(); }

signals:
    void watchedChanged();
    void activeChanged();
    void pathChanged();

private:
    void request();
    void onPacket(quint8 type, const QByteArray &payload);
    void onLocation();
    void onGear();
    // Takes `fix` as the newest; the one before it joins the path unless it is too
    // close to the path's end to be worth a point (a parked car's GPS jitter).
    void addFix(const QGeoCoordinate &fix, qreal speed);
    void clear();
    bool parked() const;
    QGeoCoordinate liveFix() const;
    void updateActive();

    ServerClient *m_server;
    TeslaData *m_tesla;
    bool m_watched = false;
    // The last reply named a drive.
    bool m_backendDrive = false;
    bool m_active = false;
    QList<QGeoCoordinate> m_path;
    QList<qreal> m_speeds;
    QGeoCoordinate m_head;
    qreal m_headSpeed = 0;
    int m_generation = 0;
    QTimer m_poll;
    QTimer m_gearSettle;
};

#endif  // FRONTEND_V2_CURRENTDRIVE_HH

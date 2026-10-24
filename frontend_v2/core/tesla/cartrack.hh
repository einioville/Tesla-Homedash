#ifndef FRONTEND_V2_CARTRACK_HH
#define FRONTEND_V2_CARTRACK_HH

#include <QElapsedTimer>
#include <QList>
#include <QObject>

/**
 * CarTrack — where the maps draw the car: moved along the path of its fixes kLagS behind the
 * car, at the speed it reported then. TeslaData feeds it; each map shows it through a
 * CarMotion, and CurrentDrive extends the drawn route as the car reaches each fix.
 * Load-bearing:
 *
 *  - **Neither the arrival nor the car's timestamp says when a position was true.** On some
 *    drives a fifth of the fixes come 2 s after the last by the car's own stamp yet hold one
 *    second of road, and others a second after it with two (measured against VehicleSpeed); the
 *    position and its stamp are up to a second apart. A glide of a fixed second toward each new
 *    fix, or a playback by the stamps, stands still and then dashes. The path's shape and the
 *    reported speed are what hold, so the car moves along the one at the other.
 *  - **The car shown runs kLagS behind, so it takes the speed reported kLagS ago**, and should be
 *    as far behind the newest fix as the reported speeds since then add up to. A gentle
 *    correction holds that: the error, less a deadband of kBandS of road, over kCorrectionS —
 *    a fix that brings two seconds of road changes the speed by a few per cent instead of
 *    doubling it. Standing, the correction is quicker (kRestCorrectionS), so a car that has
 *    stopped is brought onto its last fix in a second or two instead of creeping there.
 *  - **The speed shown eases toward that over kSpeedEaseS**, both ways: each fix moves the
 *    correction in a step, which taken at once would jolt the car once a second.
 *  - **It never passes the newest fix**, and brakes into it over its last kApproachS of road:
 *    kLagS is room for a fix a second late, and a later one slows the car down instead of
 *    stopping it dead, rather than guessing the road on.
 *  - Replayed over three logged drives at 60 frames a second, the car moved slower than a
 *    quarter of its speed in at most 0.4 % of the frames and never faster than 1.75×, with a
 *    frame-to-frame acceleration of 5–6 m/s² RMS; the fixed glide stalled in 7–34 % of them,
 *    dashed in up to 30 % and shook at 110–160 m/s².
 *  - **The heading is the car's at the point shown**: a position is mapped back to a car time
 *    between its two fixes, and the GpsHeading there is taken, so the arrow turns where the
 *    path turns rather than kLagS before.
 *  - **advance() is the one clock.** The track moves only when asked, to the moment asked, and a
 *    moment already passed changes nothing — every map asking in one frame sees the car at one
 *    place. Asked after more than kCatchUpMs (no map was live), it places the car at once.
 */
class CarTrack : public QObject {
    Q_OBJECT

public:
    struct State {
        bool valid = false;
        double latitude = 0.0;
        double longitude = 0.0;
        // Degrees clockwise from north, [0, 360); 0 before any heading.
        double heading = 0.0;
    };

    explicit CarTrack(QObject *parent = nullptr);

    // Monotonic milliseconds, fractional: a frame is 16.7 ms, and whole ones would step the car
    // unevenly from frame to frame.
    double now() const { return m_clock.nsecsElapsed() / 1e6; }
    // `carMs` is when the car sent it (epoch ms); one no newer than the last is a repeat (a
    // reconnect's snapshot) and is dropped.
    void addFix(double latitude, double longitude, qint64 carMs, double nowMs);
    void addHeading(double degrees, qint64 carMs);
    void setSpeed(double kmh, double nowMs);
    // Moves the car on to `nowMs` and answers where it is.
    State advance(double nowMs);
    // Whether advance() would still move the car: it has not reached the newest fix.
    bool moving() const;
    // The car time of the newest fix the car has reached; 0 before any.
    qint64 reachedMs() const { return m_reachedMs; }

signals:
    // A fix joined the path.
    void fixAdded(double latitude, double longitude, qint64 carMs);
    // Anything arrived: a fix, a heading or a speed.
    void changed();
    void reachedChanged();

private:
    struct Point {
        qint64 carMs;
        double latitude;
        double longitude;
        // Metres along the path.
        double distance;
    };
    struct Heading {
        qint64 carMs;
        double degrees;
    };
    struct Speed {
        // When it arrived, on now()'s clock.
        double atMs;
        // Metres a second.
        double speed;
    };

    void step(double seconds, double atMs);
    void updateReached();
    double headingAt(double carMs) const;
    double speedAt(double atMs) const;
    // The road the reported speeds add up to from kLagS before `atMs` to it.
    double roadSince(double atMs) const;

    QElapsedTimer m_clock;
    QList<Point> m_path;
    QList<Heading> m_headings;
    QList<Speed> m_speeds;
    // Where the car is, in metres along the path.
    double m_distance = 0.0;
    // The speed shown, metres a second.
    double m_speed = 0.0;
    double m_advancedAt = 0.0;
    qint64 m_reachedMs = 0;
};

#endif  // FRONTEND_V2_CARTRACK_HH

#ifndef FRONTEND_V2_CARMOTION_HH
#define FRONTEND_V2_CARMOTION_HH

#include <QObject>
#include <QPointer>

#include "cartrack.hh"

class TeslaData;

/**
 * CarMotion — the car as one map draws it (QML `CarMotion`, one per TeslaMap), read off the
 * shared CarTrack. While `live` it moves every frame, stepped by an animation on Qt's animation
 * driver so the steps fall on the frames; while not, it is placed again at each arrival and
 * nothing runs — a hidden map does no per-frame work. The animation stops whenever the car has
 * reached the newest fix, so a parked car keeps no frames coming.
 */
class CarMotion : public QObject {
    Q_OBJECT
    // Tesla, whose track this shows.
    Q_PROPERTY(QObject *source READ source WRITE setSource NOTIFY sourceChanged)
    Q_PROPERTY(bool live READ live WRITE setLive NOTIFY liveChanged)
    // False until the first fix.
    Q_PROPERTY(bool valid READ valid NOTIFY validChanged)
    Q_PROPERTY(double latitude READ latitude NOTIFY positionChanged)
    Q_PROPERTY(double longitude READ longitude NOTIFY positionChanged)
    // Degrees clockwise from north, [0, 360).
    Q_PROPERTY(double heading READ heading NOTIFY headingChanged)

public:
    explicit CarMotion(QObject *parent = nullptr);

    QObject *source() const;
    void setSource(QObject *source);
    bool live() const { return m_live; }
    void setLive(bool live);
    bool valid() const { return m_state.valid; }
    double latitude() const { return m_state.latitude; }
    double longitude() const { return m_state.longitude; }
    double heading() const { return m_state.heading; }

signals:
    void sourceChanged();
    void liveChanged();
    void validChanged();
    void positionChanged();
    void headingChanged();

private:
    class Ticker;

    CarTrack *track() const;
    void onTrackChanged();
    void sample();

    QPointer<TeslaData> m_source;
    bool m_live = false;
    CarTrack::State m_state;
    Ticker *m_ticker;
};

#endif  // FRONTEND_V2_CARMOTION_HH

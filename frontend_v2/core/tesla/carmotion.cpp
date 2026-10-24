#include "carmotion.hh"

#include <QAbstractAnimation>

#include "tesladata.hh"

// Runs until stopped, calling sample() on every tick of the animation driver.
class CarMotion::Ticker : public QAbstractAnimation {
public:
    explicit Ticker(CarMotion *owner) : QAbstractAnimation(owner), m_owner(owner) {}
    int duration() const override { return -1; }

protected:
    void updateCurrentTime(int) override { m_owner->sample(); }

private:
    CarMotion *m_owner;
};

CarMotion::CarMotion(QObject *parent) : QObject(parent), m_ticker(new Ticker(this)) {}

QObject *CarMotion::source() const {
    return m_source.data();
}

void CarMotion::setSource(QObject *source) {
    auto *tesla = qobject_cast<TeslaData *>(source);
    if (tesla == m_source) {
        return;
    }
    if (CarTrack *old = track()) {
        disconnect(old, &CarTrack::changed, this, &CarMotion::onTrackChanged);
    }
    m_source = tesla;
    if (CarTrack *now = track()) {
        connect(now, &CarTrack::changed, this, &CarMotion::onTrackChanged);
    }
    emit sourceChanged();
    onTrackChanged();
}

void CarMotion::setLive(bool live) {
    if (live == m_live) {
        return;
    }
    m_live = live;
    emit liveChanged();
    if (m_live) {
        onTrackChanged();
    } else {
        m_ticker->stop();
    }
}

CarTrack *CarMotion::track() const {
    return m_source ? m_source->track() : nullptr;
}

void CarMotion::onTrackChanged() {
    sample();
    CarTrack *carTrack = track();
    if (m_live && carTrack && carTrack->moving()
        && m_ticker->state() != QAbstractAnimation::Running) {
        m_ticker->start();
    }
}

void CarMotion::sample() {
    CarTrack *carTrack = track();
    if (!carTrack) {
        return;
    }
    const CarTrack::State state = carTrack->advance(carTrack->now());
    const CarTrack::State was = m_state;
    m_state = state;
    if (state.valid != was.valid) {
        emit validChanged();
    }
    if (state.latitude != was.latitude || state.longitude != was.longitude) {
        emit positionChanged();
    }
    if (state.heading != was.heading) {
        emit headingChanged();
    }
    if (!carTrack->moving() && m_ticker->state() == QAbstractAnimation::Running) {
        m_ticker->stop();
    }
}

#include "cartrack.hh"

#include <algorithm>
#include <cmath>
#include <numbers>

namespace {
// How far behind the car it is shown: room for a fix a second late before it has to wait.
constexpr double kLagS = 1.5;
// The correction's time constant while moving and while standing, and its deadband in
// seconds of road: within the band the car runs at the reported speed alone.
constexpr double kCorrectionS = 4.0;
constexpr double kRestCorrectionS = 1.0;
constexpr double kBandS = 0.5;
// From standing to this speed (m/s) the correction slows from kRestCorrectionS to kCorrectionS.
constexpr double kRestSpeed = 0.5;
constexpr double kMovingSpeed = 2.0;
// The speed shown eases toward the one wanted over this long: a fix moves the correction in a
// step, and the reported speed changes in steps, neither of which may jolt the car.
constexpr double kSpeedEaseS = 0.4;
// Within this many seconds of road of the newest fix the car brakes into it, so a late fix
// slows it down instead of stopping it dead on the fix.
constexpr double kApproachS = 0.5;
// The longest integration step.
constexpr double kStepS = 0.05;
// Asked after a longer pause than this, the track places the car at once.
constexpr double kCatchUpMs = 2000.0;
// A fix this far from the last starts the path afresh with the car on it: a car driven while
// the stream was down, or a first live fix far from a stale snapshot.
constexpr double kJumpMetres = 500.0;
// Closer than this to the newest fix, the car is on it.
constexpr double kArrivedMetres = 0.05;
constexpr int kKeptHeadings = 16;
// Speeds are kept while they are this recent, and the newest older one.
constexpr double kKeptSpeedsMs = 10000.0;

double metres(double lat1, double lon1, double lat2, double lon2) {
    constexpr double kMetresPerDegree = 111320.0;
    const double north = (lat2 - lat1) * kMetresPerDegree;
    const double east =
        (lon2 - lon1) * kMetresPerDegree * std::cos(lat1 * std::numbers::pi / 180.0);
    return std::hypot(north, east);
}

double normalized(double degrees) {
    const double d = std::fmod(degrees, 360.0);
    return d < 0.0 ? d + 360.0 : d;
}

// The turn from `from` to `to` the short way, in (-180, 180].
double turn(double from, double to) {
    const double d = normalized(to - from);
    return d > 180.0 ? d - 360.0 : d;
}
}  // namespace

CarTrack::CarTrack(QObject *parent) : QObject(parent) {
    m_clock.start();
}

void CarTrack::addFix(double latitude, double longitude, qint64 carMs, double nowMs) {
    if (!m_path.isEmpty() && carMs <= m_path.last().carMs) {
        return;
    }
    advance(nowMs);
    if (m_path.isEmpty()
        || metres(m_path.last().latitude, m_path.last().longitude, latitude, longitude)
               > kJumpMetres) {
        m_path = {{carMs, latitude, longitude, 0.0}};
        m_distance = 0.0;
    } else {
        const Point &last = m_path.last();
        m_path.append({carMs, latitude, longitude,
                       last.distance + metres(last.latitude, last.longitude, latitude, longitude)});
    }
    updateReached();
    emit fixAdded(latitude, longitude, carMs);
    emit changed();
}

void CarTrack::addHeading(double degrees, qint64 carMs) {
    if (!m_headings.isEmpty() && carMs <= m_headings.last().carMs) {
        return;
    }
    m_headings.append({carMs, degrees});
    if (m_headings.size() > kKeptHeadings) {
        m_headings.removeFirst();
    }
    emit changed();
}

void CarTrack::setSpeed(double kmh, double nowMs) {
    advance(nowMs);
    m_speeds.append({nowMs, std::max(0.0, kmh / 3.6)});
    while (m_speeds.size() >= 2 && m_speeds.at(1).atMs < nowMs - kKeptSpeedsMs) {
        m_speeds.removeFirst();
    }
    emit changed();
}

CarTrack::State CarTrack::advance(double nowMs) {
    const double elapsed = nowMs - m_advancedAt;
    if (elapsed > 0.0) {
        m_advancedAt = nowMs;
        if (!m_path.isEmpty()) {
            if (elapsed > kCatchUpMs) {
                m_speed = speedAt(nowMs - kLagS * 1000.0);
                const double newest = m_path.last().distance;
                m_distance = std::clamp(newest - roadSince(nowMs), m_distance, newest);
            } else {
                const double stepMs = kStepS * 1000.0;
                for (double at = nowMs - elapsed; at < nowMs; at += stepMs) {
                    const double to = std::min(at + stepMs, nowMs);
                    step((to - at) / 1000.0, to);
                }
            }
            updateReached();
        }
    }

    State state;
    if (m_path.isEmpty()) {
        return state;
    }
    state.valid = true;
    const Point &last = m_path.last();
    if (m_distance >= last.distance) {
        state.latitude = last.latitude;
        state.longitude = last.longitude;
        state.heading = m_headings.isEmpty() ? 0.0 : normalized(m_headings.last().degrees);
        return state;
    }
    // updateReached() leaves the car on the first segment.
    const Point &a = m_path.at(0);
    const Point &b = m_path.at(1);
    const double k = (m_distance - a.distance) / (b.distance - a.distance);
    state.latitude = a.latitude + (b.latitude - a.latitude) * k;
    state.longitude = a.longitude + (b.longitude - a.longitude) * k;
    state.heading = headingAt(a.carMs + (b.carMs - a.carMs) * k);
    return state;
}

bool CarTrack::moving() const {
    return !m_path.isEmpty() && m_distance < m_path.last().distance;
}

void CarTrack::step(double seconds, double atMs) {
    const double newest = m_path.last().distance;
    const double lead = newest - m_distance;
    const double then = speedAt(atMs - kLagS * 1000.0);
    const double error = lead - roadSince(atMs);
    const double band = then * kBandS;
    const double moving = std::clamp((then - kRestSpeed) / (kMovingSpeed - kRestSpeed), 0.0, 1.0);
    const double tau = kRestCorrectionS + (kCorrectionS - kRestCorrectionS) * moving;
    double correction = 0.0;
    if (error > band) {
        correction = (error - band) / tau;
    } else if (error < -band) {
        correction = (error + band) / tau;
    }
    const double wanted = std::max(0.0, then + correction);
    m_speed += (wanted - m_speed) * (1.0 - std::exp(-seconds / kSpeedEaseS));
    m_speed = std::min(m_speed, lead / kApproachS);
    m_distance = std::min(m_distance + m_speed * seconds, newest);
    if (newest - m_distance < kArrivedMetres) {
        m_distance = newest;
    }
}

// Drops the fixes the car has passed but the one it last reached, which is the first.
void CarTrack::updateReached() {
    while (m_path.size() >= 2 && m_path.at(1).distance <= m_distance) {
        m_path.removeFirst();
    }
    const qint64 reached = m_path.isEmpty() ? 0 : m_path.first().carMs;
    if (reached != m_reachedMs) {
        m_reachedMs = reached;
        emit reachedChanged();
    }
}

double CarTrack::headingAt(double carMs) const {
    if (m_headings.isEmpty()) {
        return 0.0;
    }
    if (carMs >= m_headings.last().carMs) {
        return normalized(m_headings.last().degrees);
    }
    if (carMs <= m_headings.first().carMs) {
        return normalized(m_headings.first().degrees);
    }
    for (qsizetype i = m_headings.size() - 1; i > 0; --i) {
        const Heading &a = m_headings.at(i - 1);
        if (a.carMs <= carMs) {
            const Heading &b = m_headings.at(i);
            const double k = (carMs - a.carMs) / static_cast<double>(b.carMs - a.carMs);
            return normalized(a.degrees + turn(a.degrees, b.degrees) * k);
        }
    }
    return normalized(m_headings.first().degrees);
}

double CarTrack::speedAt(double atMs) const {
    if (m_speeds.isEmpty()) {
        return 0.0;
    }
    for (qsizetype i = m_speeds.size() - 1; i > 0; --i) {
        if (m_speeds.at(i).atMs <= atMs) {
            return m_speeds.at(i).speed;
        }
    }
    // Before the first speed heard, that one.
    return m_speeds.first().speed;
}

double CarTrack::roadSince(double atMs) const {
    const double from = atMs - kLagS * 1000.0;
    double road = 0.0;
    for (qsizetype i = 0; i < m_speeds.size(); ++i) {
        const double start = i == 0 ? from : std::max(from, m_speeds.at(i).atMs);
        const double end = i + 1 < m_speeds.size() ? std::min(atMs, m_speeds.at(i + 1).atMs) : atMs;
        if (end > start) {
            road += m_speeds.at(i).speed * (end - start) / 1000.0;
        }
    }
    return road;
}

#include "currentdrive.hh"

#include "../logger.hh"
#include "../protocol.hh"
#include "../serverclient.hh"
#include "../tesla/tesladata.hh"

#include <QDataStream>
#include <QIODevice>
#include <QVariantMap>

namespace {
const Logger logger = Logger::get("trips");

// The Gear value of a parked car (the backend's PARK_STATE); an unknown gear counts as
// parked too, so a car nobody has heard from draws no drive.
const QString kParkGear = QStringLiteral("ShiftStateP");
// A fix closer than this to the path's end adds no point.
constexpr double kMinStepM = 4.0;
// How often an active drive is asked for again, which is also how long its end can go
// unnoticed.
constexpr int kPollMs = 60 * 1000;
// The wait after a gear change before asking: the backend has to have logged it.
constexpr int kGearSettleMs = 3000;
}

CurrentDrive::CurrentDrive(ServerClient *server, TeslaData *tesla, QObject *parent)
    : QObject(parent), m_server(server), m_tesla(tesla) {
    m_poll.setInterval(kPollMs);
    connect(&m_poll, &QTimer::timeout, this, &CurrentDrive::request);
    m_gearSettle.setSingleShot(true);
    m_gearSettle.setInterval(kGearSettleMs);
    connect(&m_gearSettle, &QTimer::timeout, this, &CurrentDrive::request);

    connect(server, &ServerClient::packetReceived, this, &CurrentDrive::onPacket);
    connect(server, &ServerClient::connectedChanged, this, [this]() {
        if (m_server->connected() && m_watched)
            request();
    });
    connect(tesla, &TeslaData::locationChanged, this, &CurrentDrive::onLocation);
    connect(tesla, &TeslaData::gearChanged, this, &CurrentDrive::onGear);
}

void CurrentDrive::retain() {
    setWatched(++m_watchers > 0);
}

void CurrentDrive::release() {
    if (m_watchers == 0) {
        logger.warning(QStringLiteral("release() without a matching retain()"));
        return;
    }
    setWatched(--m_watchers > 0);
}

void CurrentDrive::setWatched(bool watched) {
    if (watched == m_watched)
        return;
    m_watched = watched;
    emit watchedChanged();
    if (m_watched) {
        updateState();
        request();
    } else {
        // Fixes are not followed while nobody looks; the next look asks again and
        // replaces the path, so stopping here leaves nothing to repair.
        m_poll.stop();
        m_gearSettle.stop();
    }
}

void CurrentDrive::request() {
    if (!m_watched || !m_server->connected())
        return;
    m_server->sendPacket(protocol::frame(protocol::TRIP_GET_CURRENT, QByteArray()));
    logger.debug(QStringLiteral("Current drive requested"));
}

bool CurrentDrive::parked() const {
    const QString gear = m_tesla->gear();
    return gear.isEmpty() || gear == kParkGear;
}

QGeoCoordinate CurrentDrive::liveFix() const {
    const QVariantMap location = m_tesla->location();
    const QVariant lat = location.value(QStringLiteral("latitude"));
    const QVariant lon = location.value(QStringLiteral("longitude"));
    if (!lat.isValid() || !lon.isValid())
        return {};
    return QGeoCoordinate(lat.toDouble(), lon.toDouble());
}

void CurrentDrive::addFix(const QGeoCoordinate &fix, qreal speed) {
    if (!fix.isValid())
        return;
    if (m_head.isValid()) {
        const QGeoCoordinate &anchor = m_path.isEmpty() ? m_head : m_path.last();
        if (m_path.isEmpty() || anchor.distanceTo(m_head) >= kMinStepM) {
            m_path.append(m_head);
            m_speeds.append(m_headSpeed);
        }
    }
    m_head = fix;
    m_headSpeed = speed;
}

void CurrentDrive::clear() {
    if (m_path.isEmpty() && !m_head.isValid())
        return;
    m_path.clear();
    m_speeds.clear();
    m_head = QGeoCoordinate();
    ++m_generation;
    emit pathChanged();
}

void CurrentDrive::updateState() {
    const bool live = m_backendLive || !parked();
    // Leaving Park while the last trip is drawn starts the next drive.
    if (live && m_showingLast) {
        m_showingLast = false;
        clear();
    }
    const bool active = live || m_showingLast;
    if (!active)
        clear();
    if (m_watched && live)
        m_poll.start();
    else
        m_poll.stop();
    if (live != m_live) {
        m_live = live;
        emit liveChanged();
    }
    if (active != m_active) {
        m_active = active;
        emit activeChanged();
    }
}

void CurrentDrive::onLocation() {
    if (!m_watched || !m_live)
        return;
    const QGeoCoordinate fix = liveFix();
    if (!fix.isValid() || (m_head.isValid() && m_head.distanceTo(fix) < 0.5))
        return;
    addFix(fix, m_tesla->vehicleSpeed());
    emit pathChanged();
}

void CurrentDrive::onGear() {
    updateState();
    if (m_watched)
        m_gearSettle.start();
}

void CurrentDrive::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::TRIP_CURRENT || !m_watched)
        return;
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    // trip_id(8) + live(1) + status(1) + count(4)
    if (device->bytesAvailable() < 14) {
        logger.warning(QStringLiteral("Current-drive frame too short"));
        return;
    }
    qint64 tripId;
    quint8 live;
    quint8 status;
    quint32 count;
    stream >> tripId >> live >> status >> count;

    m_backendLive = tripId != 0 && live;
    if (tripId == 0 || (!live && !parked())) {
        // No trip in a week: parked, updateState clears the path. Out of Park with the
        // backend's newest trip finished: a drive whose gear it has not logged yet, whose
        // live fixes are all there is.
        if (tripId == 0)
            m_showingLast = false;
        updateState();
        return;
    }

    m_path.clear();
    m_speeds.clear();
    m_head = QGeoCoordinate();
    ++m_generation;
    if (status == 1) {
        for (quint32 i = 0; i < count; ++i) {
            // ts(8) + lat(8) + lon(8) + speed(8) = 32 bytes per point.
            if (device->bytesAvailable() < 32) {
                logger.warning(QStringLiteral("Truncated current-drive points at %1").arg(i));
                break;
            }
            qint64 ts;
            double lat;
            double lon;
            double speed;
            stream >> ts >> lat >> lon >> speed;
            addFix(QGeoCoordinate(lat, lon), speed);
        }
    }
    if (live) {
        // The car may have moved on since the backend read its log.
        const QGeoCoordinate fix = liveFix();
        if (fix.isValid() && (!m_head.isValid() || m_head.distanceTo(fix) >= kMinStepM))
            addFix(fix, m_tesla->vehicleSpeed());
        m_showingLast = false;
    } else {
        // A finished trip: no tail runs on from its last fix, so that fix joins the path.
        if (m_head.isValid()) {
            m_path.append(m_head);
            m_speeds.append(m_headSpeed);
            m_head = QGeoCoordinate();
        }
        m_showingLast = true;
    }
    updateState();
    emit pathChanged();
    logger.debug(QStringLiteral("Current drive | id=%1 live=%2 points=%3")
                     .arg(tripId).arg(live).arg(m_path.size()));
}

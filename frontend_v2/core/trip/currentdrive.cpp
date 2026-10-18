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

void CurrentDrive::setWatched(bool watched) {
    if (watched == m_watched)
        return;
    m_watched = watched;
    emit watchedChanged();
    if (m_watched) {
        updateActive();
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

void CurrentDrive::addFix(const QGeoCoordinate &fix) {
    if (!fix.isValid())
        return;
    if (m_head.isValid()) {
        const QGeoCoordinate &anchor = m_path.isEmpty() ? m_head : m_path.last();
        if (m_path.isEmpty() || anchor.distanceTo(m_head) >= kMinStepM)
            m_path.append(m_head);
    }
    m_head = fix;
}

void CurrentDrive::clear() {
    if (m_path.isEmpty() && !m_head.isValid())
        return;
    m_path.clear();
    m_head = QGeoCoordinate();
    emit pathChanged();
}

void CurrentDrive::updateActive() {
    const bool active = m_backendDrive || !parked();
    if (!active)
        clear();
    if (m_watched && active)
        m_poll.start();
    else
        m_poll.stop();
    if (active != m_active) {
        m_active = active;
        emit activeChanged();
    }
}

void CurrentDrive::onLocation() {
    if (!m_watched || !m_active)
        return;
    const QGeoCoordinate fix = liveFix();
    if (!fix.isValid() || (m_head.isValid() && m_head.distanceTo(fix) < 0.5))
        return;
    addFix(fix);
    emit pathChanged();
}

void CurrentDrive::onGear() {
    updateActive();
    if (m_watched)
        m_gearSettle.start();
}

void CurrentDrive::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::TRIP_CURRENT || !m_watched)
        return;
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    // trip_id(8) + status(1) + count(4)
    if (device->bytesAvailable() < 13) {
        logger.warning(QStringLiteral("Current-drive frame too short"));
        return;
    }
    qint64 tripId;
    quint8 status;
    quint32 count;
    stream >> tripId >> status >> count;

    m_backendDrive = tripId != 0;
    if (!m_backendDrive) {
        // Parked: the drive is over, and updateActive clears it. Out of Park: a drive too
        // short for the backend's minimum distance, whose live fixes are all there is.
        updateActive();
        return;
    }

    m_path.clear();
    m_head = QGeoCoordinate();
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
            addFix(QGeoCoordinate(lat, lon));
        }
    }
    // The car may have moved on since the backend read its log.
    const QGeoCoordinate fix = liveFix();
    if (fix.isValid() && (!m_head.isValid() || m_head.distanceTo(fix) >= kMinStepM))
        addFix(fix);
    updateActive();
    emit pathChanged();
    logger.debug(QStringLiteral("Current drive | id=%1 points=%2").arg(tripId).arg(m_path.size()));
}

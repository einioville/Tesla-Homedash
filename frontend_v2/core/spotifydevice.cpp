#include "spotifydevice.hh"

#include <QJsonDocument>
#include <QJsonValue>
#include <QtEndian>

#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("spotify.device");

// How long a configuredStatus answer stays fresh enough not to re-ask.
constexpr qint64 kStatusThrottleMs = 15000;

// Reads a status(1B) + len(4B) + UTF-8 JSON body, the CONFIG_*/SPOTIFY_*
// shape. Leaves *ok false on any truncation, so a malformed frame is refused
// rather than half-parsed. Deliberately identical to spotifyauth.cpp's reader:
// one parser per wire shape, not two that can drift apart.
QJsonObject readStatusJson(const QByteArray &payload, quint8 *status, bool *ok) {
    *ok = false;
    if (payload.size() < 5) {
        return {};
    }
    *status = static_cast<quint8>(payload.at(0));
    const quint32 length = qFromBigEndian<quint32>(payload.constData() + 1);
    if (static_cast<qint64>(payload.size()) < 5 + static_cast<qint64>(length)) {
        return {};
    }
    QJsonParseError error{};
    const QJsonDocument doc =
        QJsonDocument::fromJson(payload.mid(5, static_cast<int>(length)), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject()) {
        return {};
    }
    *ok = true;
    return doc.object();
}

// Frames a JSON request body as len(4B) + UTF-8, the CONFIG_SET payload shape.
QByteArray jsonRequestBody(const QJsonObject &object) {
    const QByteArray json = QJsonDocument(object).toJson(QJsonDocument::Compact);
    QByteArray body;
    body.resize(4);
    qToBigEndian<quint32>(static_cast<quint32>(json.size()), body.data());
    body.append(json);
    return body;
}
}  // namespace

SpotifyDevice::SpotifyDevice(QObject *parent) : QObject(parent) {}

void SpotifyDevice::attachServer(ServerClient *client) {
    m_server = client;
    connect(client, &ServerClient::packetReceived, this, &SpotifyDevice::onPacket);
    // A scan lives on the backend's side of this socket and dies with the
    // StreamWriter that started it — most easily when the user restarts the
    // backend from this very view's Ylläpito section. Nothing would ever arrive
    // again after that, so without this the dialog would sit on "scanning"
    // forever, with an already-found device still armed for saving.
    connect(client, &ServerClient::connectedChanged, this,
            &SpotifyDevice::onConnectionChanged);
    // Nothing is requested here: the backend scans only while a client asked it
    // to, and the configured-device status costs it a Spotify call, so neither
    // is snapshotted on connect.
}

void SpotifyDevice::onConnectionChanged() {
    if (m_server == nullptr) {
        return;
    }
    if (m_server->connected()) {
        // A restarted backend may have another device configured, and the status
        // on screen describes the old process — re-ask, past the throttle.
        if (m_statusWanted) {
            refreshStatus(true);
        }
        return;
    }
    if (m_statusPending) {
        // Its reply died with the socket; without this the row reads "checking"
        // until the next reconnect.
        m_statusPending = false;
        emit configuredStatusChanged();
    }
    if (!m_flowActive) {
        return;
    }
    logger.warning(QStringLiteral("Connection lost during a Spotify device scan"));
    // The device on screen is arbitrarily old now and cannot be re-confirmed, so
    // it goes with the flow: an honest dead end beats a selectable stale hit.
    setFlowActive(false);
    m_stateError = false;
    clearDevice();
    emit deviceChanged();
    setPhase(QStringLiteral("error"), QStringLiteral("Yhteys palvelimeen katkesi"));
}

void SpotifyDevice::begin() {
    if (m_server == nullptr || !m_server->connected()) {
        setPhase(QStringLiteral("error"), QStringLiteral("Ei yhteyttä palvelimeen"));
        return;
    }
    // A new epoch, so every reply still in flight from the previous scan is
    // identifiable as stale. Incremented before the send, so the value the
    // backend echoes is the one this side is already fencing on.
    ++m_scanId;
    setFlowActive(true);
    m_stateError = false;
    // A hit left over from the previous scan must not be on screen while the new
    // one starts, or the user confirms a device the backend has not re-seen.
    clearDevice();
    emit deviceChanged();
    setPhase(QStringLiteral("scanning"));
    QJsonObject request;
    request.insert(QStringLiteral("scanId"), static_cast<qint64>(m_scanId));
    m_server->sendPacket(
        protocol::frame(protocol::SPOTIFY_DEVICE_SCAN_START, jsonRequestBody(request)));
}

void SpotifyDevice::cancel() {
    // Fences every reply still in flight: a SPOTIFY_DEVICE_STATE arriving after
    // this must not reopen the dialog for a scan nobody is running any more.
    setFlowActive(false);
    m_stateError = false;
    if (m_server != nullptr && m_server->connected()) {
        // Unlike the auth flow there is real work on the other side — a Spotify
        // request per poll tick — so a dialog nobody is looking at gets stopped
        // rather than left to expire.
        m_server->sendPacket(protocol::frame(protocol::SPOTIFY_DEVICE_SCAN_STOP));
    }
    setPhase(QStringLiteral("idle"));
}

void SpotifyDevice::select() {
    if (!m_deviceSelectable || m_deviceId.isEmpty()) {
        // Spotify gives a restricted device no id at all, so there is nothing
        // that could be written to spotifyDeviceId.
        logger.warning(QStringLiteral("Refusing to save an unselectable Spotify device"));
        setPhase(QStringLiteral("error"), QStringLiteral("Tätä laitetta ei voi valita"));
        return;
    }
    if (m_server == nullptr || !m_server->connected()) {
        setPhase(QStringLiteral("error"), QStringLiteral("Ei yhteyttä palvelimeen"));
        return;
    }
    // Re-arms the fence: a save may be retried after a failure, and the retry's
    // own SPOTIFY_DEVICE_RESULT must not be fenced out by the first attempt.
    setFlowActive(true);
    m_stateError = false;
    QJsonObject request;
    request.insert(QStringLiteral("deviceId"), m_deviceId);
    // The backend refuses a selection from an epoch that is no longer the live
    // scan, so a save can never be answered by — or applied to — the wrong scan.
    request.insert(QStringLiteral("scanId"), static_cast<qint64>(m_scanId));
    logger.info(QStringLiteral("Selecting Spotify device %1 (%2)")
                    .arg(m_deviceName, m_deviceId));
    setPhase(QStringLiteral("saving"));
    m_server->sendPacket(
        protocol::frame(protocol::SPOTIFY_DEVICE_SELECT, jsonRequestBody(request)));
}

void SpotifyDevice::refreshStatus(bool force) {
    m_statusWanted = true;
    if (m_server == nullptr || !m_server->connected()) {
        return;
    }
    if (!force && (m_statusPending ||
                   (m_statusAge.isValid() && m_statusAge.elapsed() < kStatusThrottleMs))) {
        return;
    }
    m_statusAge.restart();
    if (!m_statusPending) {
        m_statusPending = true;
        emit configuredStatusChanged();
    }
    m_server->sendPacket(protocol::frame(protocol::SPOTIFY_DEVICE_GET_STATUS));
}

void SpotifyDevice::applyConfiguredStatus(const QByteArray &payload) {
    quint8 status = protocol::SPOTIFY_AUTH_ERROR;
    bool ok = false;
    const QJsonObject body = readStatusJson(payload, &status, &ok);
    if (!ok) {
        logger.warning(QStringLiteral("Malformed Spotify device status packet"));
        return;
    }
    m_configuredStatus = body.toVariantMap();
    m_statusPending = false;
    emit configuredStatusChanged();
}

void SpotifyDevice::setPhase(const QString &phase, const QString &message) {
    if (phase == m_phase && message == m_message) {
        return;
    }
    m_phase = phase;
    m_message = message;
    emit phaseChanged();
}

void SpotifyDevice::setFlowActive(bool active) {
    if (active == m_flowActive) {
        return;
    }
    m_flowActive = active;
    emit flowActiveChanged();
}

void SpotifyDevice::clearDevice() {
    m_hasDevice = false;
    m_deviceId.clear();
    m_deviceName.clear();
    m_deviceType.clear();
    m_deviceVolume = -1;
    m_deviceSelectable = false;
    m_trackPlaying = false;
    m_trackName.clear();
    m_trackArtists.clear();
    m_trackAlbum.clear();
    m_trackImageUrl.clear();
    m_currentDeviceId.clear();
    m_currentDeviceName.clear();
    m_isCurrent = false;
}

void SpotifyDevice::applyState(const QJsonObject &body) {
    // Start from cleared fields and fill in only what this packet carries. That
    // is what makes a device which STOPPED playing disappear from the dialog
    // instead of going stale — a stale hit invites the user to save an id the
    // backend can no longer see.
    clearDevice();

    const QJsonValue deviceValue = body.value(QStringLiteral("device"));
    if (deviceValue.isObject()) {
        const QJsonObject device = deviceValue.toObject();
        m_hasDevice = true;
        m_deviceId = device.value(QStringLiteral("id")).toString();
        m_deviceName = device.value(QStringLiteral("name")).toString();
        m_deviceType = device.value(QStringLiteral("type")).toString();
        // volumePercent is null for a device that reports none; -1 keeps that
        // distinct from a real 0 %.
        const QJsonValue volume = device.value(QStringLiteral("volumePercent"));
        m_deviceVolume = volume.isDouble() ? volume.toInt() : -1;
        // The backend already decides this, but an empty id is unsaveable
        // whatever it says — so the button can never be armed without one.
        m_deviceSelectable =
            device.value(QStringLiteral("selectable")).toBool() && !m_deviceId.isEmpty();
    }

    const QJsonValue trackValue = body.value(QStringLiteral("track"));
    if (trackValue.isObject()) {
        const QJsonObject track = trackValue.toObject();
        m_trackName = track.value(QStringLiteral("name")).toString();
        // Already joined by the backend (and the show name for an episode), so
        // this side never has to know the track/episode shape.
        m_trackArtists = track.value(QStringLiteral("artists")).toString();
        m_trackAlbum = track.value(QStringLiteral("album")).toString();
        m_trackImageUrl = track.value(QStringLiteral("imageUrl")).toString();
        m_trackPlaying = track.value(QStringLiteral("isPlaying")).toBool();
    }

    const QJsonObject current = body.value(QStringLiteral("current")).toObject();
    m_currentDeviceId = current.value(QStringLiteral("id")).toString();
    m_currentDeviceName = current.value(QStringLiteral("name")).toString();
    m_isCurrent = current.value(QStringLiteral("isSame")).toBool();

    emit deviceChanged();
}

void SpotifyDevice::onPacket(quint8 type, const QByteArray &payload) {
    // Before the fence on purpose: the configured device's status belongs to no
    // flow, and the backend broadcasts it after ANY panel's successful select.
    if (type == protocol::SPOTIFY_DEVICE_STATUS) {
        applyConfiguredStatus(payload);
        return;
    }
    if (type != protocol::SPOTIFY_DEVICE_STATE && type != protocol::SPOTIFY_DEVICE_RESULT) {
        return;
    }
    // Both packets belong to a flow this side started, so both are fenced: one
    // arriving after cancel() would reopen the dialog on a dead scan.
    if (!m_flowActive) {
        return;
    }

    quint8 status = protocol::SPOTIFY_AUTH_ERROR;
    bool ok = false;
    const QJsonObject body = readStatusJson(payload, &status, &ok);
    if (!ok) {
        logger.warning(QStringLiteral("Malformed Spotify device packet 0x%1")
                           .arg(type, 2, 16, QLatin1Char('0')));
        return;
    }

    // The second half of the fence, answering the question m_flowActive cannot:
    // not "is a flow running" but "does this packet belong to THIS flow". Cancel
    // a scan and start another straight away and a reply already in flight from
    // the old one passes the re-armed m_flowActive — and would repopulate the
    // dialog with the PREVIOUS device, which the user could then save. A missing
    // or malformed field reads as 0, which never matches a live scan.
    const qint64 scanId = body.value(QStringLiteral("scanId")).toInteger(0);
    if (scanId != static_cast<qint64>(m_scanId)) {
        logger.debug(QStringLiteral("Dropping Spotify device packet 0x%1 from scan %2 "
                                    "(current %3)")
                         .arg(QString::number(type, 16), QString::number(scanId),
                              QString::number(m_scanId)));
        return;
    }

    switch (type) {
    case protocol::SPOTIFY_DEVICE_STATE: {
        applyState(body);
        // The backend does not stop scanning while a save is in flight, so a
        // poll tick lands right on top of it. Its phase must not be written
        // then: a transient scan error would replace "Tallennetaan…", and a
        // recovery would put the phase back to "scanning" and re-arm the save
        // button under the finger of a user whose save has not answered yet.
        // The device fields above are still refreshed — only the phase waits.
        if (m_phase == QStringLiteral("saving")) {
            break;
        }
        const QString message = body.value(QStringLiteral("message")).toString();
        if (status != protocol::SPOTIFY_AUTH_OK || !message.isEmpty()) {
            // Something blocks the scan (no grant, Spotify unreachable). The
            // dialog stays open on the error: the backend keeps polling and may
            // recover on the next tick.
            m_stateError = true;
            setPhase(QStringLiteral("error"),
                     message.isEmpty() ? QStringLiteral("Laitehaku epäonnistui") : message);
            return;
        }
        if (m_stateError) {
            // The blocked scan recovered, so drop the error the scan itself
            // raised. A failed SAVE is never cleared this way — its message has
            // to survive until the user acts on it.
            m_stateError = false;
            setPhase(QStringLiteral("scanning"));
        }
        // A "scanning": false body deliberately does NOT close the dialog. The
        // sibling's "consent" phase waits the same way, and a popup vanishing
        // under the user is worse than a stale one — Peruuta is always there.
        break;
    }
    case protocol::SPOTIFY_DEVICE_RESULT: {
        const bool succeeded = status == protocol::SPOTIFY_AUTH_OK &&
                               body.value(QStringLiteral("ok")).toBool();
        const QString message = body.value(QStringLiteral("message")).toString();
        if (succeeded) {
            // The flow is over: drop the fence so a late state packet cannot
            // knock the success screen back to "scanning".
            setFlowActive(false);
        } else {
            // Keep the fence up — the user may press "Valitse laite" again, and
            // that retry's own result must still be accepted. The scan itself is
            // still running on the backend, and the button is gated on the flow
            // rather than on the phase, so it stays available on this error
            // phase instead of the dialog becoming a dead end.
            m_stateError = false;
        }
        setPhase(succeeded ? QStringLiteral("done") : QStringLiteral("error"), message);
        logger.info(QStringLiteral("Spotify device selection %1")
                        .arg(succeeded ? QStringLiteral("succeeded")
                                       : QStringLiteral("failed: ") + message));
        break;
    }
    default:
        break;
    }
}

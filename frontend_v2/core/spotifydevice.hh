#ifndef FRONTEND_V2_SPOTIFYDEVICE_HH
#define FRONTEND_V2_SPOTIFYDEVICE_HH

#include <QByteArray>
#include <QJsonObject>
#include <QObject>
#include <QString>

class ServerClient;

/**
 * SpotifyDevice — drives the Options view's "Tunnista laite" flow, which writes
 * config.json's spotifyDeviceId from the dashboard.
 *
 * Why it exists: every Spotify transport control is routed to the ONE Connect
 * device that key names, so a wrong id makes play/pause/skip/seek SILENTLY
 * no-op — nothing errors, the buttons simply do nothing and the dashboard looks
 * broken. Until now the id was obtainable only by SSHing into the Pi to run
 * media_service/setup/spotify_setup.py, which is not a repair a fullscreen,
 * keyboard-less panel can offer.
 *
 * The split matches its sibling SpotifyAuth: the BACKEND stops the radio, polls
 * Spotify for whatever is playing on any device, resolves the currently
 * configured id and streams the result here; this side only renders what it is
 * told and posts back the id the user confirmed. No credential is ever seen on
 * this side, and the scan runs only while a client asked for it.
 *
 * `phase` is a plain string state machine so QML can switch on it without any
 * enum registration:
 *   "idle"     nothing in progress
 *   "scanning" the backend is polling; the dialog shows the guide + any hit
 *   "saving"   the chosen id was sent, awaiting SPOTIFY_DEVICE_RESULT
 *   "done"     spotifyDeviceId was written
 *   "error"    see `message`
 *
 * Registered with the QML engine as the singleton `SpotifyDevice` (see main.cpp).
 */
class SpotifyDevice : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString phase READ phase NOTIFY phaseChanged)
    Q_PROPERTY(QString message READ message NOTIFY phaseChanged)
    // Whether a flow is running at all, exposed because the dialog's "Valitse
    // laite" button is gated on the FLOW rather than on the phase: a failed save
    // leaves the phase on "error" while the backend keeps scanning, and a button
    // that disappeared then would never come back.
    Q_PROPERTY(bool flowActive READ flowActive NOTIFY flowActiveChanged)
    // The device the backend currently sees playing, plus what is playing on it —
    // the whole point of the dialog is that the user recognises the device by the
    // track coming out of it, so both halves change together.
    Q_PROPERTY(bool hasDevice READ hasDevice NOTIFY deviceChanged)
    Q_PROPERTY(QString deviceId READ deviceId NOTIFY deviceChanged)
    Q_PROPERTY(QString deviceName READ deviceName NOTIFY deviceChanged)
    Q_PROPERTY(QString deviceType READ deviceType NOTIFY deviceChanged)
    // -1 when the device reports no volume, so "unknown" stays distinct from 0 %.
    Q_PROPERTY(int deviceVolume READ deviceVolume NOTIFY deviceChanged)
    // False for a restricted device: Spotify gives it no id, so there is nothing
    // that could be written to spotifyDeviceId.
    Q_PROPERTY(bool deviceSelectable READ deviceSelectable NOTIFY deviceChanged)
    Q_PROPERTY(bool trackPlaying READ trackPlaying NOTIFY deviceChanged)
    Q_PROPERTY(QString trackName READ trackName NOTIFY deviceChanged)
    Q_PROPERTY(QString trackArtists READ trackArtists NOTIFY deviceChanged)
    Q_PROPERTY(QString trackAlbum READ trackAlbum NOTIFY deviceChanged)
    Q_PROPERTY(QString trackImageUrl READ trackImageUrl NOTIFY deviceChanged)
    // The id already in config.json, resolved to a name by the backend when it
    // can — so the dialog can say "this is already the configured device".
    Q_PROPERTY(QString currentDeviceId READ currentDeviceId NOTIFY deviceChanged)
    Q_PROPERTY(QString currentDeviceName READ currentDeviceName NOTIFY deviceChanged)
    Q_PROPERTY(bool isCurrent READ isCurrent NOTIFY deviceChanged)

public:
    explicit SpotifyDevice(QObject *parent = nullptr);

    QString phase() const { return m_phase; }
    QString message() const { return m_message; }
    bool flowActive() const { return m_flowActive; }
    bool hasDevice() const { return m_hasDevice; }
    QString deviceId() const { return m_deviceId; }
    QString deviceName() const { return m_deviceName; }
    QString deviceType() const { return m_deviceType; }
    int deviceVolume() const { return m_deviceVolume; }
    bool deviceSelectable() const { return m_deviceSelectable; }
    bool trackPlaying() const { return m_trackPlaying; }
    QString trackName() const { return m_trackName; }
    QString trackArtists() const { return m_trackArtists; }
    QString trackAlbum() const { return m_trackAlbum; }
    QString trackImageUrl() const { return m_trackImageUrl; }
    QString currentDeviceId() const { return m_currentDeviceId; }
    QString currentDeviceName() const { return m_currentDeviceName; }
    bool isCurrent() const { return m_isCurrent; }

    void attachServer(ServerClient *client);

    // Starts a scan: asks the backend to stop other playback and begin polling.
    Q_INVOKABLE void begin();
    // Closes the dialog and stops the backend's polling. Unlike the auth flow
    // there IS work running on the other side, so this one really does send.
    Q_INVOKABLE void cancel();
    // Writes the detected device's id to config.json's spotifyDeviceId.
    Q_INVOKABLE void select();

signals:
    void phaseChanged();
    void deviceChanged();
    void flowActiveChanged();

private:
    void onPacket(quint8 type, const QByteArray &payload);
    // The socket dropped (or came back). A scan lives on the backend's side of
    // that socket, so losing it ends the flow — see the .cpp for why silence is
    // the only thing the dialog would otherwise show.
    void onConnectionChanged();
    void setPhase(const QString &phase, const QString &message = QString());
    // Sets m_flowActive and notifies QML only on a real change.
    void setFlowActive(bool active);
    // Replaces every detected-device / track / current field from one
    // SPOTIFY_DEVICE_STATE body and emits deviceChanged once.
    void applyState(const QJsonObject &body);
    // Resets the detected device, its track and the resolved current device.
    // Does NOT emit — the callers emit once they have finished writing.
    void clearDevice();

    ServerClient *m_server = nullptr;
    QString m_phase = QStringLiteral("idle");
    QString m_message;
    QString m_deviceId;
    QString m_deviceName;
    QString m_deviceType;
    QString m_trackName;
    QString m_trackArtists;
    QString m_trackAlbum;
    QString m_trackImageUrl;
    QString m_currentDeviceId;
    QString m_currentDeviceName;
    int m_deviceVolume = -1;
    bool m_hasDevice = false;
    bool m_deviceSelectable = false;
    bool m_trackPlaying = false;
    bool m_isCurrent = false;
    // True only between begin() and the flow ending. Without it a reply that
    // lands after cancel() reopens the dialog on a scan nobody is running any
    // more — and the user would be invited to save a device from it.
    //
    // It is only HALF the fence, and the two halves answer different questions:
    // m_flowActive answers "is a flow running at all", m_scanId answers "does
    // this packet belong to THIS flow". Cancel a scan and immediately start
    // another and a reply from the old one passes the re-armed m_flowActive —
    // only the epoch can tell the two scans apart.
    bool m_flowActive = false;
    // Whether the current "error" phase came from the SCAN (no grant, Spotify
    // unreachable) rather than from a failed save. Only a scan error may be
    // cleared by the next healthy poll; a save failure has to stay on screen
    // until the user acts on it.
    bool m_stateError = false;
    // Monotonic scan epoch, generated on this side because this is the side that
    // knows when a new flow began. Sent in SPOTIFY_DEVICE_SCAN_START and
    // SPOTIFY_DEVICE_SELECT, echoed by the backend in every SPOTIFY_DEVICE_STATE
    // and SPOTIFY_DEVICE_RESULT; a packet carrying any other value belongs to a
    // scan that is over and is dropped. Starts at 0 and is incremented BEFORE the
    // first scan, so 0 — the value a missing or malformed field parses as — can
    // never match a live scan.
    quint32 m_scanId = 0;
};

#endif  // FRONTEND_V2_SPOTIFYDEVICE_HH

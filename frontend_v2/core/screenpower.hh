#ifndef FRONTEND_V2_SCREENPOWER_HH
#define FRONTEND_V2_SCREENPOWER_HH

#include <QByteArray>
#include <QObject>
#include <QTimer>

class ServerClient;

/**
 * ScreenPower — decides WHEN the panel should sleep, and asks the backend to do it.
 *
 * A step BEYOND the screensaver, and deliberately layered on top of it: the
 * screensaver keeps the backlight on to show photos, this cuts it. A typical
 * setup is screensaver at 30 min, display off at 60.
 *
 * The split matters. This process is the only one that sees touch input, so the
 * inactivity countdown belongs here — but the actual switching is a SYSTEM call
 * (wlopm on the Pi's Wayland session) and system calls belong to the backend. So
 * this class owns a timer and sends DISPLAY_SET_POWER; backend/src/display_service
 * owns the process spawn. Nothing here shells out.
 *
 * `off` and `available` are reported BY the backend (DISPLAY_POWER_STATE), never
 * assumed here: a host with no wlopm answers available=false, and the toggle then
 * has nothing to drive. While disconnected no request can be sent, so the panel
 * simply stays as it is.
 *
 * Activity comes from IdleWatcher::activity() rather than a second event filter,
 * so both timeouts share one definition of "the user is here".
 *
 * Registered with the QML engine as the singleton `Display` (see main.cpp).
 * Not named `Screen`: QtQuick already attaches a `Screen` type to every Item.
 */
class ScreenPower : public QObject {
    Q_OBJECT
    // Whether the timeout is armed at all. Bound from Theme in Main.qml, so the
    // Options view toggles it live.
    Q_PROPERTY(bool enabled READ enabled WRITE setEnabled NOTIFY enabledChanged)
    // Inactivity before the panel powers down. Floored at 30 s so a mistyped
    // value cannot make the screen unusable.
    Q_PROPERTY(int timeoutMs READ timeoutMs WRITE setTimeoutMs NOTIFY timeoutMsChanged)
    // Backend-reported: true while the panel is powered down.
    Q_PROPERTY(bool off READ off NOTIFY stateChanged)
    // Backend-reported: false when the host has no wlopm, so the feature is inert
    // however the setting is set.
    Q_PROPERTY(bool available READ available NOTIFY stateChanged)

public:
    explicit ScreenPower(QObject *parent = nullptr);

    bool enabled() const { return m_enabled; }
    int timeoutMs() const { return m_timeoutMs; }
    bool off() const { return m_off; }
    bool available() const { return m_available; }

    void setEnabled(bool enabled);
    void setTimeoutMs(int timeoutMs);

    // Wires the DISPLAY_* traffic once the socket exists. Called from main.cpp
    // after ServerClient is constructed, for the same reason Settings defers its
    // own wiring: this object is built before the socket is.
    void attachServer(ServerClient *client);

public slots:
    // Restarts the countdown, and asks for the panel back if it is asleep.
    // Connected to IdleWatcher::activity() in main.cpp.
    void onActivity();

    // Wakes the panel now, ignoring the countdown (which is restarted either
    // way). Exposed for testing from QML.
    Q_INVOKABLE void wake();

signals:
    void enabledChanged();
    void timeoutMsChanged();
    void stateChanged();

private:
    void onTimeout();
    void request(bool off);
    void onPacket(quint8 type, const QByteArray &payload);

    QTimer m_timer;
    ServerClient *m_server = nullptr;
    int m_timeoutMs = 60 * 60 * 1000;
    bool m_enabled = false;
    bool m_off = false;
    bool m_available = false;
};

#endif  // FRONTEND_V2_SCREENPOWER_HH

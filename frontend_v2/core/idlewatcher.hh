#ifndef FRONTEND_V2_IDLEWATCHER_HH
#define FRONTEND_V2_IDLEWATCHER_HH

#include <QObject>
#include <QTimer>

class QEvent;

/**
 * IdleWatcher — application-wide inactivity detector for the screensaver.
 *
 * There is no global "user activity" signal in the app (input is handled
 * per-item and taps deliberately fall through to the cards), so this installs
 * itself as an event filter on the QGuiApplication: it sees EVERY input event
 * (mouse / touch / key / wheel / tablet) before delivery, resets a single-shot
 * countdown, and NEVER consumes the event — the UI is completely unaffected.
 *
 * When the countdown elapses with no input, `idle` flips true; the next input
 * event (or an explicit poke()) flips it back to false. The screensaver overlay
 * binds its visibility to `idle`.
 *
 * Registered with the QML engine as the singleton `Idle` (see main.cpp),
 * constructed after the QGuiApplication (so qApp exists) and after AppConfig
 * (which supplies the timeout).
 */
class IdleWatcher : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool idle READ idle NOTIFY idleChanged)
    Q_PROPERTY(int timeoutMs READ timeoutMs WRITE setTimeoutMs NOTIFY timeoutMsChanged)

public:
    explicit IdleWatcher(int timeoutMs = 30 * 60 * 1000, QObject *parent = nullptr);

    bool idle() const { return m_idle; }
    int timeoutMs() const { return m_timeoutMs; }
    void setTimeoutMs(int timeoutMs);

    // Explicitly register activity (e.g. the screensaver's dismiss tap): same
    // effect as a real input event — clears idle and restarts the countdown.
    Q_INVOKABLE void poke();

signals:
    void idleChanged();
    void timeoutMsChanged();
    // Every input event, not just the idle→active edge. ScreenPower hangs its own
    // (longer) countdown off this so both timeouts share one definition of
    // activity instead of installing a second event filter.
    void activity();

protected:
    bool eventFilter(QObject *watched, QEvent *event) override;

private:
    void registerActivity();
    void onTimeout();

    QTimer m_timer;
    int m_timeoutMs;
    bool m_idle = false;
};

#endif  // FRONTEND_V2_IDLEWATCHER_HH

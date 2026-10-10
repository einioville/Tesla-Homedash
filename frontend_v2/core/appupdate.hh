#ifndef FRONTEND_V2_APPUPDATE_HH
#define FRONTEND_V2_APPUPDATE_HH

#include <QByteArray>
#include <QObject>
#include <QtTypes>
#include <QString>
#include <QVariantMap>

class ServerClient;

/**
 * AppUpdate — the Options view's "Päivitys" card, this side of it.
 *
 * The BACKEND owns every part of an update that touches the system: fetching,
 * moving the working tree onto a target commit, re-syncing dependencies,
 * rebuilding this very binary and restarting itself. Nothing here runs a
 * process. This class picks a channel, asks, shows what comes back, and — when
 * the backend says the new binary is on disk — restarts the app so it is the one
 * running. The same split display_service and ScreenPower make.
 *
 * Two channels, both resolved by the backend to a COMMIT:
 *   "development"  the tip of origin/main
 *   "releases"     the newest v* tag
 * The verdict is a commit comparison, so moving BACK (releases is usually older
 * than main) is an ordinary outcome, not an error — which is what makes
 * switching channels work in both directions.
 *
 * The whole state arrives as one opaque document, deliberately, for the same
 * reason SystemStatus does: it is a report, and a field added on the backend
 * should not need a C++ change to reach the screen. A run in progress is the
 * document's "job" object, so progress needs no second packet type and a
 * dashboard that connects mid-update sees it from its on-connect snapshot.
 *
 * Registered with the QML engine as the singleton `Updater` (see main.cpp).
 */
class AppUpdate : public QObject {
    Q_OBJECT
    // The whole UPDATE_STATE document. Empty until the first one arrives.
    Q_PROPERTY(QVariantMap state READ state NOTIFY stateChanged)
    // True once any state has been received, so the card can tell "asking" from
    // "the backend answered and there is nothing to report".
    Q_PROPERTY(bool loaded READ loaded NOTIFY stateChanged)
    // Whether this deployment can update itself at all (git present, and the
    // source really is a working tree). `reason` says why not.
    Q_PROPERTY(bool available READ available NOTIFY stateChanged)
    Q_PROPERTY(QString reason READ reason NOTIFY stateChanged)
    // A run is in flight. Every control that could start a second one is gated
    // on this, and so is the card's progress block.
    Q_PROPERTY(bool busy READ busy NOTIFY stateChanged)
    // Set by the card while it is on screen. Asks for a fresh state on the way
    // in — including a network fetch, which the backend throttles — so opening
    // the card is the check rather than a button the user has to know to press.
    Q_PROPERTY(bool active READ active WRITE setActive NOTIFY activeChanged)
    // True between asking for a state and the reply landing, so the check button
    // can show that something is happening on a slow link.
    Q_PROPERTY(bool checking READ checking NOTIFY checkingChanged)
    // The commit THIS BINARY was built from, stamped in at configure time. Not
    // the same question as the repository's HEAD, and the difference is the
    // point: between an update's checkout and the app restarting, the repo has
    // moved and this process has not. Empty when the build had no git.
    Q_PROPERTY(QString buildCommit READ buildCommit CONSTANT)
    // The running binary is older than the checkout it was built from — an
    // update landed and this process has not been restarted onto it.
    Q_PROPERTY(bool restartPending READ restartPending NOTIFY stateChanged)

public:
    explicit AppUpdate(QObject *parent = nullptr);

    QVariantMap state() const { return m_state; }
    bool loaded() const { return m_loaded; }
    bool available() const;
    QString reason() const;
    bool busy() const;
    bool active() const { return m_active; }
    void setActive(bool active);
    bool checking() const { return m_checking; }
    QString buildCommit() const;
    bool restartPending() const;

    void attachServer(ServerClient *client);

    // Asks the backend for a fresh state. `fetch` also contacts the remote,
    // which the backend rate-limits, so calling it on every card open is safe.
    Q_INVOKABLE void check(bool fetch);

    // Starts a run. `commit` is the full sha the card was showing: the backend
    // refuses the run if the channel no longer resolves to it, so a target that
    // moved between looking and tapping cannot be applied by accident.
    Q_INVOKABLE void apply(const QString &channel, const QString &commit);

    // Stops a run at the end of the current step.
    Q_INVOKABLE void cancel();

    // NOTE: there is deliberately no channelInfo() invokable. A Q_INVOKABLE
    // registers no property dependency, so a QML binding built on one never
    // re-evaluates — the card must index `state.channels` directly.

signals:
    void stateChanged();
    void activeChanged();
    void checkingChanged();
    // The backend has finished writing a new binary and wants this process
    // restarted so it runs it. Routed in Main.qml to Settings::restartApp() —
    // the same indirection Settings::actionRequested uses, and for the same
    // reason: the singleton should not need to know about the other one.
    void restartRequested();

private:
    void onPacket(quint8 type, const QByteArray &payload);
    void applyDocument(const QVariantMap &document);
    void setChecking(bool checking);

    ServerClient *m_server = nullptr;
    QVariantMap m_state;
    bool m_loaded = false;
    bool m_active = false;
    bool m_checking = false;
    // Start time of the job whose restart request has already been acted on. A
    // job is broadcast repeatedly while it runs, so without this the restart
    // would be re-emitted on every progress packet that follows it. Fenced on
    // startedMs rather than the job id: the id is a per-process counter that
    // restarts at 1 with the backend, so an id could repeat and a later job's
    // restart would be silently swallowed.
    qint64 m_restartedForJobStart = 0;
};

#endif  // FRONTEND_V2_APPUPDATE_HH

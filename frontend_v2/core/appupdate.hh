#ifndef FRONTEND_V2_APPUPDATE_HH
#define FRONTEND_V2_APPUPDATE_HH

#include <QByteArray>
#include <QObject>
#include <QString>
#include <QVariantMap>

class ServerClient;

/**
 * AppUpdate — this side of the Options view's "Päivitys" card (#56).
 *
 * The backend installs releases from GitHub on its own device: it lists them,
 * verifies them, unpacks one beside the running release and switches both units
 * to it (backend/src/update_service/CLAUDE.md). Nothing here runs a process or
 * restarts anything: this asks for the list, starts an install by tag, cancels,
 * and shows what comes back.
 *
 * The whole state arrives as one opaque document, as SystemStatus's does: it is a
 * report, and a field added on the backend should not need a C++ change to reach
 * the screen. A run in progress is the document's "job" object, so a display that
 * connects mid-install sees it from its on-connect snapshot.
 *
 * Registered with the QML engine as the singleton `Updater` (see main.cpp).
 */
class AppUpdate : public QObject {
    Q_OBJECT
    // The whole UPDATE_STATE document. Empty until the first one arrives.
    Q_PROPERTY(QVariantMap state READ state NOTIFY stateChanged)
    Q_PROPERTY(bool loaded READ loaded NOTIFY stateChanged)
    // The backend's device runs an installed release and can install another;
    // false on a development checkout, which `reason` says.
    Q_PROPERTY(bool available READ available NOTIFY stateChanged)
    Q_PROPERTY(QString reason READ reason NOTIFY stateChanged)
    // An install is in flight. The restart buttons, the screensaver and the panel
    // blackout wait on this, and the banner shows.
    Q_PROPERTY(bool busy READ busy NOTIFY stateChanged)
    // Set by the card while it is on screen; turning it on lists the releases
    // again, so opening the card is the check.
    Q_PROPERTY(bool active READ active WRITE setActive NOTIFY activeChanged)
    Q_PROPERTY(bool checking READ checking NOTIFY checkingChanged)
    // What this display is: its release, else its short commit (core/appversion).
    Q_PROPERTY(QString appVersion READ appVersion CONSTANT)
    // Whether pre-releases count: the display's own choice (updateShowPrereleases,
    // bound in Main.qml), which newRelease follows.
    Q_PROPERTY(bool showPrereleases READ showPrereleases WRITE setShowPrereleases
                   NOTIFY showPrereleasesChanged)
    // The newest installable release newer than the backend's, among those shown;
    // empty when there is none. The card's mark, and the notice Main.qml posts
    // each time it changes to a release.
    Q_PROPERTY(QString newRelease READ newRelease NOTIFY newReleaseChanged)

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
    bool showPrereleases() const { return m_showPrereleases; }
    void setShowPrereleases(bool show);
    QString newRelease() const { return m_newRelease; }
    QString appVersion() const;

    void attachServer(ServerClient *client);

    // Asks for the state; `fetch` lists the releases again (the backend throttles it).
    Q_INVOKABLE void check(bool fetch);
    // Installs a release the backend listed as installable; it refuses anything else.
    Q_INVOKABLE void apply(const QString &tag);
    // Stops an install before its switch (job.cancellable).
    Q_INVOKABLE void cancel();

    // NOTE: no per-release invokable. A Q_INVOKABLE registers no property
    // dependency, so a binding built on one never re-evaluates — the card indexes
    // `state.releases` directly.

signals:
    void stateChanged();
    void activeChanged();
    void checkingChanged();
    void showPrereleasesChanged();
    void newReleaseChanged();

private:
    void onPacket(quint8 type, const QByteArray &payload);
    void setChecking(bool checking);
    void updateNewRelease();

    ServerClient *m_server = nullptr;
    QVariantMap m_state;
    bool m_loaded = false;
    bool m_active = false;
    bool m_checking = false;
    bool m_showPrereleases = false;
    QString m_newRelease;
};

#endif  // FRONTEND_V2_APPUPDATE_HH

#ifndef FRONTEND_V2_SETTINGS_HH
#define FRONTEND_V2_SETTINGS_HH

#include <QByteArray>
#include <QHash>
#include <QJsonObject>
#include <QObject>
#include <QQmlPropertyMap>
#include <QSet>
#include <QString>
#include <QVariant>
#include <QVariantList>

class ServerClient;

/**
 * Settings — the single facade the Options view talks to, covering BOTH the
 * frontend's own preferences and the backend's editable config.json tunables.
 *
 * Two halves behind one interface:
 *
 *  - LOCAL settings. Declared in the bundled `:/config/settings.json` schema
 *    (defaults + type + bounds + Finnish label) and persisted as user overrides
 *    to a writable settings.json under QStandardPaths::AppConfigLocation. They
 *    are exposed to QML through `values`, a QQmlPropertyMap, so app/Theme.qml can
 *    bind a token straight to one — `property bool lunaEnabled: Settings.values.lunaEnabled`
 *    — and every existing `Theme.x` call site keeps working unchanged while
 *    gaining live updates. A QQmlPropertyMap (rather than a plain getter) is what
 *    makes those bindings re-evaluate: it emits per-key change notification.
 *
 *  - BACKEND settings. Received as a schema over CONFIG_SCHEMA (0x91) and written
 *    with CONFIG_SET (0x92). The backend owns that schema, so a tunable added
 *    there needs no change here at all. Values are never edited optimistically:
 *    the backend re-broadcasts the authoritative schema after every accepted
 *    write, which is what updates the view.
 *
 * `groups` concatenates both into one UI description, each entry tagged with an
 * `origin` of "local" or "backend", so SettingsView renders them with a single
 * delegate family.
 *
 * Construction order matters (see main.cpp): Settings is built FIRST, before
 * AppConfig, because AppConfig consults it for backendHost / backendPort — a user
 * override has to beat the environment. The socket does not exist yet at that
 * point, so the CONFIG_* wiring is deferred to attachServer().
 *
 * Registered with the QML engine as the singleton `Settings`.
 */
class Settings : public QObject {
    Q_OBJECT
    // Local settings only, keyed by setting key. Bound to from app/Theme.qml.
    Q_PROPERTY(QQmlPropertyMap *values READ values CONSTANT)
    // Unified UI description: local groups followed by the backend's, each
    // setting carrying its current value, bounds, label and origin.
    Q_PROPERTY(QVariantList groups READ groups NOTIFY groupsChanged)
    // True once a backend schema has arrived; the view hides the remote sections
    // (rather than showing empty ones) until then.
    Q_PROPERTY(bool backendAvailable READ backendAvailable NOTIFY groupsChanged)
    // True when a write landed on a restart-tier backend setting since the last
    // restart request — drives the "restart required" banner.
    Q_PROPERTY(bool restartPending READ restartPending NOTIFY restartPendingChanged)
    // The same, for restart-tier LOCAL settings (backendHost / backendPort are
    // consumed once by AppConfig at startup). Separate from restartPending
    // because the two are fixed by restarting different processes.
    Q_PROPERTY(bool appRestartPending READ appRestartPending NOTIFY appRestartPendingChanged)
    // Absolute path of the writable settings file, shown in the view's footer so
    // the file is findable on the device.
    Q_PROPERTY(QString storagePath READ storagePath CONSTANT)

public:
    explicit Settings(QObject *parent = nullptr);

    QQmlPropertyMap *values() { return &m_values; }
    QVariantList groups() const { return m_groups; }
    bool backendAvailable() const { return !m_backendGroups.isEmpty(); }
    bool restartPending() const { return m_restartPending; }
    bool appRestartPending() const { return m_appRestartPending; }
    QString storagePath() const { return m_storagePath; }

    // Wires the CONFIG_* traffic once the socket exists. Called from main.cpp
    // after ServerClient is constructed; requests the schema on every (re)connect.
    void attachServer(ServerClient *client);

    // Startup readers used by AppConfig before the QML engine exists. Returns the
    // user's override if one was saved, otherwise an invalid QVariant so the
    // caller falls through to the environment and then its own default.
    QVariant savedValue(const QString &key) const;

    // Writes one setting. Routes by origin: a local key updates `values`, saves
    // the file and notifies immediately; a backend key is sent as CONFIG_SET and
    // takes effect when the backend's reply + re-broadcast arrive.
    Q_INVOKABLE void setValue(const QString &key, const QVariant &value);

    // Restores one setting to its schema default (local keys only — the backend's
    // defaults live in its own config and are not part of the wire schema).
    Q_INVOKABLE void resetToDefault(const QString &key);

    // Asks the backend to exit so its service manager restarts it, applying every
    // restart-tier setting written since. No-op while disconnected.
    Q_INVOKABLE void requestBackendRestart();

    // Quits this app with a non-zero code so the service manager restarts it,
    // applying restart-tier local settings. On the embedded target the dashboard
    // runs fullscreen with no keyboard, so this is the ONLY way to restart it.
    Q_INVOKABLE void restartApp();

    // Runs the named action from an `action`-typed schema entry. Actions are not
    // values — they are not stored, persisted or sent as CONFIG_SET; keeping them
    // in the schema is just what lets the same sidebar/pane render them.
    Q_INVOKABLE void invokeAction(const QString &key);

signals:
    void groupsChanged();
    void restartPendingChanged();
    void appRestartPendingChanged();
    // Emitted for every completed write so the view can show a transient result.
    // `applied` is "live"/"restart" for local keys and "hook"/"restart"/"unchanged"
    // for backend keys.
    void writeSucceeded(const QString &key, const QString &applied);
    void writeFailed(const QString &key, const QString &message);

private:
    void loadLocalSchema();
    void loadSavedValues();
    void saveLocalValues();
    void rebuildGroups();
    void onPacket(quint8 type, const QByteArray &payload);
    void parseBackendSchema(const QByteArray &payload);
    void parseSetResult(const QByteArray &payload);
    void setLocal(const QString &key, const QVariant &value);
    QVariant coerceLocal(const QJsonObject &setting, const QVariant &value, QString *error) const;

    QQmlPropertyMap m_values;
    // Local schema groups, straight from the bundled JSON (defaults included).
    QVariantList m_localGroups;
    // Backend schema groups from the most recent CONFIG_SCHEMA.
    QVariantList m_backendGroups;
    // m_localGroups + m_backendGroups with live values folded in.
    QVariantList m_groups;
    // key -> the schema entry, for validation and default lookup on write.
    QHash<QString, QJsonObject> m_localSchema;
    // Keys the user has explicitly overridden; only these are written to disk, so
    // a default that changes in a later release still reaches existing installs.
    QSet<QString> m_overridden;

    ServerClient *m_server = nullptr;
    QString m_storagePath;
    bool m_restartPending = false;
    bool m_appRestartPending = false;
};

#endif  // FRONTEND_V2_SETTINGS_HH

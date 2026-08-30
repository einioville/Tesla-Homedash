#ifndef FRONTEND_V2_APPCONFIG_HH
#define FRONTEND_V2_APPCONFIG_HH

#include <QObject>
#include <QString>
#include <QtGlobal>

#include "logger.hh"

class Settings;

/**
 * AppConfig — minimal runtime configuration read at construction from the
 * environment, falling back to the repo-root .env (the same file the backend
 * uses; located by walking up from the working/executable directory). Real
 * environment variables take precedence over .env. The env-var names mirror the
 * production frontend so existing deployments carry over. Also the single place
 * that reads frontend configuration.
 *
 *   TESLA_HOMEDASH_BACKEND_HOST  (string)  default "127.0.0.1"
 *   TESLA_HOMEDASH_BACKEND_PORT  (uint16)  default 6969
 *                                Both are also Options-view settings: a value the
 *                                user saved there WINS over the environment (see
 *                                the Settings ctor arg), because an explicit
 *                                on-device change must not be silently ignored.
 *   TESLA_HOMEDASH_LOG_LEVEL     (string)  default "info"
 *                                (debug|info|warning|error|critical)
 *   TESLA_HOMEDASH_MAP_API_KEY   (string)  optional — a National Land Survey of
 *                                Finland (Maanmittauslaitos) open-data api-key.
 *                                When set, the map uses MML's 0.5 m orthophoto;
 *                                otherwise it falls back to the keyless EOX
 *                                Sentinel-2 basemap. Kept in the environment so
 *                                the key never lives in the committed QML.
 *   TESLA_HOMEDASH_SCREENSAVER_DIR         (string)  optional — a folder of photos
 *                                the screensaver cycles through. NOT read here: it
 *                                is the default for the Options-view setting of the
 *                                same meaning, which owns the value and can change
 *                                it live. Empty (unset) → nothing to show, and the
 *                                screensaver stays off.
 *   TESLA_HOMEDASH_SCREENSAVER_TIMEOUT_MIN (int)     minutes of inactivity before
 *                                the screensaver appears (default 30). Read by
 *                                main() and pushed to the IdleWatcher. Also an
 *                                Options-view setting, which takes precedence.
 *
 * Registered with the QML engine as the singleton `App` (see main.cpp), which
 * is how items/tesla/TeslaMap.qml reads mapTilesUrl / mapAttribution.
 */
class AppConfig : public QObject {
    Q_OBJECT
    // The basemap tile URL + on-screen attribution for the Map's custom tile
    // host. Both are decided once at construction (CONSTANT — no NOTIFY needed).
    Q_PROPERTY(QString mapTilesUrl READ mapTilesUrl CONSTANT)
    Q_PROPERTY(QString mapAttribution READ mapAttribution CONSTANT)

public:
    // `settings` is optional but normally supplied: main.cpp constructs Settings
    // FIRST so a user override of the backend host/port/screensaver timeout beats
    // the environment. Passing nullptr falls back to env/.env only.
    explicit AppConfig(const Settings* settings = nullptr, QObject* parent = nullptr);

    // Startup config — read by main() before the QML engine exists.
    const QString& backendHost() const { return m_backendHost; }
    quint16 backendPort() const { return m_backendPort; }
    Logger::Level logLevel() const { return m_logLevel; }
    int screensaverTimeoutMs() const { return m_screensaverTimeoutMs; }

    // Exposed to QML via the Q_PROPERTYs above.
    const QString& mapTilesUrl() const { return m_mapTilesUrl; }
    const QString& mapAttribution() const { return m_mapAttribution; }

private:
    QString m_backendHost;
    quint16 m_backendPort = 6969;
    Logger::Level m_logLevel = Logger::Level::Info;
    QString m_mapTilesUrl;
    QString m_mapAttribution;
    int m_screensaverTimeoutMs = 30 * 60 * 1000;
};

#endif  // FRONTEND_V2_APPCONFIG_HH

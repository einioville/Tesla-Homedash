#ifndef FRONTEND_V2_APPCONFIG_HH
#define FRONTEND_V2_APPCONFIG_HH

#include <QObject>
#include <QString>
#include <QtGlobal>

#include "logger.hh"

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
 *   TESLA_HOMEDASH_LOG_LEVEL     (string)  default "info"
 *                                (debug|info|warning|error|critical)
 *   TESLA_HOMEDASH_MAP_API_KEY   (string)  optional — a National Land Survey of
 *                                Finland (Maanmittauslaitos) open-data api-key.
 *                                When set, the map uses MML's 0.5 m orthophoto;
 *                                otherwise it falls back to the keyless EOX
 *                                Sentinel-2 basemap. Kept in the environment so
 *                                the key never lives in the committed QML.
 *   TESLA_HOMEDASH_SCREENSAVER_DIR         (string)  optional — a folder of photos
 *                                the screensaver cycles through. Exposed to QML as
 *                                a file:// URL; empty (unset) → the screensaver has
 *                                nothing to show and stays off.
 *   TESLA_HOMEDASH_SCREENSAVER_TIMEOUT_MIN (int)     minutes of inactivity before
 *                                the screensaver appears (default 30). Read by
 *                                main() and pushed to the IdleWatcher.
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
    // Screensaver photo folder as a file:// URL (empty when unset). Decided once
    // at construction. Consumed by items/util/ScreenSaver.qml's FolderListModel.
    Q_PROPERTY(QString screensaverDir READ screensaverDir CONSTANT)

public:
    explicit AppConfig(QObject* parent = nullptr);

    // Startup config — read by main() before the QML engine exists.
    const QString& backendHost() const { return m_backendHost; }
    quint16 backendPort() const { return m_backendPort; }
    Logger::Level logLevel() const { return m_logLevel; }
    int screensaverTimeoutMs() const { return m_screensaverTimeoutMs; }

    // Exposed to QML via the Q_PROPERTYs above.
    const QString& mapTilesUrl() const { return m_mapTilesUrl; }
    const QString& mapAttribution() const { return m_mapAttribution; }
    const QString& screensaverDir() const { return m_screensaverDir; }

private:
    QString m_backendHost;
    quint16 m_backendPort = 6969;
    Logger::Level m_logLevel = Logger::Level::Info;
    QString m_mapTilesUrl;
    QString m_mapAttribution;
    QString m_screensaverDir;
    int m_screensaverTimeoutMs = 30 * 60 * 1000;
};

#endif  // FRONTEND_V2_APPCONFIG_HH

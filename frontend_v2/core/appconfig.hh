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
 * uses; located by dotenv). Real environment variables take precedence over
 * .env.
 *
 *   TESLA_HOMEDASH_BACKEND_HOST  (string)  default "127.0.0.1"
 *   TESLA_HOMEDASH_BACKEND_PORT  (uint16)  default 6969
 *                                Both are also Options-view settings: a value the
 *                                user saved there WINS over the environment (see
 *                                the Settings ctor arg), because an explicit
 *                                on-device change must not be silently ignored.
 *   TESLA_HOMEDASH_LOG_LEVEL     (string)  default "info"
 *                                (debug|info|warning|error|critical)
 *   TESLA_HOMEDASH_MAP_API_KEY   (string)  a National Land Survey of Finland
 *                                (Maanmittauslaitos) open-data api-key. With it the
 *                                map uses MML's 0.5 m orthophoto within Finland;
 *                                without it, the keyless EOX Sentinel-2 basemap
 *                                everywhere (and a startup warning). A deployment
 *                                secret: the environment or .env only, never the
 *                                committed QML or the Options view.
 *   TESLA_HOMEDASH_GPU_CANVAS    (bool)    default on. 0 keeps Qt's default OpenGL
 *                                context (gpuCanvas false).
 *   TESLA_HOMEDASH_SCREENSAVER_TIMEOUT_MIN (int)     minutes of inactivity before
 *                                the screensaver appears (default 30). main()
 *                                seeds the IdleWatcher with it. Also an
 *                                Options-view setting, which takes precedence.
 *
 * Registered with the QML engine as the singleton `App` (see main.cpp), which
 * is how items/tesla/BasemapPlugin.qml reads mapTilesUrl / mapAttribution /
 * mapTileCacheDir.
 */
class AppConfig : public QObject {
    Q_OBJECT
    // MML's tile URL (with its key) + attribution for the maps' custom tile host
    // (items/tesla/BasemapPlugin.qml), decided once at construction; both empty
    // without a key, when the maps show EOX's imagery only.
    Q_PROPERTY(QString mapTilesUrl READ mapTilesUrl CONSTANT)
    Q_PROPERTY(QString mapAttribution READ mapAttribution CONSTANT)
    // The folder every map caches its tiles in (BasemapPlugin's cache directory), which the
    // Options view's *Tyhjennä karttavälimuisti* deletes (Settings::clearMapCache).
    Q_PROPERTY(QString mapTileCacheDir READ mapTileCacheDir CONSTANT)
    // Whether Canvas2D (Qt Canvas Painter) can draw: it has shaders only for OpenGL 3+,
    // OpenGL ES 3+ and the other graphics APIs, and Qt asks OpenGL for 2.0 by default,
    // which Mesa answers with 2.1 — on the dev box and as the Pi's desktop GL — and on
    // which a Canvas2D crashes the app. So the constructor makes the default surface
    // format one the driver gives at 3+ (desktop 3.3 core, else ES 3.0, the Pi's), before
    // any window exists, and says whether it could. No item draws with Canvas2D at
    // present, so nothing reads it (#83).
    Q_PROPERTY(bool gpuCanvas READ gpuCanvas CONSTANT)

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
    static QString mapTileCacheDir();
    bool gpuCanvas() const { return m_gpuCanvas; }

private:
    QString m_backendHost;
    quint16 m_backendPort = 6969;
    Logger::Level m_logLevel = Logger::Level::Info;
    QString m_mapTilesUrl;
    QString m_mapAttribution;
    int m_screensaverTimeoutMs = 30 * 60 * 1000;
    bool m_gpuCanvas = false;
};

#endif  // FRONTEND_V2_APPCONFIG_HH

#include "appconfig.hh"

#include <QOffscreenSurface>
#include <QOpenGLContext>
#include <QQuickWindow>
#include <QStandardPaths>
#include <QStringList>
#include <QSurfaceFormat>
#include <QVariant>
#include <QtGlobal>

#include "dotenv.hh"
#include "settings.hh"

namespace {
const Logger logger = Logger::get("app");

// The basemap's keyed tile provider; the keyless one, EOX, is the provider file
// config/map-providers/satellite. The OSM plugin substitutes %x/%y/%z positionally
// anywhere in the URL (Qt 6.7+), so a z/y/x provider is driven by ordering the
// tokens %z/%y/%x; the literal %x also suppresses the plugin's default
// "%z/%x/%y.png" postfix. Tiles must be EPSG:3857 Web Mercator. Consumed by
// items/tesla/BasemapPlugin.qml via the App singleton.

// MML (National Land Survey of Finland) open orthophoto — 0.5 m aerial of
// Finland, CC BY 4.0. Needs a free api-key (the %1). Web-Mercator variant so it
// aligns with the EPSG:3857 map.
const QString kMmlTilesUrlTemplate = QStringLiteral(
    "https://avoin-karttakuva.maanmittauslaitos.fi/avoin/wmts/1.0.0/ortokuva/"
    "default/WGS84_Pseudo-Mercator/%z/%y/%x.jpg?api-key=%1");
const QString kMmlAttribution = QStringLiteral("© Maanmittauslaitos");

// Makes the default surface format an OpenGL 3+ / OpenGL ES 3+ one the driver gives, for
// Canvas2D (AppConfig::gpuCanvas), and says whether that worked. A candidate counts only once
// a context made with it is current on a surface: one that merely exists proves nothing.
bool requestGpuCanvasFormat() {
    const QSGRendererInterface::GraphicsApi api = QQuickWindow::graphicsApi();
    if (api == QSGRendererInterface::Software) {
        return false;
    }
    if (api != QSGRendererInterface::OpenGL) {
        return true;  // Direct3D, Vulkan, Metal: Canvas Painter has shaders for all of them.
    }
    QSurfaceFormat core = QSurfaceFormat::defaultFormat();
    core.setVersion(3, 3);
    core.setProfile(QSurfaceFormat::CoreProfile);
    QSurfaceFormat es = QSurfaceFormat::defaultFormat();
    es.setRenderableType(QSurfaceFormat::OpenGLES);
    es.setVersion(3, 0);
    for (const QSurfaceFormat& candidate : {core, es}) {
        QOpenGLContext context;
        context.setFormat(candidate);
        if (!context.create() || context.format().majorVersion() < 3) {
            continue;
        }
        QOffscreenSurface surface;
        surface.setFormat(context.format());
        surface.create();
        if (!context.makeCurrent(&surface)) {
            continue;
        }
        context.doneCurrent();
        QSurfaceFormat::setDefaultFormat(candidate);
        logger.info(QStringLiteral("OpenGL: %1 %2.%3 context for Canvas2D")
                        .arg(context.isOpenGLES() ? QStringLiteral("ES") : QStringLiteral("core"))
                        .arg(context.format().majorVersion())
                        .arg(context.format().minorVersion()));
        return true;
    }
    logger.warning(QStringLiteral("OpenGL: no 3.0+ context; the Trips route is drawn on the CPU"));
    return false;
}

}  // namespace

AppConfig::AppConfig(const Settings* settings, QObject* parent) : QObject(parent) {
    const QString dotEnvPath = dotenv::sourcePath();
    if (!dotEnvPath.isEmpty()) {
        logger.info(QStringLiteral("Loaded .env from %1").arg(dotEnvPath));
    }

    // Precedence for the three values the Options view can also set:
    //   built-in default  <  environment / .env  <  saved user setting
    // The user's explicit on-device change has to win, or the Options view would
    // appear to do nothing on a deployment that sets these in .env.
    const auto saved = [settings](const char* key) -> QVariant {
        return settings != nullptr ? settings->savedValue(QLatin1String(key)) : QVariant();
    };

    const QVariant savedHost = saved("backendHost");
    m_backendHost = savedHost.isValid()
                        ? savedHost.toString()
                        : dotenv::valueOr("TESLA_HOMEDASH_BACKEND_HOST",
                                          QStringLiteral("127.0.0.1"));

    bool ok = false;
    const QVariant savedPort = saved("backendPort");
    const int port = savedPort.isValid()
                         ? savedPort.toInt(&ok)
                         : dotenv::valueOr("TESLA_HOMEDASH_BACKEND_PORT", QString()).toInt(&ok);
    m_backendPort = (ok && port >= 1 && port <= 65535) ? static_cast<quint16>(port) : 6969;

    // Log level: parse, defaulting to INFO. An explicit-but-invalid value falls
    // back to INFO with a warning (which lands because main() has already
    // installed the logger at INFO before constructing AppConfig).
    const QString rawLevel = dotenv::valueOr("TESLA_HOMEDASH_LOG_LEVEL", QString());
    m_logLevel = Logger::parseLevel(rawLevel, Logger::Level::Info);
    static const QStringList kValidLevels = {
        QStringLiteral("debug"), QStringLiteral("info"), QStringLiteral("warning"),
        QStringLiteral("error"), QStringLiteral("critical")};
    if (!rawLevel.isEmpty() && !kValidLevels.contains(rawLevel.trimmed().toLower())) {
        logger.warning(QStringLiteral("Unknown TESLA_HOMEDASH_LOG_LEVEL '%1'; using info").arg(rawLevel));
    }

    // Map basemap: MML's 0.5 m orthophoto, keyed by TESLA_HOMEDASH_MAP_API_KEY from
    // the environment or .env — a deployment secret like the backend's keys, so it
    // is not an Options-view setting. The OSM plugin reads its tile host once, when
    // the map is created, so a changed key needs a restart. Without a key the maps
    // show only the keyless EOX Sentinel-2 imagery (~10 m), which they also show
    // outside MML's coverage (items/tesla/BasemapSwitch.qml), and the log says so.
    const QString mapApiKey = dotenv::valueOr("TESLA_HOMEDASH_MAP_API_KEY", QString()).trimmed();
    if (!mapApiKey.isEmpty()) {
        m_mapTilesUrl = kMmlTilesUrlTemplate.arg(mapApiKey);
        m_mapAttribution = kMmlAttribution;
        logger.info(QStringLiteral("Map basemap: MML orthophoto (0.5 m, keyed)"));
    } else {
        logger.warning(QStringLiteral("Map basemap: EOX Sentinel-2 (keyless fallback); set "
                                      "TESLA_HOMEDASH_MAP_API_KEY in .env for MML's 0.5 m imagery"));
    }

    // Screensaver: after `screensaverTimeoutMs` of no input the frontend fades to a
    // photo slideshow from a fixed folder (ScreensaverPhotos).
    bool minsOk = false;
    const QVariant savedTimeout = saved("screensaverTimeoutMin");
    const int mins =
        savedTimeout.isValid()
            ? savedTimeout.toInt(&minsOk)
            : dotenv::valueOr("TESLA_HOMEDASH_SCREENSAVER_TIMEOUT_MIN", QString()).toInt(&minsOk);
    m_screensaverTimeoutMs = (minsOk && mins >= 1) ? mins * 60000 : 30 * 60 * 1000;
    logger.info(QStringLiteral("Screensaver inactivity timeout: %1 min")
                    .arg(m_screensaverTimeoutMs / 60000));

    // The escape hatch for a device whose 3.x context misbehaves: back to Qt's default.
    if (dotenv::valueOr("TESLA_HOMEDASH_GPU_CANVAS", QStringLiteral("1")).trimmed() == QStringLiteral("0")) {
        logger.info(QStringLiteral("OpenGL: TESLA_HOMEDASH_GPU_CANVAS=0; Qt's default context"));
    } else {
        m_gpuCanvas = requestGpuCanvasFormat();
    }
}

// Qt's own default folder for the OSM plugin's tiles (QAbstractGeoTileCache::
// baseLocationCacheDirectory() + "osm"), named here so the maps and the cache clear use one path.
QString AppConfig::mapTileCacheDir() {
    return QStandardPaths::writableLocation(QStandardPaths::GenericCacheLocation) +
           QStringLiteral("/QtLocation/5.8/tiles/osm");
}

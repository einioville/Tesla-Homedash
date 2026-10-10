#include "appconfig.hh"

#include <QStringList>
#include <QVariant>
#include <QtGlobal>

#include "dotenv.hh"
#include "settings.hh"

namespace {
const Logger logger = Logger::get("app");

// --- Basemap tile providers -------------------------------------------------
// The OSM plugin substitutes %x/%y/%z positionally anywhere in the URL (Qt 6.7+),
// so a z/y/x provider is driven by ordering the tokens %z/%y/%x; the literal %x
// also suppresses the plugin's default "%z/%x/%y.png" postfix. Tiles must be
// EPSG:3857 Web Mercator. Consumed by items/tesla/TeslaMap.qml via the App
// singleton.

// EOX Sentinel-2 cloudless — no API key, ~10 m. Keyless default so the map
// works out of the box.
const QString kEoxTilesUrl = QStringLiteral(
    "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/"
    "GoogleMapsCompatible/%z/%y/%x.jpg");
const QString kEoxAttribution = QStringLiteral(
    "Sentinel-2 cloudless (s2maps.eu) by EOX — modified Copernicus Sentinel data");

// MML (National Land Survey of Finland) open orthophoto — 0.5 m aerial of
// Finland, CC BY 4.0. Needs a free api-key (the %1). Web-Mercator variant so it
// aligns with the EPSG:3857 map.
const QString kMmlTilesUrlTemplate = QStringLiteral(
    "https://avoin-karttakuva.maanmittauslaitos.fi/avoin/wmts/1.0.0/ortokuva/"
    "default/WGS84_Pseudo-Mercator/%z/%y/%x.jpg?api-key=%1");
const QString kMmlAttribution = QStringLiteral("© Maanmittauslaitos");

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
    // the map is created, so a changed key needs a restart. Without a key the map
    // falls back to the keyless EOX Sentinel-2 imagery (~10 m) rather than going
    // blank, and says so.
    const QString mapApiKey = dotenv::valueOr("TESLA_HOMEDASH_MAP_API_KEY", QString()).trimmed();
    if (!mapApiKey.isEmpty()) {
        m_mapTilesUrl = kMmlTilesUrlTemplate.arg(mapApiKey);
        m_mapAttribution = kMmlAttribution;
        logger.info(QStringLiteral("Map basemap: MML orthophoto (0.5 m, keyed)"));
    } else {
        m_mapTilesUrl = kEoxTilesUrl;
        m_mapAttribution = kEoxAttribution;
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
}

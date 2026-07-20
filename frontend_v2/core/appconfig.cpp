#include "appconfig.hh"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHash>
#include <QStringList>
#include <QTextStream>
#include <QUrl>
#include <QtGlobal>

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

// --- .env loading -----------------------------------------------------------
// The frontend shares the backend's repo-root .env. Real environment variables
// still win; .env is a fallback so secrets (the map api-key) live outside the
// committed source tree.

// Walk up from the working directory and the executable directory to find the
// first .env. Returns an empty string if none is found.
QString findDotEnv() {
    QStringList starts{QDir::currentPath()};
    if (QCoreApplication::instance() != nullptr) {
        starts << QCoreApplication::applicationDirPath();
    }
#ifdef FRONTEND_V2_SOURCE_DIR
    // Dev builds (Qt Creator shadow build) put the exe outside the source tree,
    // so the cwd/exe walk-up never reaches the repo .env; the baked source dir
    // walks up to it. Harmless when the path no longer exists (deploy targets
    // rely on real environment variables, which take precedence anyway).
    starts << QStringLiteral(FRONTEND_V2_SOURCE_DIR);
#endif
    for (const QString& start : starts) {
        QDir dir(start);
        do {
            const QString candidate = dir.filePath(QStringLiteral(".env"));
            if (QFileInfo::exists(candidate)) {
                return candidate;
            }
        } while (dir.cdUp());
    }
    return QString();
}

// Minimal KEY=VALUE parser: skips blank/`#` lines, tolerates a leading
// `export `, strips matching surrounding quotes. Values are not interpolated.
QHash<QString, QString> parseDotEnv(const QString& path) {
    QHash<QString, QString> out;
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
        return out;
    }
    QTextStream in(&file);
    while (!in.atEnd()) {
        QString line = in.readLine().trimmed();
        if (line.isEmpty() || line.startsWith('#')) {
            continue;
        }
        if (line.startsWith(QStringLiteral("export "))) {
            line = line.mid(7).trimmed();
        }
        const int eq = line.indexOf('=');
        if (eq <= 0) {
            continue;
        }
        const QString key = line.left(eq).trimmed();
        QString value = line.mid(eq + 1).trimmed();
        if (value.size() >= 2 &&
            ((value.startsWith('"') && value.endsWith('"')) ||
             (value.startsWith('\'') && value.endsWith('\'')))) {
            value = value.mid(1, value.size() - 2);
        }
        out.insert(key, value);
    }
    return out;
}

// Real env var (if set and non-empty) wins; then the .env value (if non-empty);
// then the supplied default. An empty placeholder line in .env reads as "unset".
QString envOr(const QHash<QString, QString>& dotenv, const char* key, const QString& def) {
    if (qEnvironmentVariableIsSet(key)) {
        const QString fromEnv = qEnvironmentVariable(key);
        if (!fromEnv.isEmpty()) {
            return fromEnv;
        }
    }
    const auto it = dotenv.constFind(QString::fromLatin1(key));
    if (it != dotenv.constEnd() && !it.value().isEmpty()) {
        return it.value();
    }
    return def;
}
}  // namespace

AppConfig::AppConfig(QObject* parent) : QObject(parent) {
    const QString dotEnvPath = findDotEnv();
    const QHash<QString, QString> dotenv =
        dotEnvPath.isEmpty() ? QHash<QString, QString>() : parseDotEnv(dotEnvPath);
    if (!dotEnvPath.isEmpty()) {
        logger.info(QStringLiteral("Loaded .env from %1").arg(dotEnvPath));
    }

    m_backendHost = envOr(dotenv, "TESLA_HOMEDASH_BACKEND_HOST", QStringLiteral("127.0.0.1"));

    bool ok = false;
    const int port = envOr(dotenv, "TESLA_HOMEDASH_BACKEND_PORT", QString()).toInt(&ok);
    m_backendPort = (ok && port >= 1 && port <= 65535) ? static_cast<quint16>(port) : 6969;

    // Log level: parse, defaulting to INFO. An explicit-but-invalid value falls
    // back to INFO with a warning (which lands because main() has already
    // installed the logger at INFO before constructing AppConfig).
    const QString rawLevel = envOr(dotenv, "TESLA_HOMEDASH_LOG_LEVEL", QString());
    m_logLevel = Logger::parseLevel(rawLevel, Logger::Level::Info);
    static const QStringList kValidLevels = {
        QStringLiteral("debug"), QStringLiteral("info"), QStringLiteral("warning"),
        QStringLiteral("error"), QStringLiteral("critical")};
    if (!rawLevel.isEmpty() && !kValidLevels.contains(rawLevel.trimmed().toLower())) {
        logger.warning(QStringLiteral("Unknown TESLA_HOMEDASH_LOG_LEVEL '%1'; using info").arg(rawLevel));
    }

    // Map basemap: high-res MML orthophoto when an api-key is configured,
    // otherwise the keyless EOX Sentinel-2 fallback. The key never lives in the
    // committed QML/resource bundle — it comes from the environment or .env.
    const QString mapApiKey = envOr(dotenv, "TESLA_HOMEDASH_MAP_API_KEY", QString()).trimmed();
    if (!mapApiKey.isEmpty()) {
        m_mapTilesUrl = kMmlTilesUrlTemplate.arg(mapApiKey);
        m_mapAttribution = kMmlAttribution;
        logger.info(QStringLiteral("Map basemap: MML orthophoto (0.5 m, keyed)"));
    } else {
        m_mapTilesUrl = kEoxTilesUrl;
        m_mapAttribution = kEoxAttribution;
        logger.info(QStringLiteral("Map basemap: EOX Sentinel-2 (keyless fallback); set "
                                   "TESLA_HOMEDASH_MAP_API_KEY in .env for MML 0.5 m imagery"));
    }

    // Screensaver: after `screensaverTimeoutMs` of no input the frontend fades to a
    // photo slideshow read from `screensaverDir`. The folder comes from the
    // environment so the photos live outside the committed tree; it is handed to
    // QML as a file:// URL. Empty when unset → the screensaver stays off.
    const QString screensaverPath =
        envOr(dotenv, "TESLA_HOMEDASH_SCREENSAVER_DIR", QString()).trimmed();
    if (!screensaverPath.isEmpty()) {
        m_screensaverDir = QUrl::fromLocalFile(screensaverPath).toString();
        logger.info(QStringLiteral("Screensaver photos: %1").arg(screensaverPath));
    } else {
        logger.info(QStringLiteral("Screensaver folder unset; set TESLA_HOMEDASH_SCREENSAVER_DIR "
                                   "to enable the screensaver"));
    }

    bool minsOk = false;
    const int mins =
        envOr(dotenv, "TESLA_HOMEDASH_SCREENSAVER_TIMEOUT_MIN", QString()).toInt(&minsOk);
    m_screensaverTimeoutMs = (minsOk && mins >= 1) ? mins * 60000 : 30 * 60 * 1000;
    logger.info(QStringLiteral("Screensaver inactivity timeout: %1 min")
                    .arg(m_screensaverTimeoutMs / 60000));
}

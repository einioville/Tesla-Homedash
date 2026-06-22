#include "appconfig.hh"

#include <QStringList>
#include <QtGlobal>

namespace {
const Logger logger = Logger::get("app");
}

AppConfig AppConfig::load() {
    AppConfig cfg;

    cfg.backendHost = qEnvironmentVariable("TESLA_HOMEDASH_BACKEND_HOST", QStringLiteral("127.0.0.1"));

    bool ok = false;
    const int port = qEnvironmentVariableIntValue("TESLA_HOMEDASH_BACKEND_PORT", &ok);
    cfg.backendPort = (ok && port >= 1 && port <= 65535) ? static_cast<quint16>(port) : 6969;

    // Log level: parse the env var, defaulting to INFO. An explicit-but-invalid
    // value falls back to INFO with a warning (which lands because main() has
    // already installed the logger at INFO before calling load()).
    const QString rawLevel = qEnvironmentVariable("TESLA_HOMEDASH_LOG_LEVEL");
    cfg.logLevel = Logger::parseLevel(rawLevel, Logger::Level::Info);
    static const QStringList kValidLevels = {
        QStringLiteral("debug"), QStringLiteral("info"), QStringLiteral("warning"),
        QStringLiteral("error"), QStringLiteral("critical")};
    if (!rawLevel.isEmpty() && !kValidLevels.contains(rawLevel.trimmed().toLower())) {
        logger.warning(QStringLiteral("Unknown TESLA_HOMEDASH_LOG_LEVEL '%1'; using info").arg(rawLevel));
    }

    return cfg;
}

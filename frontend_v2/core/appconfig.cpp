#include "appconfig.hh"

#include <QtGlobal>

AppConfig AppConfig::load() {
    AppConfig cfg;

    cfg.backendHost = qEnvironmentVariable("TESLA_HOMEDASH_BACKEND_HOST", QStringLiteral("127.0.0.1"));

    bool ok = false;
    const int port = qEnvironmentVariableIntValue("TESLA_HOMEDASH_BACKEND_PORT", &ok);
    cfg.backendPort = (ok && port >= 1 && port <= 65535) ? static_cast<quint16>(port) : 6969;

    return cfg;
}

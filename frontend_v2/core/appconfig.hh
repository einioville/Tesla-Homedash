#ifndef FRONTEND_V2_APPCONFIG_HH
#define FRONTEND_V2_APPCONFIG_HH

#include <QString>
#include <QtGlobal>

#include "logger.hh"

/**
 * AppConfig — minimal runtime configuration read from environment variables at
 * startup. The env-var names mirror the production frontend so existing
 * deployments carry over.
 *
 *   TESLA_HOMEDASH_BACKEND_HOST  (string)  default "127.0.0.1"
 *   TESLA_HOMEDASH_BACKEND_PORT  (uint16)  default 6969
 *   TESLA_HOMEDASH_LOG_LEVEL     (string)  default "info"
 *                                (debug|info|warning|error|critical)
 */
struct AppConfig {
    QString backendHost;
    quint16 backendPort;
    Logger::Level logLevel;

    static AppConfig load();
};

#endif  // FRONTEND_V2_APPCONFIG_HH

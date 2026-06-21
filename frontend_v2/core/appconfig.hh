#ifndef FRONTEND_V2_APPCONFIG_HH
#define FRONTEND_V2_APPCONFIG_HH

#include <QString>
#include <QtGlobal>

/**
 * AppConfig — minimal runtime configuration read from environment variables at
 * startup. Stage 1 only needs the backend endpoint; the env-var names mirror the
 * production frontend so existing deployments carry over.
 *
 *   TESLA_HOMEDASH_BACKEND_HOST  (string)  default "127.0.0.1"
 *   TESLA_HOMEDASH_BACKEND_PORT  (uint16)  default 6969
 */
struct AppConfig {
    QString backendHost;
    quint16 backendPort;

    static AppConfig load();
};

#endif  // FRONTEND_V2_APPCONFIG_HH

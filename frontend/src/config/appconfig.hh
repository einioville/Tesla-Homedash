//
// Created by ville on 13.5.2026.
//

#ifndef GUI_APPCONFIG_HH
#define GUI_APPCONFIG_HH

#include <QString>

/**
 * AppConfig — runtime configuration read from environment variables at
 * startup. Lets the dashboard be redeployed (different backend host, screen
 * size, fullscreen mode) without recompiling. All fields fall back to the
 * 1.0 defaults baked into the binary if the corresponding env var is unset.
 *
 * Recognised env vars:
 *   TESLA_HOMEDASH_BACKEND_HOST   (string)  default "127.0.0.1"
 *   TESLA_HOMEDASH_BACKEND_PORT   (uint16)  default 6969
 *   TESLA_HOMEDASH_WINDOW_WIDTH   (uint)    default 1280
 *   TESLA_HOMEDASH_WINDOW_HEIGHT  (uint)    default 800
 *   TESLA_HOMEDASH_FULLSCREEN     (bool)    default false
 *                                  ("1" / "true" / "yes", case-insensitive)
 */
struct AppConfig {
    QString backend_host;
    quint16 backend_port;
    int window_width;
    int window_height;
    bool fullscreen;

    static AppConfig load();
};

#endif //GUI_APPCONFIG_HH

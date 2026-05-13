//
// Created by ville on 13.5.2026.
//

#include "appconfig.hh"
#include <QByteArray>
#include <QString>
#include <QtGlobal>

namespace {
    bool parseBool(const QByteArray &raw, bool fallback) {
        if (raw.isEmpty()) {
            return fallback;
        }
        const QByteArray lower = raw.trimmed().toLower();
        if (lower == "1" || lower == "true" || lower == "yes" || lower == "on") {
            return true;
        }
        if (lower == "0" || lower == "false" || lower == "no" || lower == "off") {
            return false;
        }
        return fallback;
    }

    int parseInt(const char *name, int fallback, int min_value, int max_value) {
        bool ok = false;
        const int value = qEnvironmentVariableIntValue(name, &ok);
        if (!ok) {
            return fallback;
        }
        if (value < min_value || value > max_value) {
            qWarning() << "AppConfig:" << name << "out of range" << value
                       << "- using default" << fallback;
            return fallback;
        }
        return value;
    }
}

AppConfig AppConfig::load() {
    AppConfig cfg;

    cfg.backend_host = qEnvironmentVariable("TESLA_HOMEDASH_BACKEND_HOST", "127.0.0.1");
    cfg.backend_port = static_cast<quint16>(
        parseInt("TESLA_HOMEDASH_BACKEND_PORT", 6969, 1, 65535));
    cfg.window_width = parseInt("TESLA_HOMEDASH_WINDOW_WIDTH", 1280, 320, 7680);
    cfg.window_height = parseInt("TESLA_HOMEDASH_WINDOW_HEIGHT", 800, 240, 4320);
    cfg.fullscreen = parseBool(qgetenv("TESLA_HOMEDASH_FULLSCREEN"), false);

    qInfo().nospace() << "AppConfig | backend=" << cfg.backend_host << ":" << cfg.backend_port
                      << " | window=" << cfg.window_width << "x" << cfg.window_height
                      << " | fullscreen=" << cfg.fullscreen;

    return cfg;
}

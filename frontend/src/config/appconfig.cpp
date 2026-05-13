//
// Created by ville on 13.5.2026.
//

#include "appconfig.hh"
#include <QByteArray>
#include <QString>
#include <QtGlobal>
#include <QDebug>

#include "../utils/logger.hh"

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

    int parseInt(const Logger &log, const char *name, int fallback, int min_value, int max_value) {
        bool ok = false;
        const int value = qEnvironmentVariableIntValue(name, &ok);
        if (!ok) {
            return fallback;
        }
        if (value < min_value || value > max_value) {
            log.warning(QStringLiteral("Env var %1 out of range (%2), using default %3")
                            .arg(QString::fromLatin1(name)).arg(value).arg(fallback));
            return fallback;
        }
        return value;
    }

    QString levelToString(Logger::Level level) {
        switch (level) {
            case Logger::Level::Debug:    return QStringLiteral("debug");
            case Logger::Level::Info:     return QStringLiteral("info");
            case Logger::Level::Warning:  return QStringLiteral("warning");
            case Logger::Level::Error:    return QStringLiteral("error");
            case Logger::Level::Critical: return QStringLiteral("critical");
        }
        return QStringLiteral("info");
    }
}

AppConfig AppConfig::load() {
    // The Logger threshold isn't installed yet at this point, so any
    // logs we emit here go through with the install()-time default.
    // That's fine — startup config-load is small and INFO-level.
    static const Logger log = Logger::get("config");

    AppConfig cfg;

    cfg.backend_host = qEnvironmentVariable("TESLA_HOMEDASH_BACKEND_HOST", "127.0.0.1");
    cfg.backend_port = static_cast<quint16>(
        parseInt(log, "TESLA_HOMEDASH_BACKEND_PORT", 6969, 1, 65535));
    cfg.window_width = parseInt(log, "TESLA_HOMEDASH_WINDOW_WIDTH", 1280, 320, 7680);
    cfg.window_height = parseInt(log, "TESLA_HOMEDASH_WINDOW_HEIGHT", 800, 240, 4320);
    cfg.fullscreen = parseBool(qgetenv("TESLA_HOMEDASH_FULLSCREEN"), false);

    const QString raw_level = qEnvironmentVariable("TESLA_HOMEDASH_LOG_LEVEL", "info");
    const QString raw_lower = raw_level.trimmed().toLower();
    const bool is_known = raw_lower == QStringLiteral("debug")
                       || raw_lower == QStringLiteral("info")
                       || raw_lower == QStringLiteral("warning")
                       || raw_lower == QStringLiteral("error")
                       || raw_lower == QStringLiteral("critical");
    if (!is_known) {
        log.warning(QStringLiteral("Env var TESLA_HOMEDASH_LOG_LEVEL invalid (%1), using default info")
                        .arg(raw_level));
    }
    cfg.log_level = Logger::parseLevel(raw_level, Logger::Level::Info);

    log.info(QStringLiteral("AppConfig loaded | backend=%1:%2 | window=%3x%4 | fullscreen=%5 | log_level=%6")
                 .arg(cfg.backend_host)
                 .arg(cfg.backend_port)
                 .arg(cfg.window_width)
                 .arg(cfg.window_height)
                 .arg(cfg.fullscreen ? QStringLiteral("true") : QStringLiteral("false"),
                      levelToString(cfg.log_level)));

    return cfg;
}

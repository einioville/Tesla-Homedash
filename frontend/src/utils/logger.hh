//
// Created by ville on 14.5.2026.
//

#ifndef GUI_LOGGER_HH
#define GUI_LOGGER_HH

#include <QString>

/**
 * Logger — frontend mirror of the Python backend's logger configurator
 * (backend/src/utils/logger_configurator.py).
 *
 * Same output format ("LEVEL | YYYY-MM-DD | HH:MM:SS | name | message"),
 * same five severity levels, same stdout-only destination. The call-site
 * API mirrors the backend's `logger = logging.getLogger("name")` pattern:
 *
 *   static const Logger logger = Logger::get("server_client");
 *   logger.info("Connected to backend");
 *   logger.warning(QString("Truncated payload: need=%1 have=%2").arg(n).arg(m));
 *
 * Thread-safe: cover-art and dominant-colour QtConcurrent workers can
 * log freely; writes to stdout are serialised by a static QMutex.
 *
 * Logger::install() must be called once from main() before any other
 * log site. It sets the global threshold (drops anything below it) and
 * installs a qInstallMessageHandler so Qt-internal warnings (QML,
 * QGraphics, deprecation notices, etc.) flow through this same
 * formatter under the source name "qt".
 */
class Logger {
public:
    enum class Level { Debug, Info, Warning, Error, Critical };

    static Logger get(const QString &name);

    // Idempotent. Sets the global level threshold and installs the
    // Qt message handler. Call once from main() right after AppConfig::load().
    static void install(Level default_level);

    // Case-insensitive parse of the names used by AppConfig:
    //   "debug" | "info" | "warning" | "error" | "critical"
    // Anything else returns `fallback` and emits a warning via the
    // "config" logger.
    static Level parseLevel(const QString &text, Level fallback);

    void debug(const QString &message) const;
    void info(const QString &message) const;
    void warning(const QString &message) const;
    void error(const QString &message) const;
    void critical(const QString &message) const;

private:
    explicit Logger(QString name);
    void log(Level level, const QString &message) const;

    QString m_name;
};

#endif //GUI_LOGGER_HH

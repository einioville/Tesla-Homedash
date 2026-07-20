#ifndef FRONTEND_V2_LOGGER_HH
#define FRONTEND_V2_LOGGER_HH

#include <QString>

/**
 * Logger — frontend_v2 mirror of the Python backend's logger configurator
 * (backend/src/utils/logger_configurator.py) and the original Widgets
 * frontend's logger (frontend/src/utils/logger.{hh,cpp}).
 *
 * Same output format ("LEVEL | YYYY-MM-DD | HH:MM:SS | source | message"),
 * same five severity levels. The destination is stdout (→ systemd/journald on
 * the Pi); on Windows the same line is also mirrored to the OutputDebugString
 * debug channel, because GUI-subsystem (WIN32_EXECUTABLE) builds have no console
 * so stdout is invisible in a terminal and in Qt Creator's Application Output.
 * The call-site API
 * mirrors the backend's `logger = logging.getLogger("name")` pattern; each core
 * .cpp keeps one file-local instance:
 *
 *   static const Logger logger = Logger::get("server_client");
 *   logger.info(QStringLiteral("Connected to %1:%2").arg(host).arg(port));
 *   logger.warning(QStringLiteral("Truncated payload for stream %1").arg(id));
 *
 * Sources are grouped by subsystem, not by file. The set in use:
 *   app            — application startup / lifecycle (main.cpp, AppConfig)
 *   server_client  — TCP transport (core/serverclient.cpp)
 *   tesla          — Tesla telemetry + HVAC commands (core/tesla/tesladata.cpp)
 *   tesla.history  — Tesla history / graph requests (core/tesla/teslahistory.cpp)
 *   media          — media metadata, transport, cover decode (core/media/mediadata.cpp)
 *   weather        — weather forecast (core/weather/weatherdata.cpp)
 *   notifications  — frontend notifications (core/notification/notificationhandler.cpp)
 *   idle           — inactivity watcher / screensaver (core/idlewatcher.cpp)
 *   qt             — Qt-internal messages (QML/Quick warnings, etc.) via the handler
 *
 * The QML UI layer must not log — only the C++ core (data/transport) does.
 *
 * Thread-safe: the media cover-art decode runs on a QtConcurrent worker, so any
 * log site may be reached off the GUI thread; writes to stdout are serialised by
 * a static QMutex.
 *
 * Logger::install() must be called once from main() before any other log site.
 * It sets the global threshold (drops anything below it) and installs a
 * qInstallMessageHandler so Qt-internal warnings (QML, Quick, deprecation
 * notices, etc.) flow through this same formatter under the source name "qt".
 */
class Logger {
public:
    enum class Level { Debug, Info, Warning, Error, Critical };

    static Logger get(const QString &name);

    // Idempotent. Sets the global level threshold and installs the Qt message
    // handler. Call once from main() (and again once the configured level is
    // known — INFO first so AppConfig's own logs land, then the real level).
    static void install(Level default_level);

    // Case-insensitive parse of the names used by AppConfig:
    //   "debug" | "info" | "warning" | "error" | "critical"
    // Anything else returns `fallback`.
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

#endif  // FRONTEND_V2_LOGGER_HH

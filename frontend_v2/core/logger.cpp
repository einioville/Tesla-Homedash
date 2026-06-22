#include "logger.hh"

#include <QDateTime>
#include <QMutex>
#include <QMutexLocker>
#include <QTextStream>
#include <QtGlobal>
#include <QtMessageHandler>

#include <utility>

#ifdef Q_OS_WIN
#  ifndef WIN32_LEAN_AND_MEAN
#    define WIN32_LEAN_AND_MEAN
#  endif
#  ifndef NOMINMAX
#    define NOMINMAX
#  endif
#  include <windows.h>
#endif

namespace {
// Global level threshold. Messages below this severity are dropped before any
// string formatting work. Set by Logger::install().
Logger::Level g_threshold = Logger::Level::Info;

// Serialises writes to stdout so QtConcurrent workers (e.g. the media cover-art
// decode) and the GUI thread don't interleave half-lines.
QMutex &stdoutMutex() {
    static QMutex m;
    return m;
}

QString levelToString(Logger::Level level) {
    switch (level) {
        case Logger::Level::Debug:    return QStringLiteral("DEBUG");
        case Logger::Level::Info:     return QStringLiteral("INFO");
        case Logger::Level::Warning:  return QStringLiteral("WARNING");
        case Logger::Level::Error:    return QStringLiteral("ERROR");
        case Logger::Level::Critical: return QStringLiteral("CRITICAL");
    }
    return QStringLiteral("INFO");
}

// Maps Qt's own message types onto our levels so that anything emitted via
// qInfo/qWarning/qCritical/qFatal/qDebug from Qt itself (QML, Quick,
// deprecation notices, etc.) lands in the same formatter.
Logger::Level qtMsgTypeToLevel(QtMsgType type) {
    switch (type) {
        case QtDebugMsg:    return Logger::Level::Debug;
        case QtInfoMsg:     return Logger::Level::Info;
        case QtWarningMsg:  return Logger::Level::Warning;
        case QtCriticalMsg: return Logger::Level::Error;
        case QtFatalMsg:    return Logger::Level::Critical;
    }
    return Logger::Level::Info;
}

void qtMessageHandler(QtMsgType type, const QMessageLogContext &context, const QString &message) {
    Q_UNUSED(context);
    static const Logger qt_logger = Logger::get("qt");
    switch (qtMsgTypeToLevel(type)) {
        case Logger::Level::Debug:    qt_logger.debug(message); break;
        case Logger::Level::Info:     qt_logger.info(message); break;
        case Logger::Level::Warning:  qt_logger.warning(message); break;
        case Logger::Level::Error:    qt_logger.error(message); break;
        case Logger::Level::Critical: qt_logger.critical(message); break;
    }
}
}  // namespace

Logger::Logger(QString name) : m_name(std::move(name)) {}

Logger Logger::get(const QString &name) {
    return Logger(name);
}

void Logger::install(Level default_level) {
    g_threshold = default_level;
    qInstallMessageHandler(&qtMessageHandler);
}

Logger::Level Logger::parseLevel(const QString &text, Level fallback) {
    const QString t = text.trimmed().toLower();
    if (t == QStringLiteral("debug"))    return Level::Debug;
    if (t == QStringLiteral("info"))     return Level::Info;
    if (t == QStringLiteral("warning"))  return Level::Warning;
    if (t == QStringLiteral("error"))    return Level::Error;
    if (t == QStringLiteral("critical")) return Level::Critical;
    return fallback;
}

void Logger::debug(const QString &message) const    { log(Level::Debug, message); }
void Logger::info(const QString &message) const     { log(Level::Info, message); }
void Logger::warning(const QString &message) const  { log(Level::Warning, message); }
void Logger::error(const QString &message) const    { log(Level::Error, message); }
void Logger::critical(const QString &message) const { log(Level::Critical, message); }

void Logger::log(Level level, const QString &message) const {
    if (static_cast<int>(level) < static_cast<int>(g_threshold)) {
        return;
    }

    const QString timestamp = QDateTime::currentDateTime().toString(QStringLiteral("yyyy-MM-dd | HH:mm:ss"));
    const QString line = QStringLiteral("%1 | %2 | %3 | %4")
            .arg(levelToString(level), timestamp, m_name, message);

    QMutexLocker lock(&stdoutMutex());
    QTextStream out(stdout);
    out << line << '\n';
    out.flush();

#ifdef Q_OS_WIN
    // GUI-subsystem builds (WIN32_EXECUTABLE) have no attached console, so the
    // stdout write above is invisible both in a terminal and in Qt Creator's
    // Application Output. Mirror the line to the Windows debug channel, which
    // Qt Creator (and DebugView) display. Dev aid only — compiled out on the
    // Pi (Linux), where stdout reaches systemd/journald normally.
    const QString debugLine = line + QLatin1Char('\n');
    OutputDebugStringW(reinterpret_cast<const wchar_t *>(debugLine.utf16()));
#endif
}

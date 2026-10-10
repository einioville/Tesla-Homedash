#include "logger.hh"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QMutex>
#include <QMutexLocker>
#include <QStandardPaths>
#include <QTextStream>
#include <QtGlobal>
#include <QtMessageHandler>

#include <atomic>
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
// stdout's level threshold. A message below both thresholds is dropped before
// any string formatting work. Set by Logger::install() and, at runtime when the
// Options view's log level changes, by setLevels() — while worker threads may be
// logging, hence atomic.
std::atomic<Logger::Level> g_threshold{Logger::Level::Info};
// The log file's own threshold: the same as stdout's, except that the Options
// view's DEBUG reaches only the file.
std::atomic<Logger::Level> g_fileThreshold{Logger::Level::Info};

// Serialises writes to stdout and the log file so QtConcurrent workers (e.g. the
// media cover-art decode) and the GUI thread don't interleave half-lines; also
// guards the file state below.
QMutex &stdoutMutex() {
    static QMutex m;
    return m;
}

// The open log file, its path and how much has been written to it. Guarded by
// stdoutMutex().
QFile *g_file = nullptr;
QString g_filePath;
qint64 g_fileBytes = 0;

constexpr qint64 kFileMaxBytes = 5 * 1024 * 1024;
constexpr int kFileBackups = 3;

// Opens (or reopens) g_filePath for appending. Caller holds the mutex.
bool openFileLocked() {
    delete g_file;
    g_file = new QFile(g_filePath);
    if (!g_file->open(QIODevice::WriteOnly | QIODevice::Append)) {
        delete g_file;
        g_file = nullptr;
        return false;
    }
    g_fileBytes = g_file->size();
    return true;
}

// frontend.log -> .1 -> .2 -> .3, the oldest dropped. Caller holds the mutex.
void rotateLocked() {
    g_file->close();
    QFile::remove(QStringLiteral("%1.%2").arg(g_filePath).arg(kFileBackups));
    for (int i = kFileBackups - 1; i >= 1; --i) {
        QFile::rename(QStringLiteral("%1.%2").arg(g_filePath).arg(i),
                      QStringLiteral("%1.%2").arg(g_filePath).arg(i + 1));
    }
    QFile::rename(g_filePath, g_filePath + QStringLiteral(".1"));
    openFileLocked();
}

// The lines of the records at WARNING or above, with each one's continuation
// lines — the backend's filter (system_service/log_files.py), line for line.
QByteArray warningLines(const QByteArray &content) {
    static const QList<QByteArray> levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"};
    QByteArray kept;
    bool keeping = false;
    for (const QByteArray &line : content.split('\n')) {
        const qsizetype bar = line.indexOf(" | ");
        const QByteArray head = bar > 0 ? line.left(bar) : QByteArray();
        if (levels.contains(head)) {
            keeping = head == "WARNING" || head == "ERROR" || head == "CRITICAL";
        }
        if (keeping && !line.isEmpty()) {
            kept += line + '\n';
        }
    }
    return kept;
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
    g_threshold.store(default_level, std::memory_order_relaxed);
    g_fileThreshold.store(default_level, std::memory_order_relaxed);
    qInstallMessageHandler(&qtMessageHandler);
}

void Logger::setLevels(Level stdoutLevel, Level fileLevel) {
    g_threshold.store(stdoutLevel, std::memory_order_relaxed);
    g_fileThreshold.store(fileLevel, std::memory_order_relaxed);
}

QString Logger::defaultDirectory() {
    const QString override = qEnvironmentVariable("TESLA_HOMEDASH_LOG_DIR");
    if (!override.isEmpty()) {
        return override;
    }
    return QStandardPaths::writableLocation(QStandardPaths::GenericStateLocation) +
           QStringLiteral("/Tesla-Homedash/logs");
}

bool Logger::openFile(const QString &directory) {
    if (!QDir().mkpath(directory)) {
        return false;
    }
    QMutexLocker lock(&stdoutMutex());
    g_filePath = directory + QStringLiteral("/frontend.log");
    return openFileLocked();
}

qint64 Logger::clearFiles(bool keepWarnings) {
    QMutexLocker lock(&stdoutMutex());
    if (g_filePath.isEmpty()) {
        return 0;
    }
    qint64 freed = 0;
    QStringList paths{g_filePath};
    for (int i = 1; i <= kFileBackups; ++i) {
        paths.append(QStringLiteral("%1.%2").arg(g_filePath).arg(i));
    }
    if (g_file != nullptr) {
        g_file->close();
    }
    for (const QString &path : std::as_const(paths)) {
        QFile file(path);
        if (!file.exists()) {
            continue;
        }
        const qint64 before = file.size();
        QByteArray kept;
        if (keepWarnings && file.open(QIODevice::ReadOnly)) {
            kept = warningLines(file.readAll());
            file.close();
        }
        // The active file stays (it is reopened below); an emptied backup goes.
        if (kept.isEmpty() && path != g_filePath) {
            file.remove();
        } else if (file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
            file.write(kept);
            file.close();
        }
        freed += before - kept.size();
    }
    openFileLocked();
    return qMax<qint64>(0, freed);
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
    const bool toStdout =
        static_cast<int>(level) >= static_cast<int>(g_threshold.load(std::memory_order_relaxed));
    const bool toFile =
        static_cast<int>(level) >= static_cast<int>(g_fileThreshold.load(std::memory_order_relaxed));
    if (!toStdout && !toFile) {
        return;
    }

    const QString timestamp = QDateTime::currentDateTime().toString(QStringLiteral("yyyy-MM-dd | HH:mm:ss"));
    const QString line = QStringLiteral("%1 | %2 | %3 | %4")
            .arg(levelToString(level), timestamp, m_name, message);

    QMutexLocker lock(&stdoutMutex());
    if (toFile && g_file != nullptr) {
        const QByteArray bytes = line.toUtf8() + '\n';
        g_file->write(bytes);
        g_file->flush();
        g_fileBytes += bytes.size();
        if (g_fileBytes >= kFileMaxBytes) {
            rotateLocked();
        }
    }
    if (!toStdout) {
        return;
    }
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

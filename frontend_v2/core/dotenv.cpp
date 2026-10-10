#include "dotenv.hh"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHash>
#include <QStringList>
#include <QTextStream>
#include <QtGlobal>

namespace {

// Walk up from the working directory and the executable directory to find the
// first .env. Returns an empty string if none is found.
QString findDotEnv() {
    QStringList starts{QDir::currentPath()};
    if (QCoreApplication::instance() != nullptr) {
        starts << QCoreApplication::applicationDirPath();
    }
#ifdef FRONTEND_V2_SOURCE_DIR
    // Dev builds (Qt Creator shadow build) put the exe outside the source tree,
    // so the cwd/exe walk-up never reaches the repo .env; the baked source dir
    // walks up to it. Harmless when the path no longer exists (deploy targets
    // rely on real environment variables, which take precedence anyway).
    starts << QStringLiteral(FRONTEND_V2_SOURCE_DIR);
#endif
    for (const QString &start : starts) {
        QDir dir(start);
        do {
            const QString candidate = dir.filePath(QStringLiteral(".env"));
            if (QFileInfo::exists(candidate)) {
                return candidate;
            }
        } while (dir.cdUp());
    }
    return QString();
}

// Minimal KEY=VALUE parser: skips blank/`#` lines, tolerates a leading
// `export `, strips matching surrounding quotes. Values are not interpolated.
QHash<QString, QString> parseDotEnv(const QString &path) {
    QHash<QString, QString> out;
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
        return out;
    }
    QTextStream in(&file);
    while (!in.atEnd()) {
        QString line = in.readLine().trimmed();
        if (line.isEmpty() || line.startsWith('#')) {
            continue;
        }
        if (line.startsWith(QStringLiteral("export "))) {
            line = line.mid(7).trimmed();
        }
        const int eq = line.indexOf('=');
        if (eq <= 0) {
            continue;
        }
        const QString key = line.left(eq).trimmed();
        QString value = line.mid(eq + 1).trimmed();
        if (value.size() >= 2 &&
            ((value.startsWith('"') && value.endsWith('"')) ||
             (value.startsWith('\'') && value.endsWith('\'')))) {
            value = value.mid(1, value.size() - 2);
        }
        out.insert(key, value);
    }
    return out;
}

struct Cache {
    QString path;
    QHash<QString, QString> values;
};

// Loaded on first use and kept for the process lifetime: .env is a startup input
// that never changes under a running app.
const Cache &cache() {
    static const Cache instance = [] {
        Cache c;
        c.path = findDotEnv();
        if (!c.path.isEmpty()) {
            c.values = parseDotEnv(c.path);
        }
        return c;
    }();
    return instance;
}

}  // namespace

namespace dotenv {

QString valueOr(const char *key, const QString &fallback) {
    if (qEnvironmentVariableIsSet(key)) {
        const QString fromEnv = qEnvironmentVariable(key);
        if (!fromEnv.isEmpty()) {
            return fromEnv;
        }
    }
    const auto &values = cache().values;
    const auto it = values.constFind(QString::fromLatin1(key));
    if (it != values.constEnd() && !it.value().isEmpty()) {
        return it.value();
    }
    return fallback;
}

bool isSet(const char *key) { return !valueOr(key, QString()).isEmpty(); }

QString sourcePath() { return cache().path; }

}  // namespace dotenv

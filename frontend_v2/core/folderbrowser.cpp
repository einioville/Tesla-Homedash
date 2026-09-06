#include "folderbrowser.hh"

#include <QDir>
#include <QFileInfo>
#include <QSet>
#include <QStandardPaths>
#include <QStorageInfo>
#include <QUrl>

namespace {
// The extensions the screensaver plays. Kept here rather than in ScreenSaver.qml
// so the picker's image count and the screensaver's playlist cannot disagree.
// Matched case-INSENSITIVELY by both consumers: nameFilters are case-sensitive by
// default and every camera writes DSC_0042.JPG in capitals, so the default would
// report an empty folder for a stick full of photos.
const QStringList kImageNameFilters = {
    QStringLiteral("*.jpg"),  QStringLiteral("*.jpeg"), QStringLiteral("*.png"),
    QStringLiteral("*.bmp"),  QStringLiteral("*.webp"), QStringLiteral("*.gif"),
};

// Directories nobody browsing for photos wants to walk into, and which cost real
// time to stat on a Pi. Hidden only from the SHORTCUTS and never from the listing:
// a user who navigates to /proc deliberately still gets it.
QString homePath() {
    return QDir::homePath();
}

// Where a desktop actually mounts removable media. udisks2 (the Pi's Bookworm
// desktop) uses /media/<user>/<LABEL>, so anything under /media or /run/media is
// fair game at any depth. /mnt is different: it is a general-purpose mount root,
// so only its immediate children qualify — on WSL2 that is the Windows drives
// (/mnt/c), while /mnt/wslg/distro and friends are internals nobody is browsing
// for photos.
bool isRemovableMountPoint(const QString &rootPath) {
    if (rootPath.startsWith(QLatin1String("/media/")) ||
        rootPath.startsWith(QLatin1String("/run/media/"))) {
        return true;
    }
    if (!rootPath.startsWith(QLatin1String("/mnt/"))) {
        return false;
    }
    return rootPath.count(QLatin1Char('/')) == 2 && !rootPath.endsWith(QLatin1Char('/'));
}
}  // namespace

FolderBrowser::FolderBrowser(QObject *parent) : QObject(parent) {}

QStringList FolderBrowser::imageNameFilters() const {
    return kImageNameFilters;
}

bool FolderBrowser::isBrowsable(const QString &path) {
    if (path.isEmpty()) {
        return false;
    }
    // Mirrors what QQuickFolderListModel does to a path internally: it re-parses
    // the decoded local path as a URL and keeps only the path component. A '#'
    // becomes a fragment separator and a '%' starts a percent-escape, so
    // "/media/pi/Loma#2024" resolves to "/media/pi/Loma" and the model opens
    // nothing. Measured against Qt 6.11.1: both cases end at status Null, count 0,
    // even when the URL handed in is correctly encoded.
    return QUrl(path).path() == path;
}

QVariantMap FolderBrowser::describe(const QString &path) const {
    const QString trimmed = path.trimmed();
    QVariantMap out;
    out.insert(QStringLiteral("path"), trimmed);

    if (trimmed.isEmpty()) {
        // The setting's legitimate "not configured" value, not an error.
        out.insert(QStringLiteral("name"), QString());
        out.insert(QStringLiteral("exists"), false);
        out.insert(QStringLiteral("readable"), false);
        out.insert(QStringLiteral("isDir"), false);
        out.insert(QStringLiteral("browsable"), false);
        out.insert(QStringLiteral("parent"), QString());
        out.insert(QStringLiteral("hasParent"), false);
        return out;
    }

    const QFileInfo info(trimmed);
    const QString parent = parentOf(trimmed);
    out.insert(QStringLiteral("name"), info.fileName().isEmpty() ? trimmed : info.fileName());
    out.insert(QStringLiteral("exists"), info.exists());
    // isReadable() is the only way to tell "this directory is empty" from "you may
    // not look inside it": FolderListModel reports BOTH as status Ready with a
    // count of 0.
    out.insert(QStringLiteral("readable"), info.exists() && info.isReadable());
    out.insert(QStringLiteral("isDir"), info.isDir());
    out.insert(QStringLiteral("browsable"), isBrowsable(trimmed));
    out.insert(QStringLiteral("parent"), parent);
    out.insert(QStringLiteral("hasParent"), !parent.isEmpty());
    return out;
}

QString FolderBrowser::parentOf(const QString &path) const {
    const QString trimmed = path.trimmed();
    if (trimmed.isEmpty()) {
        return {};
    }
    QDir dir(trimmed);
    // isRoot() first: cdUp() on "/" returns false but cdUp() on a RELATIVE path
    // would happily walk above it, and the answer for the root must be "nowhere".
    if (dir.isRoot() || !dir.cdUp()) {
        return {};
    }
    return dir.absolutePath();
}

QString FolderBrowser::startFolder(const QString &saved) const {
    // The saved value wins whenever it is still a directory we can open. A path
    // that has gone away (the stick was pulled) deliberately does NOT: opening the
    // dialog on a dead path would show an empty list with no hint why.
    const QString trimmed = saved.trimmed();
    if (!trimmed.isEmpty()) {
        const QFileInfo info(trimmed);
        if (info.isDir() && info.isReadable() && isBrowsable(trimmed)) {
            return QDir(trimmed).absolutePath();
        }
    }

    const QString pictures =
        QStandardPaths::writableLocation(QStandardPaths::PicturesLocation);
    if (!pictures.isEmpty() && QFileInfo(pictures).isDir()) {
        return pictures;
    }
    const QString home = homePath();
    if (!home.isEmpty() && QFileInfo(home).isDir()) {
        return home;
    }
    return QStringLiteral("/");
}

QVariantList FolderBrowser::crumbs(const QString &path) const {
    QVariantList out;
    const QString trimmed = path.trimmed();
    if (trimmed.isEmpty()) {
        return out;
    }

    // Always lead with the root, so the breadcrumb doubles as the way back out of
    // any depth in one tap.
    QVariantMap root;
    root.insert(QStringLiteral("label"), QStringLiteral("/"));
    root.insert(QStringLiteral("path"), QStringLiteral("/"));
    out.append(root);

    const QString absolute = QDir(trimmed).absolutePath();
    QString walked;
    const QStringList parts = absolute.split(QLatin1Char('/'), Qt::SkipEmptyParts);
    for (const QString &part : parts) {
        walked += QLatin1Char('/') + part;
        QVariantMap crumb;
        crumb.insert(QStringLiteral("label"), part);
        crumb.insert(QStringLiteral("path"), walked);
        out.append(crumb);
    }
    return out;
}

QVariantList FolderBrowser::shortcuts() const {
    QVariantList out;
    const auto add = [&out](const QString &label, const QString &path, bool removable) {
        if (path.isEmpty()) {
            return;
        }
        const QFileInfo info(path);
        // Existence AND readability: a shortcut that opens an empty pane reads as a
        // broken button, and /media/<user> only exists once something is mounted.
        if (!info.isDir() || !info.isReadable()) {
            return;
        }
        const QString absolute = QDir(path).absolutePath();
        for (const QVariant &existing : std::as_const(out)) {
            if (existing.toMap().value(QStringLiteral("path")).toString() == absolute) {
                return;  // /media and /media/<user> can collapse onto each other.
            }
        }
        QVariantMap entry;
        entry.insert(QStringLiteral("label"), label);
        entry.insert(QStringLiteral("path"), absolute);
        entry.insert(QStringLiteral("removable"), removable);
        out.append(entry);
    };

    add(QStringLiteral("Koti"), homePath(), false);
    add(QStringLiteral("Kuvat"),
        QStandardPaths::writableLocation(QStandardPaths::PicturesLocation), false);

    // Mounted removable volumes, by their own label — "PHOTOS" is what is printed
    // on the stick, and /media/pi/PHOTOS is not. Filtered to what is actually
    // ready: a volume that has gone away still lingers in the list briefly.
    for (const QStorageInfo &volume : QStorageInfo::mountedVolumes()) {
        if (!volume.isValid() || !volume.isReady() || volume.isRoot()) {
            continue;
        }
        const QString rootPath = volume.rootPath();
        if (!isRemovableMountPoint(rootPath)) {
            continue;
        }
        // Pseudo-filesystems mounted under those prefixes are plumbing, not media.
        // Measured on the WSL2 dev box, an unfiltered list offered /mnt/wsl,
        // /mnt/wslg, /mnt/wslg/doc and /mnt/wslg/run/user/1000 — five junk rows
        // above the drives anyone would actually be looking for.
        static const QSet<QByteArray> pseudoFilesystems = {
            "tmpfs", "devtmpfs", "overlay", "squashfs", "ramfs",
            "proc",  "sysfs",    "cgroup",  "cgroup2",  "devpts",
        };
        if (pseudoFilesystems.contains(volume.fileSystemType())) {
            continue;
        }
        // The volume's own label when it has one (a USB stick's "PHOTOS"),
        // otherwise the last path segment ("c" for /mnt/c). Deliberately NOT
        // displayName(), which falls back to the whole root path and would put
        // "/media/pi/PHOTOS" in a 200px-wide column.
        const QString label =
            volume.name().isEmpty() ? QFileInfo(rootPath).fileName() : volume.name();
        add(label.isEmpty() ? rootPath : label, rootPath, true);
    }

    add(QStringLiteral("Juurihakemisto"), QStringLiteral("/"), false);
    return out;
}

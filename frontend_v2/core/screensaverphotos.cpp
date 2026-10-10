#include "screensaverphotos.hh"

#include <QDir>
#include <QStandardPaths>

#include "dotenv.hh"
#include "logger.hh"

namespace {
const Logger logger = Logger::get("screensaver");

// Matched case-INSENSITIVELY by both consumers: QDir name filters are by
// default, and ScreenSaver.qml sets caseSensitive: false on its FolderListModel.
// Every camera writes DSC_0042.JPG in capitals, so a case-sensitive match would
// report an empty folder full of photos. usb_import_service copies the same list.
const QStringList kImageNameFilters = {
    QStringLiteral("*.jpg"),  QStringLiteral("*.jpeg"), QStringLiteral("*.png"),
    QStringLiteral("*.bmp"),  QStringLiteral("*.webp"), QStringLiteral("*.gif"),
};
}  // namespace

ScreensaverPhotos::ScreensaverPhotos(QObject *parent) : QObject(parent) {
    // Beside frontend_config.json and the backend's backend_config.json (see
    // defaultStoragePath in settings.cpp, and screensaver_dir() in
    // usb_import_service.py, which must resolve the same folder).
    m_path = QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation) +
             QStringLiteral("/Tesla-Homedash/screensaver");

    if (!QDir(m_path).exists()) {
        if (QDir().mkpath(m_path)) {
            logger.info(QStringLiteral("Created the screensaver photo folder %1").arg(m_path));
        } else {
            logger.warning(QStringLiteral("Could not create the screensaver photo folder %1")
                               .arg(m_path));
        }
    }
    // The folder used to be configurable; a deployment that still sets the old
    // variable would otherwise lose its photos without a word.
    if (dotenv::isSet("TESLA_HOMEDASH_SCREENSAVER_DIR")) {
        logger.warning(QStringLiteral("TESLA_HOMEDASH_SCREENSAVER_DIR is no longer read; "
                                      "copy the photos to %1")
                           .arg(m_path));
    }

    m_debounce.setSingleShot(true);
    m_debounce.setInterval(500);
    connect(&m_debounce, &QTimer::timeout, this, &ScreensaverPhotos::refresh);
    connect(&m_watcher, &QFileSystemWatcher::directoryChanged, &m_debounce,
            qOverload<>(&QTimer::start));

    refresh();
    logger.info(QStringLiteral("Screensaver photo folder: %1 (%2 photos)").arg(m_path).arg(m_count));
}

QStringList ScreensaverPhotos::imageNameFilters() const {
    return kImageNameFilters;
}

void ScreensaverPhotos::refresh() {
    const QDir dir(m_path);
    // QDir's defaults match FolderListModel's in ScreenSaver.qml: no hidden
    // files (the import's ".name.part" files among them), no subfolders.
    const int count = dir.exists() ? dir.entryList(kImageNameFilters, QDir::Files).size() : 0;

    // A watched folder that is deleted drops out of the watcher; re-arm whenever
    // it is there.
    if (dir.exists() && !m_watcher.directories().contains(m_path)) {
        m_watcher.addPath(m_path);
    }

    if (count != m_count) {
        m_count = count;
        emit changed();
    }
}

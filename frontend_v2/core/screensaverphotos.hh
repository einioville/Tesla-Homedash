#ifndef FRONTEND_V2_SCREENSAVERPHOTOS_HH
#define FRONTEND_V2_SCREENSAVERPHOTOS_HH

#include <QFileSystemWatcher>
#include <QObject>
#include <QString>
#include <QStringList>
#include <QTimer>
#include <QUrl>

/**
 * ScreensaverPhotos — the screensaver's photo folder: where it is and how many
 * photos it holds.
 *
 * Registered with the QML engine as the singleton `Photos`.
 *
 * The folder is FIXED at `<GenericConfigLocation>/Tesla-Homedash/screensaver`
 * (~/.config/Tesla-Homedash/screensaver), beside frontend_config.json, and is
 * created at startup. Photos arrive over scp or through the Options view's USB
 * import, which the BACKEND runs (usb_import_service) — it resolves the same path,
 * which is why neither side lets it be configured.
 *
 * ScreenSaver.qml lists and plays the folder with its own FolderListModel. This
 * class exists for what that model cannot give the Options view: a count that is
 * right before the screensaver has ever run. It watches the folder, so photos
 * copied in while the app runs — an import in progress included — are counted
 * without a restart.
 */
class ScreensaverPhotos : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString path READ path CONSTANT)
    // For FolderListModel.folder, which takes a URL.
    Q_PROPERTY(QUrl url READ url CONSTANT)
    Q_PROPERTY(int count READ count NOTIFY changed)
    // The extensions the screensaver plays. CONSTANT: read by both ScreenSaver.qml
    // and the count here, so the Options view cannot vouch for a folder the
    // screensaver renders as empty.
    Q_PROPERTY(QStringList imageNameFilters READ imageNameFilters CONSTANT)

public:
    explicit ScreensaverPhotos(QObject *parent = nullptr);

    QString path() const { return m_path; }
    QUrl url() const { return QUrl::fromLocalFile(m_path); }
    int count() const { return m_count; }
    QStringList imageNameFilters() const;

    // Recounts now. The watcher covers changes inside the folder; this covers the
    // folder itself being deleted and made again, so the Options view calls it
    // when the row is built.
    Q_INVOKABLE void refresh();

signals:
    void changed();

private:
    QString m_path;
    int m_count = 0;
    QFileSystemWatcher m_watcher;
    // Copying a few hundred photos fires a directoryChanged per file; recount
    // once when it settles instead.
    QTimer m_debounce;
};

#endif  // FRONTEND_V2_SCREENSAVERPHOTOS_HH

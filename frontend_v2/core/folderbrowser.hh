#ifndef FRONTEND_V2_FOLDERBROWSER_HH
#define FRONTEND_V2_FOLDERBROWSER_HH

#include <QObject>
#include <QString>
#include <QStringList>
#include <QVariantList>
#include <QVariantMap>

/**
 * FolderBrowser — the filesystem facts the Options view's folder picker needs and
 * QML cannot answer for itself.
 *
 * Registered with the QML engine as the singleton `Folders`.
 *
 * The picker's list of directories comes from a FolderListModel, which is a fine
 * lister and a poor navigator: it can only tell you what is INSIDE a directory it
 * has already opened. Everything a picker needs BEFORE that — does this path still
 * exist, may we read it, what is its parent, where should we open when nothing is
 * configured, which removable volumes are mounted right now — has no QML type in
 * this build at all. Qt.labs.platform (which would bring StandardPaths) is not
 * linked, QStorageInfo has no QML API in any build, and probing a candidate
 * directory by pointing a FolderListModel at it would spawn a QThread per probe.
 *
 * So this class is small on purpose: it answers questions, holds no state, and
 * every method recomputes. That last part is load-bearing rather than lazy — a USB
 * stick can be plugged in, or pulled, while the Options view sits open, so a
 * shortcut list cached at construction would be wrong exactly when it matters.
 *
 * It also owns `imageNameFilters`, the one list of image extensions the screensaver
 * plays. That lived as a literal in ScreenSaver.qml; the picker has to count images
 * with the SAME filter or its "42 kuvaa" would describe a folder the screensaver
 * renders as empty — recreating, with more confidence, the silent no-op the picker
 * exists to end.
 */
class FolderBrowser : public QObject {
    Q_OBJECT
    // The extensions the screensaver plays. CONSTANT: a compiled-in list, read by
    // both ScreenSaver.qml and the picker's image counter so the two cannot drift.
    Q_PROPERTY(QStringList imageNameFilters READ imageNameFilters CONSTANT)

public:
    explicit FolderBrowser(QObject *parent = nullptr);

    QStringList imageNameFilters() const;

    // Everything the UI needs to know about one path, in one call so a QML binding
    // makes a single trip: {path, name, exists, readable, isDir, browsable, parent,
    // hasParent}. An empty or blank path answers exists=false rather than throwing,
    // because it is the legitimate "no folder configured" value of the setting.
    Q_INVOKABLE QVariantMap describe(const QString &path) const;

    // Where to open the dialog: the saved value when it is still usable, else the
    // user's Pictures folder, else home, else "/". Never returns an unusable path,
    // which is what keeps a FolderListModel from silently falling back to the
    // process's working directory (see the note on componentComplete in the .cpp).
    Q_INVOKABLE QString startFolder(const QString &saved) const;

    // The parent directory, or an empty string AT THE ROOT. Deliberately not
    // FolderListModel.parentFolder: that returns an empty URL at "/", and feeding
    // an empty URL back into `folder` leaves the model pointing nowhere with no way
    // to recover on a device that has no keyboard.
    Q_INVOKABLE QString parentOf(const QString &path) const;

    // The path split into cumulative crumbs, root first: [{label, path}, ...].
    // "/home/pi/kuvat" -> [{"/", "/"}, {"home", "/home"}, {"pi", "/home/pi"},
    // {"kuvat", "/home/pi/kuvat"}].
    Q_INVOKABLE QVariantList crumbs(const QString &path) const;

    // Jump targets that exist on THIS host right now: [{label, path, removable}].
    // Filtered by existence — a shortcut leading nowhere reads as a broken button,
    // and /media/<user> does not exist until the first stick is mounted.
    Q_INVOKABLE QVariantList shortcuts() const;

    // True when FolderListModel can actually open this path. It re-parses the
    // decoded local path as a URL internally, so a directory whose name contains
    // '#', '?' or a '%' sequence is silently truncated to something else. Such a
    // folder can be listed by its parent but never entered — and, more to the
    // point, never PLAYED by the screensaver, which uses the same model. Better to
    // mark it than to let the user pick a folder that will quietly stay dark.
    //
    // Separate from describe() rather than just a field of it because the browser
    // asks this question once per VISIBLE ROW, re-evaluated on every flick: this
    // is a pure string parse and touches the filesystem not at all, where
    // describe() stats.
    Q_INVOKABLE static bool isBrowsable(const QString &path);
};

#endif  // FRONTEND_V2_FOLDERBROWSER_HH

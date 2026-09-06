import QtQuick
import QtQuick.Controls
import Qt.labs.folderlistmodel
import frontend_v2

// The folder browser, as a modal over the Options view.
//
// Sibling of SpotifyDevicePopup and built the same way, for the same reason: a
// folder is only ever picked from a settings row a few pixels above, so the dialog
// belongs to this screen and darkens only this screen.
//
// ONE RULE governs the whole dialog: tapping anything — a directory row, a
// shortcut, a breadcrumb crumb — only changes WHERE YOU ARE. Nothing is ever
// "selected"; the button at the bottom writes, and what it writes is always the
// folder named in the breadcrumb. That removes the classic touch file-picker
// failure of tap-to-select vs. double-tap-to-open (a double tap is a poor touch
// idiom, and a tap that both navigates AND changes a stored value is
// unrecoverable by mis-tap). It also means a leaf folder with no subdirectories —
// DCIM/100CANON, the overwhelmingly common case — is selectable at all, which a
// select-the-row design cannot do.
//
// Deliberately NOT a QtQuick.Controls Popup: those render inside QQuickOverlay at
// a z far above this window's own layers, so one left open when the idle timeout
// fired would sit on top of the SCREENSAVER (z:300).
//
// Deliberately NOT hosted in a Loader either, which is the tempting way to avoid
// holding FolderListModels open for the life of the process. ~FileInfoThread takes
// the thread's mutex and wait()s for it, and the scan holds that mutex for the
// whole of its directory walk — so unloading mid-scan blocks the GUI THREAD until
// the walk finishes. A stale network mount or a spun-down USB disk turns that into
// a frozen dashboard, and "Peruuta during a slow load" is exactly when a user
// taps. The cost of the alternative is one listing of the process's working
// directory at startup (FolderListModel falls back to it when `folder` is empty at
// component completion) plus one idle QFileSystemWatcher. That is the cheaper bad
// option by a wide margin.
Item {
    id: popup

    // The setting being edited. Empty means closed — one property, so there is no
    // way for "which key" and "is it open" to disagree.
    property string settingKey: ""
    // The folder the browser is standing in. The SINGLE source of truth for
    // navigation, held as a plain path: FolderListModel's own `folder` and
    // `parentFolder` are URLs, and deriving a path back out of one by stripping
    // "file://" corrupts every name containing a space or a non-ASCII character.
    property string currentPath: ""

    anchors.fill: parent
    visible: settingKey.length > 0
    // Above the device popup, so the two can never fight over the same screen.
    z: 110

    function open(key, path) {
        // Resolve in C++ BEFORE the model sees anything: startFolder() never
        // returns a path that cannot be opened, which is what stops
        // FolderListModel from silently falling back to the working directory
        // when the saved value is empty or its stick has been pulled.
        popup.currentPath = Folders.startFolder(path)
        popup.settingKey = key
        popup.refreshShortcuts()
    }

    function close() {
        popup.settingKey = ""
        // Also drop the folder, which releases the two models' QFileSystemWatcher
        // handles — otherwise the last directory browsed stays watched for the
        // life of the process, and on a USB stick that also keeps the mount busy.
        // Safe to clear at RUNTIME: the working-directory fallback only happens at
        // component completion, so this leaves the models genuinely empty. open()
        // sets the path before the key, so reopening never flashes the empty state.
        popup.currentPath = ""
    }

    function navigate(path) {
        if (path.length > 0 && Folders.isBrowsable(path))
            popup.currentPath = path
    }

    // Recomputed on open rather than bound: a stick plugged in while the Options
    // view sits idle must appear, and QStorageInfo has no change notification.
    property var shortcutList: []
    function refreshShortcuts() {
        popup.shortcutList = Folders.shortcuts()
    }

    readonly property var info: Folders.describe(popup.currentPath)
    // Resolved once per navigation rather than per breadcrumb delegate: the
    // Repeater's model and each delegate's "am I the last one" test would
    // otherwise both call into C++, twice for every crumb on screen.
    readonly property var crumbList: Folders.crumbs(popup.currentPath)

    // Debounced, because each change costs a full stat walk of the directory on a
    // worker thread: walking four crumbs quickly should queue one count, not four.
    property string countPath: ""
    onCurrentPathChanged: countSettle.restart()
    Timer {
        id: countSettle
        interval: 250
        onTriggered: popup.countPath = popup.currentPath
    }

    // Swallows every tap that misses the card, so the settings underneath cannot be
    // operated while the dialog is up. No dismiss-on-scrim: a stray palm on a 10"
    // panel must not discard a browse in progress.
    MouseArea {
        anchors.fill: parent
        preventStealing: true
        onClicked: {}
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.dialogScrim
    }

    // Directories only. showDotAndDotDot stays false — ".." as a list row is a
    // desktop idiom, and the breadcrumb above is both the display and the way up.
    // showOnlyReadable means the list never offers a folder that cannot be entered.
    FolderListModel {
        id: dirModel
        folder: Settings.toFileUrl(popup.currentPath)
        showDirs: true
        showFiles: false
        showDotAndDotDot: false
        showHidden: false
        showOnlyReadable: true
        sortField: FolderListModel.Name
        sortCaseSensitive: false
    }

    // The image count for the folder the user is standing in — the single most
    // useful thing this dialog can say, because an empty folder is precisely the
    // case where the screensaver silently never starts.
    //
    // The filter comes from the Folders singleton rather than being restated here:
    // if it drifted from what ScreenSaver.qml plays, this count would confidently
    // report "42 kuvaa" for a folder the screensaver renders as empty — the exact
    // silent failure the dialog exists to end. caseSensitive:false is part of that
    // contract (cameras write DSC_0042.JPG).
    FolderListModel {
        id: imageModel
        folder: Settings.toFileUrl(popup.countPath)
        showDirs: false
        showFiles: true
        showHidden: false
        caseSensitive: false
        nameFilters: Folders.imageNameFilters
    }

    // The bottom band the DOCK occupies when it is revealed. Reserving it is not
    // cosmetic: the dock lives in Main.qml and is declared AFTER the view host, so
    // it floats over this dialog no matter what `z` is set here — z only orders
    // siblings within SettingsView, and the scrim's tap-swallowing MouseArea is
    // likewise powerless against an item in a higher layer. The dock can be swiped
    // up at any moment (its reveal handler is above the views too) and it is
    // briefly on screen at startup, so a card whose buttons reached into this band
    // would have *Peruuta* and *Valitse tämä kansio* covered with no way to reach
    // them. Measured on the 1280x800 target: a 96px bar sitting 2 x gridMargin
    // clear of the bottom edge, i.e. y 684..780 against a button row that would
    // otherwise land at 681..725.
    readonly property int dockBand: 96 + 2 * Theme.gridMargin

    Rectangle {
        id: card
        // Top-anchored rather than centred, so the reserved band below is actually
        // reserved: centring a shorter card would just re-centre it and put the
        // buttons back down there.
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: Theme.gridMargin
        width: Math.min(parent.width - 2 * Theme.gridMargin, 880)
        height: Math.min(parent.height - 2 * Theme.gridMargin - popup.dockBand, 690)
        radius: Theme.tripCardRadius
        // The repo's OPAQUE popup token. A translucent card over the blurred
        // settings screen would smear that backdrop into its own directory names.
        color: Theme.tripComboPopupBg
        border.width: 1
        border.color: Theme.tripCardBorder

        // --- Title ---------------------------------------------------------
        Text {
            id: title
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 22
            height: 26
            text: qsTr("Valitse kuvakansio")
            font.family: Theme.fontFamily
            font.pixelSize: 19
            font.bold: true
            color: Theme.dataLabelValue
            elide: Text.ElideRight
        }

        // --- Path bar: up button + breadcrumb -------------------------------
        Item {
            id: pathBar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: title.bottom
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            anchors.topMargin: 14
            height: 44

            // Fixed at the left so the most-used control in the dialog never
            // moves under a finger. Disabled at the root rather than hidden, for
            // the same reason.
            Rectangle {
                id: upButton
                width: 62
                height: parent.height
                radius: 8
                color: upTap.pressed ? Theme.tripComboPressed : Theme.tripComboBg
                border.width: 1
                border.color: Theme.tripCardBorder
                enabled: popup.info.hasParent
                opacity: enabled ? 1.0 : 0.35

                TintedIcon {
                    anchors.centerIn: parent
                    iconSize: 18
                    // The dashboard has no "up" glyph; the left arrow is the
                    // nearest honest one and reads correctly beside a breadcrumb.
                    source: "qrc:/resources/icons/arrow_left.svg"
                    tint: Theme.dataLabelValue
                }

                MouseArea {
                    id: upTap
                    anchors.fill: parent
                    // parentOf() returns "" at the filesystem root, and navigate()
                    // ignores that. Never FolderListModel.parentFolder, which
                    // yields an empty URL at "/" — feeding that back into `folder`
                    // strands the model with no way to re-seed it on a device
                    // that has no keyboard.
                    onClicked: popup.navigate(popup.info.parent)
                }
            }

            // Horizontally flickable so a deep path stays reachable without ever
            // eliding the part that says where you are. Every crumb is a 44px-tall
            // jump target, which turns "up three levels" into one tap.
            Flickable {
                id: crumbFlick
                anchors.left: upButton.right
                anchors.leftMargin: 8
                anchors.right: parent.right
                height: parent.height
                contentWidth: crumbRow.width
                flickableDirection: Flickable.HorizontalFlick
                boundsBehavior: Flickable.StopAtBounds
                clip: true

                // Keep the DEEPEST crumb visible: that is the folder the confirm
                // button will write, so it must never be the one scrolled off.
                function scrollToEnd() {
                    crumbFlick.contentX = Math.max(0, crumbFlick.contentWidth - crumbFlick.width)
                }
                Connections {
                    target: popup
                    function onCurrentPathChanged() { Qt.callLater(crumbFlick.scrollToEnd) }
                }

                Row {
                    id: crumbRow
                    height: crumbFlick.height
                    spacing: 2

                    Repeater {
                        model: popup.crumbList

                        Row {
                            id: crumbEntry
                            required property int index
                            required property var modelData

                            readonly property bool isLast:
                                index === popup.crumbList.length - 1

                            height: crumbRow.height
                            spacing: 2

                            Text {
                                visible: crumbEntry.index > 0
                                anchors.verticalCenter: parent.verticalCenter
                                text: "›"
                                font.family: Theme.fontFamily
                                font.pixelSize: 15
                                color: Theme.dataLabelTitle
                            }

                            Rectangle {
                                height: crumbRow.height
                                // A minimum width so a one-character segment ("/",
                                // "v") is still a reliable target.
                                width: Math.max(52, crumbLabel.implicitWidth + 26)
                                radius: 8
                                color: crumbTap.pressed ? Theme.tripComboPressed
                                     : crumbEntry.isLast ? Theme.tripComboHover
                                     : "transparent"

                                Text {
                                    id: crumbLabel
                                    anchors.centerIn: parent
                                    text: crumbEntry.modelData.label
                                    font.family: Theme.fontFamily
                                    font.pixelSize: 14
                                    color: crumbEntry.isLast ? Theme.dataLabelValue
                                                             : Theme.dataLabelTitle
                                }

                                MouseArea {
                                    id: crumbTap
                                    anchors.fill: parent
                                    onClicked: popup.navigate(crumbEntry.modelData.path)
                                }
                            }
                        }
                    }
                }
            }
        }

        // --- Body: shortcuts | directory list -------------------------------
        Item {
            id: body
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: pathBar.bottom
            anchors.bottom: statusLine.top
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            anchors.topMargin: 12
            anchors.bottomMargin: 10

            // A COLUMN, not a row of chips across the top: the column spends 200px
            // of width (the list still gets ~600px, far more than any folder name
            // needs) where a chip row would spend ~56px of height — one whole
            // directory row out of eight. Height is the scarce axis here.
            ListView {
                id: shortcuts
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 200
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: popup.shortcutList
                header: Text {
                    height: 26
                    text: qsTr("Pikavalinnat")
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    color: Theme.dataLabelTitle
                }

                delegate: Rectangle {
                    id: shortcutRow
                    required property var modelData

                    width: shortcuts.width
                    height: 48
                    radius: 8
                    readonly property bool here: popup.currentPath === modelData.path
                    color: shortcutTap.pressed ? Theme.tripComboPressed
                         : here ? Theme.tripComboHover : "transparent"

                    TintedIcon {
                        id: shortcutIcon
                        anchors.left: parent.left
                        anchors.leftMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        iconSize: 16
                        source: shortcutRow.modelData.removable
                                ? "qrc:/resources/icons/link.svg"
                                : "qrc:/resources/icons/folder.svg"
                        tint: Theme.dataLabelTitle
                    }

                    Text {
                        anchors.left: shortcutIcon.right
                        anchors.leftMargin: 8
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        text: shortcutRow.modelData.label
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                        color: Theme.dataLabelValue
                        elide: Text.ElideMiddle
                    }

                    MouseArea {
                        id: shortcutTap
                        anchors.fill: parent
                        onClicked: popup.navigate(shortcutRow.modelData.path)
                    }
                }
            }

            Rectangle {
                id: bodyRule
                anchors.left: shortcuts.right
                anchors.leftMargin: 10
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 1
                color: "#1affffff"
            }

            ListView {
                id: dirList
                anchors.left: bodyRule.right
                anchors.leftMargin: 10
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                // ~2 screens, so a fast flick through a big /usr/share does not
                // churn delegates.
                cacheBuffer: 560
                model: dirModel
                // A ScrollIndicator, not a ScrollBar. SettingsPane bans scroll bars
                // as mouse chrome, but the real distinction is interactive control
                // vs. non-interactive feedback, and a 200-entry directory needs the
                // feedback — TripComboBox's popup already carries one.
                ScrollIndicator.vertical: ScrollIndicator {}

                delegate: Rectangle {
                    id: dirRow
                    required property string fileName
                    required property string filePath

                    // 56px = 9.4mm on this 151ppi panel, comfortably past the 9mm
                    // reliable-touch figure, and the same floor SettingRow uses.
                    width: dirList.width
                    height: 56
                    color: dirTap.pressed ? Theme.tripComboHover : "transparent"

                    // A directory whose name contains '#', '%' or '?' cannot be
                    // opened by FolderListModel at all — it re-parses the path as a
                    // URL internally and truncates at the first such character. It
                    // is shown but inert, because letting the user tap into an
                    // apparently-empty folder they could then SELECT would persist
                    // a path the screensaver cannot play either.
                    readonly property bool usable: Folders.isBrowsable(dirRow.filePath)
                    opacity: usable ? 1.0 : 0.4

                    TintedIcon {
                        id: rowIcon
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        iconSize: 18
                        source: "qrc:/resources/icons/folder.svg"
                        tint: Theme.dataLabelTitle
                    }

                    Text {
                        anchors.left: rowIcon.right
                        anchors.leftMargin: 12
                        anchors.right: rowChevron.left
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        // filePath is used for navigation, but fileName is what is
                        // shown — a plain, already-decoded name straight from
                        // QFileInfo.
                        text: dirRow.fileName
                        font.family: Theme.fontFamily
                        font.pixelSize: 15
                        color: Theme.dataLabelValue
                        elide: Text.ElideRight
                    }

                    TintedIcon {
                        id: rowChevron
                        anchors.right: parent.right
                        anchors.rightMargin: 14
                        anchors.verticalCenter: parent.verticalCenter
                        visible: dirRow.usable
                        iconSize: 14
                        source: "qrc:/resources/icons/arrow_right.svg"
                        tint: Theme.dataLabelTitle
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        height: 1
                        color: "#14ffffff"
                    }

                    MouseArea {
                        id: dirTap
                        anchors.fill: parent
                        enabled: dirRow.usable
                        // filePath, NOT fileUrl: the role is already an absolute,
                        // decoded path, so no URL ever enters the navigation state.
                        onClicked: popup.navigate(dirRow.filePath)
                    }
                }

                // Three outcomes look identical from the model alone (status Ready,
                // count 0), so the reason comes from C++ rather than being guessed.
                Text {
                    anchors.centerIn: parent
                    width: parent.width - 40
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    visible: dirList.count === 0
                             && dirModel.status !== FolderListModel.Loading
                    text: !popup.info.exists ? qsTr("Kansiota ei löydy")
                        : !popup.info.readable ? qsTr("Ei lukuoikeutta tähän kansioon")
                        : qsTr("Ei alikansioita")
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: Theme.dataLabelTitle
                }
            }
        }

        // --- Status line ----------------------------------------------------
        // Height reserved unconditionally: a line that appeared and disappeared
        // would shift the button row below it vertically, under a finger already
        // on its way down.
        Text {
            id: statusLine
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: buttonRow.top
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            anchors.bottomMargin: 10
            height: 20
            verticalAlignment: Text.AlignVCenter
            font.family: Theme.fontFamily
            font.pixelSize: 12
            elide: Text.ElideRight
            // Gated on the model's STATUS, not on count alone: count is 0 while the
            // background walk is still running, so a naive binding flashes the
            // amber "no images here" warning on every single descend — including
            // into folders that turn out to be full.
            readonly property bool counting: imageModel.status === FolderListModel.Loading
                                             || popup.countPath !== popup.currentPath
            readonly property bool empty: !counting && imageModel.count === 0
            color: empty ? "#ffd48a" : Theme.dataLabelTitle
            text: {
                if (!popup.info.exists)
                    return ""
                if (statusLine.counting)
                    return qsTr("Lasketaan kuvia…")
                if (imageModel.count === 0)
                    return "⚠ " + qsTr("Tässä kansiossa ei ole kuvia — näytönsäästäjä ei käynnisty")
                if (imageModel.count === 1)
                    return qsTr("1 kuva tässä kansiossa")
                return qsTr("%1 kuvaa tässä kansiossa").arg(imageModel.count)
            }
        }

        // --- Buttons --------------------------------------------------------
        Item {
            id: buttonRow
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            anchors.bottomMargin: 20
            height: 44

            // Left-anchored and alone, so its visibility can never shift the pair
            // on the right. Clearing is a real operation, not a tidy-up: empty
            // means "no folder configured, screensaver off", which is genuinely
            // different from a folder that happens to hold no photos — and with
            // the text field gone this is the only way back to unconfigured.
            DialogButton {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                height: parent.height
                // valuesRevision is read to make this live: valueOf is an
                // invokable and registers no property dependency of its own, so
                // without it the button would keep the visibility it happened to
                // have when the dialog opened.
                visible: {
                    const revision = Settings.valuesRevision
                    if (popup.settingKey.length === 0)
                        return false
                    const saved = Settings.valueOf(popup.settingKey)
                    return saved !== undefined && saved !== null && String(saved).length > 0
                }
                label: qsTr("Tyhjennä")
                onActivated: {
                    Settings.setValue(popup.settingKey, "")
                    popup.close()
                }
            }

            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10

                DialogButton {
                    height: buttonRow.height
                    label: qsTr("Peruuta")
                    onActivated: popup.close()
                }

                // Fixed label and fixed width. "Valitse: Kesäloma" would resize as
                // the user navigates, sliding "Peruuta" sideways under a finger
                // already reaching for it — the mis-tap SpotifyDevicePopup
                // documents and designs around. Which folder it means is answered
                // by the breadcrumb, permanently, at the top of the dialog.
                DialogButton {
                    id: confirm
                    width: 214
                    height: buttonRow.height
                    // The ENABLED state follows popup.info, which re-resolves on
                    // navigation. That is not enough on its own: nothing notifies
                    // QML when a stick is unmounted, so a folder that went away
                    // while the dialog sat open still looks pickable. The handler
                    // therefore re-stats at TAP time and refuses, rather than
                    // persisting a path that would send the screensaver quietly
                    // dark. Both are needed — the binding greys the button in the
                    // cases it can see, the re-stat catches the rest.
                    readonly property bool canPick: popup.info.exists && popup.info.isDir
                                                    && popup.info.readable
                                                    && popup.info.browsable
                    enabled: canPick
                    opacity: canPick ? 1.0 : 0.4
                    label: qsTr("Valitse tämä kansio")
                    onActivated: {
                        const fresh = Folders.describe(popup.currentPath)
                        if (!fresh.exists || !fresh.isDir || !fresh.readable
                                || !fresh.browsable)
                            return
                        // A plain QString path. setValue's coercion requires a
                        // string for a "string" setting and rejects a QUrl
                        // outright, so anything derived from a model's fileUrl
                        // role would fail the write with a toast and no folder.
                        Settings.setValue(popup.settingKey, popup.currentPath)
                        popup.close()
                    }
                }
            }
        }
    }
}

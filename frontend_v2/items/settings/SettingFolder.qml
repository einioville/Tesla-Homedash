import QtQuick
import frontend_v2

// Folder editor: a tappable value button that opens the folder browser, used for
// a string setting carrying `editor: "folder"`.
//
// It replaces the text field rather than sitting beside one, and that is the whole
// point of the feature. On the deployed panel the dashboard runs FULLSCREEN, and
// squeekboard is hardcoded to labwc's `top` layer and does not draw over a
// fullscreen surface (labwc#2926) — the same limitation that makes Main.qml step
// back to windowed for a Spotify re-authorization. So the field this replaces
// could be focused on the device but never typed into.
//
// The obvious counter-argument — keep the field as an escape hatch for a folder
// the browser cannot reach — does not survive contact with the facts: the only
// folders the browser cannot enter are those whose names contain '#', '%' or '?',
// and FolderListModel cannot open those either, so ScreenSaver.qml could not PLAY
// such a folder however its path was entered. A field that can only produce
// unusable values is not an escape hatch. (The view's footer still names the
// settings file for genuine hand-editing.)
Item {
    id: control

    required property var setting

    implicitWidth: 240
    // Taller than the 36px text field it replaces: this is the row's primary
    // touch target now, not a field you tab into. SettingRow's own
    // `Math.max(56, ...)` floor means nothing reflows.
    implicitHeight: 44

    readonly property string currentPath: {
        const value = control.setting.value
        return value === undefined || value === null ? "" : String(value)
    }

    // Folders is a C++ singleton because none of this is answerable from QML:
    // FolderListModel can only report what is inside a directory it has already
    // opened, and there is no QML type here for "does this path still exist".
    // valuesRevision makes the binding live — describe() is an invokable, so it
    // registers no property dependency of its own (the same trap Settings.valueOf
    // documents).
    readonly property var info: {
        const revision = Settings.valuesRevision
        return Folders.describe(control.currentPath)
    }

    // A saved folder that has gone away — the USB stick was pulled — is the case
    // worth shouting about: the screensaver then just silently stops working, with
    // the toggle still on and a plausible-looking path still in the row.
    readonly property bool missing: currentPath.length > 0 && !info.exists
    readonly property bool unusable: currentPath.length > 0 && info.exists
                                     && (!info.readable || !info.browsable)
    readonly property bool warned: missing || unusable

    Rectangle {
        id: field
        anchors.fill: parent
        radius: 8
        // The field styling of SettingText, so the row still reads as an editor
        // rather than as a stray button that wandered in.
        color: tap.pressed ? Theme.tripComboPressed : Theme.tripComboBg
        border.width: 1
        border.color: control.warned ? "#80ffb020" : Theme.tripCardBorder

        TintedIcon {
            id: leadIcon
            anchors.left: parent.left
            anchors.leftMargin: 11
            anchors.verticalCenter: parent.verticalCenter
            iconSize: 17
            source: "qrc:/resources/icons/folder.svg"
            tint: control.warned ? "#ffd48a"
                 : control.currentPath.length > 0 ? Theme.dataLabelValue
                 : Theme.dataLabelTitle
        }

        Text {
            id: pathText
            anchors.left: leadIcon.right
            anchors.leftMargin: 9
            anchors.right: chevron.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            // ElideMiddle, not ElideRight: the HEAD of the path is what says which
            // volume this is (/media/… the stick vs /home/… the SD card), and the
            // TAIL is the folder's own name. Both matter; the middle does not.
            // Same choice the view's footer makes for the settings file paths.
            elide: Text.ElideMiddle
            font.family: Theme.fontFamily
            font.pixelSize: 14
            text: control.currentPath.length > 0
                  ? control.currentPath
                  : qsTr("Valitse kansio…")
            color: control.warned ? "#ffd48a"
                 : control.currentPath.length > 0 ? Theme.dataLabelValue
                 : Theme.dataLabelTitle
        }

        // The language-free "this opens something" cue. Reuses the existing arrow
        // asset rather than adding a chevron.
        TintedIcon {
            id: chevron
            anchors.right: parent.right
            anchors.rightMargin: 11
            anchors.verticalCenter: parent.verticalCenter
            iconSize: 14
            source: "qrc:/resources/icons/arrow_right.svg"
            tint: Theme.dataLabelTitle
        }

        MouseArea {
            id: tap
            anchors.fill: parent
            onClicked: Settings.requestFolderPick(control.setting.key)
        }
    }
}

import QtQuick
import frontend_v2

// The Lokitaso row's details: while it is at DEBUG, when it returns, to which
// level, and how long that is from now — or that it stays (toistaiseksi). Both come from the backend
// (`setting.runtime.until` / `.returnTo`, from LogLevel), because the countdown
// restarts with the backend process and only it knows when that was. Styled as
// the warning text the row's state is: DEBUG left on is the thing to notice.
// An Item around the line, collapsing to no height while there is nothing to say:
// an empty Text keeps a line's height and pushed the row's label up.
Item {
    id: details

    required property var setting

    readonly property real until: setting.value === "debug" && setting.runtime !== undefined
                                  && setting.runtime.until !== undefined ? setting.runtime.until : 0
    readonly property string returnTo: until > 0 && setting.runtime.returnTo !== undefined
                                       ? String(setting.runtime.returnTo).toUpperCase() : ""
    readonly property bool indefinite: setting.value === "debug" && setting.runtime !== undefined
                                       && setting.runtime.indefinite === true
    readonly property bool shown: until > 0 || indefinite

    // Re-read every half minute so "vielä N min" counts down on a panel left here.
    property real now: Date.now()

    Timer {
        interval: 30000
        repeat: true
        running: details.until > 0
        onTriggered: details.now = Date.now()
    }

    implicitHeight: shown ? line.implicitHeight : 0

    Text {
        id: line
        width: parent.width
        visible: details.shown
        wrapMode: Text.WordWrap
        font.family: Theme.fontFamily
        font.pixelSize: 12
        color: "#ffd48a"
        text: {
            if (details.indefinite)
                return qsTr("Päällä toistaiseksi, kunnes taso vaihdetaan")
            if (details.until <= 0)
                return ""
            const minutes = Math.max(1, Math.round((details.until - details.now) / 60000))
            const left = minutes < 60 ? minutes + " min"
                                      : Math.floor(minutes / 60) + " h " + (minutes % 60) + " min"
            return qsTr("Palautuu tasolle %1 klo %2 (vielä %3)")
                   .arg(details.returnTo).arg(Qt.formatTime(new Date(details.until), "hh:mm")).arg(left)
        }
    }
}

import QtQuick
import QtQuick.Controls
import frontend_v2

// Boolean editor: a touch-sized custom switch.
//
// Hand-drawn rather than a styled Qt Quick Controls Switch because the Basic
// style's indicator is small for a 10" finger target and its palette fights the
// dark theme — the same reason TripComboBox restyles ComboBox wholesale.
Item {
    id: control

    required property var setting

    // The authoritative value from the schema; a write round-trips through
    // Settings (and, for backend keys, the server) rather than being held here.
    readonly property bool checked: setting.value === true

    implicitWidth: 56
    implicitHeight: 30

    Rectangle {
        id: track
        anchors.centerIn: parent
        width: 52
        height: 28
        radius: height / 2
        color: control.checked ? Theme.accent : Theme.tripComboBg
        border.width: 1
        border.color: control.checked ? Theme.accent : Theme.tripCardBorder

        Behavior on color {
            ColorAnimation { duration: Theme.pressDuration }
        }

        Rectangle {
            id: knob
            width: 22
            height: 22
            radius: height / 2
            color: Theme.dataLabelValue
            anchors.verticalCenter: parent.verticalCenter
            x: control.checked ? track.width - width - 3 : 3

            Behavior on x {
                NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        onClicked: Settings.setValue(control.setting.key, !control.checked)
    }
}

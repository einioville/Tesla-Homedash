import QtQuick
import QtQuick.Controls
import frontend_v2

// Action editor: a button, for schema entries of type "action".
//
// Actions are not values — nothing is stored, persisted or sent as CONFIG_SET.
// They live in the schema purely so the sidebar/pane render them like anything
// else, which is what lets "restart the dashboard" sit in a settings section
// instead of being a bespoke widget bolted onto the view.
//
// A tap ARMS the button and a second tap within `confirmMs` runs it; the arming
// lapses on its own. That is deliberately not a modal dialog: this runs on a 10"
// touch panel where a stray palm on "restart the dashboard" is a real risk, but a
// dialog needs somewhere to put a Cancel button and something to dismiss it with.
Item {
    id: control

    required property var setting

    // How long an armed button stays armed before lapsing back.
    readonly property int confirmMs: 4000
    // Whether the action needs a live backend (the backend restart does).
    readonly property bool needsConnection: setting.requiresConnection === true
    readonly property bool available: !needsConnection || Server.connected

    property bool armed: false

    implicitWidth: 240
    implicitHeight: 38

    Timer {
        id: disarm
        interval: control.confirmMs
        onTriggered: control.armed = false
    }

    Rectangle {
        id: button
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(160, buttonLabel.implicitWidth + 32)
        height: parent.height
        radius: 8
        opacity: control.available ? 1.0 : 0.4

        // Armed state borrows the restart banner's amber so the two read as the
        // same "this is disruptive" language.
        color: !control.armed
               ? (tap.pressed ? Theme.tripComboPressed : Theme.tripComboBg)
               : (tap.pressed ? "#ccffb020" : "#99ffb020")
        border.width: 1
        border.color: control.armed ? "#80ffb020" : Theme.tripCardBorder

        Behavior on color {
            ColorAnimation { duration: Theme.pressDuration }
        }

        Text {
            id: buttonLabel
            anchors.centerIn: parent
            text: control.armed
                  ? qsTr("Vahvista")
                  : (control.setting.actionLabel !== undefined
                     ? control.setting.actionLabel : qsTr("Suorita"))
            font.family: Theme.fontFamily
            font.pixelSize: 14
            color: control.armed ? "#1a1206" : Theme.dataLabelValue
        }

        MouseArea {
            id: tap
            anchors.fill: parent
            enabled: control.available
            onClicked: {
                if (control.armed) {
                    control.armed = false
                    disarm.stop()
                    Settings.invokeAction(control.setting.key)
                } else {
                    control.armed = true
                    disarm.restart()
                }
            }
        }
    }
}

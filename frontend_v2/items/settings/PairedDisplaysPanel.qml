import QtQuick
import frontend_v2
import "../../app/Format.js" as Format

// Ylläpito › Näytöt (issue #64): every display that has logged in to the
// backend, connected or not, each with a button that revokes its login. Revoking
// closes that display's connection at once and it asks for the password again —
// this display included, which is how to log it out.
//
// Rendered as the backend subsection's `status` widget, above its lifetime row.
// The rows are the backend's AUTH_DISPLAYS list (PairedDisplays), re-broadcast
// after any change, so a display connecting or leaving updates them live.
Column {
    id: panel

    spacing: 0

    Component.onCompleted: PairedDisplays.refresh()

    Text {
        visible: PairedDisplays.displays.length === 0
        topPadding: 4
        bottomPadding: 4
        text: !Server.connected ? qsTr("Ei yhteyttä palvelimeen")
            : !PairedDisplays.loaded ? qsTr("Ladataan…")
            : qsTr("Ei kirjautuneita näyttöjä")
        font.family: Theme.fontFamily
        font.pixelSize: 13
        color: Theme.dataLabelTitle
    }

    Repeater {
        model: PairedDisplays.displays

        Item {
            id: entry

            required property var modelData
            required property int index

            readonly property bool thisDisplay: modelData.id === Server.deviceId
            property bool armed: false

            width: panel.width
            height: 54

            Rectangle {
                visible: entry.index > 0
                anchors.top: parent.top
                width: parent.width
                height: 1
                color: Theme.tripCardBorder
            }

            // Connected now or not, never by colour alone: the line below says it too.
            Rectangle {
                id: dot
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 8
                height: 8
                radius: 4
                color: entry.modelData.connected ? "#4ade80" : Theme.dataLabelTitle
            }

            Column {
                anchors.left: dot.right
                anchors.leftMargin: 10
                anchors.right: revoke.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2

                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    text: entry.modelData.name
                          + (entry.thisDisplay ? " · " + qsTr("tämä näyttö") : "")
                    font.family: Theme.fontFamily
                    font.pixelSize: 14
                    color: Theme.dataLabelValue
                }

                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    text: (entry.modelData.connected
                           ? qsTr("Yhdistetty")
                           : qsTr("Viimeksi %1").arg(Format.moment(entry.modelData.lastSeen)))
                          + " · " + entry.modelData.address
                          + " · " + qsTr("kirjautui %1").arg(Format.moment(entry.modelData.created))
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    color: Theme.dataLabelTitle
                }
            }

            // Arm, then confirm within 4 s — SettingAction's guard against a
            // stray tap on a 10" panel, since this one logs a display out.
            Timer {
                id: disarm
                interval: 4000
                onTriggered: entry.armed = false
            }

            Rectangle {
                id: revoke
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(96, revokeLabel.implicitWidth + 28)
                height: 34
                radius: 8
                opacity: Server.connected ? 1.0 : 0.4
                color: !entry.armed
                       ? (revokeTap.pressed ? Theme.tripComboPressed : Theme.tripComboBg)
                       : (revokeTap.pressed ? "#ccffb020" : "#99ffb020")
                border.width: 1
                border.color: entry.armed ? "#80ffb020" : Theme.tripCardBorder

                Text {
                    id: revokeLabel
                    anchors.centerIn: parent
                    text: entry.armed ? qsTr("Vahvista") : qsTr("Poista")
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: entry.armed ? "#1a1206" : Theme.dataLabelValue
                }

                MouseArea {
                    id: revokeTap
                    anchors.fill: parent
                    enabled: Server.connected
                    onClicked: {
                        if (entry.armed) {
                            entry.armed = false
                            disarm.stop()
                            PairedDisplays.revoke(entry.modelData.id)
                        } else {
                            entry.armed = true
                            disarm.restart()
                        }
                    }
                }
            }
        }
    }
}

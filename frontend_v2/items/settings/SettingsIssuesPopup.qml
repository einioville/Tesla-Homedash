import QtQuick
import frontend_v2

// The list behind the header's "Ongelmia havaittu": each detected problem with a
// "Korjaa" button that takes the user to the setting that fixes it.
//
// A child of SettingsView like SpotifyDevicePopup, and drawn the same way (scrim
// over the view's blurred content, an opaque card), but anchored to the TOP of the
// view rather than centred: it answers the header line directly above it. It
// holds no state of its own beyond being open — the list is SettingsIssues' live
// binding, so an issue fixed while the box is open leaves it at once.
Item {
    id: popup

    // SettingsIssues.issues.
    property var issues: []

    signal fixRequested(var issue)

    property bool shown: false

    function open() { popup.shown = true }
    function close() { popup.shown = false }

    anchors.fill: parent
    visible: shown
    z: 100

    // A tap beside the card closes it: this box only informs, so dismissing it
    // costs nothing and needs no dedicated target.
    MouseArea {
        anchors.fill: parent
        onClicked: popup.close()
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.dialogScrim
    }

    Rectangle {
        id: card
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: Theme.gridMargin + 48
        width: Math.min(parent.width - 2 * Theme.gridMargin, 640)
        height: column.implicitHeight + 40
        radius: Theme.tripCardRadius
        color: Theme.spotifySurface
        border.width: 1
        border.color: Theme.spotifyRim

        // Taps on the card itself must not reach the close-on-tap area behind it.
        MouseArea {
            anchors.fill: parent
        }

        Column {
            id: column
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 20
            spacing: 14

            Text {
                width: parent.width
                text: qsTr("Havaitut ongelmat")
                font.family: Theme.fontFamily
                font.pixelSize: 19
                font.bold: true
                color: Theme.dataLabelValue
            }

            // Shown when the last issue clears while the box is open, so it does
            // not sit there empty.
            Text {
                width: parent.width
                visible: popup.issues.length === 0
                text: qsTr("Ei ongelmia.")
                font.family: Theme.fontFamily
                font.pixelSize: 14
                color: Theme.dataLabelTitle
            }

            Repeater {
                model: popup.issues

                Item {
                    id: entry

                    required property var modelData
                    required property int index

                    width: column.width
                    height: Math.max(texts.implicitHeight, fixButton.height) + 12

                    Rectangle {
                        id: dot
                        anchors.left: parent.left
                        anchors.top: texts.top
                        anchors.topMargin: 6
                        width: 8
                        height: 8
                        radius: 4
                        color: entry.modelData.level === "error" ? "#f87171" : "#ffb020"
                    }

                    Column {
                        id: texts
                        anchors.left: dot.right
                        anchors.leftMargin: 10
                        anchors.right: fixButton.left
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2

                        Text {
                            width: parent.width
                            text: entry.modelData.title
                            font.family: Theme.fontFamily
                            font.pixelSize: 15
                            color: Theme.dataLabelValue
                            wrapMode: Text.WordWrap
                        }

                        Text {
                            width: parent.width
                            visible: text.length > 0
                            text: entry.modelData.detail !== undefined ? entry.modelData.detail : ""
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            color: Theme.dataLabelTitle
                            wrapMode: Text.WordWrap
                        }
                    }

                    DialogButton {
                        id: fixButton
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        label: qsTr("Korjaa")
                        // No section: the fixing row is not in the schema now.
                        visible: entry.modelData.section.length > 0
                        onActivated: popup.fixRequested(entry.modelData)
                    }

                    Rectangle {
                        visible: entry.index < popup.issues.length - 1
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: "#1affffff"
                    }
                }
            }

            DialogButton {
                anchors.right: parent.right
                label: qsTr("Sulje")
                onActivated: popup.close()
            }
        }
    }
}

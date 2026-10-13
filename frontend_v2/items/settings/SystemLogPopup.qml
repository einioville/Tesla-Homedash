import QtQuick
import frontend_v2

// One service card's warnings and errors, newest first, with the date and time of
// each — what the card's *Näytä* opens. The list is the backend's persistent
// error store (System.openLog → SYSTEM_GET_LOG), so it reaches back past a
// restart, to the last time the logs were cleared in full.
//
// A child of SettingsView like the other dialogs, anchored high and capped in
// height so it stays clear of the menu's swipe-up strip (ModalDialog); the list
// scrolls.
ModalDialog {
    id: popup

    visible: System.logOpen

    onScrimClicked: System.closeLog()
    cardTopMargin: Theme.gridMargin + 48
    cardWidth: 760
    // At least room for the empty / loading line when there is no list yet; at
    // most what stays clear of the swipe-up strip.
    cardHeight: Math.min(header.height + Math.max(list.contentHeight, 72) + footer.height + 64,
                         height - cardTopMargin - 140)

    Item {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 20
        height: titleText.implicitHeight

        Text {
            id: titleText
            anchors.left: parent.left
            anchors.right: countText.left
            anchors.rightMargin: 12
            text: System.logLabel + " · " + qsTr("varoitukset ja virheet")
            font.family: Theme.fontFamily
            font.pixelSize: 19
            font.bold: true
            color: Theme.dataLabelValue
            elide: Text.ElideRight
        }

        Text {
            id: countText
            anchors.right: parent.right
            anchors.verticalCenter: titleText.verticalCenter
            visible: System.logEntries.length > 0
            text: System.logEntries.length + " " + qsTr("kpl")
            font.family: Theme.fontFamily
            font.pixelSize: 13
            color: Theme.dataLabelTitle
        }
    }

    ListView {
        id: list
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.bottom: footer.top
        anchors.leftMargin: 20
        anchors.rightMargin: 20
        anchors.topMargin: 12
        anchors.bottomMargin: 12
        clip: true
        model: System.logEntries
        boundsBehavior: Flickable.DragAndOvershootBounds

        delegate: Item {
            id: entry

            required property var modelData
            required property int index

            readonly property bool isError: modelData.level === "ERROR" || modelData.level === "CRITICAL"

            width: ListView.view.width
            height: texts.implicitHeight + 22

            Column {
                id: texts
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3

                Row {
                    spacing: 10

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: levelText.implicitWidth + 12
                        height: levelText.implicitHeight + 4
                        radius: 4
                        color: entry.isError ? "#33f87171" : "#33ffb020"

                        Text {
                            id: levelText
                            anchors.centerIn: parent
                            text: entry.modelData.level === "CRITICAL" ? qsTr("KRIITTINEN")
                                : entry.isError ? qsTr("VIRHE") : qsTr("VAROITUS")
                            font.family: Theme.fontFamily
                            font.pixelSize: 11
                            color: entry.isError ? "#f87171" : "#ffd48a"
                        }
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: Qt.formatDateTime(new Date(entry.modelData.t), "dd.MM.yyyy hh:mm:ss")
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                        color: Theme.dataLabelValue
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: entry.modelData.logger
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        color: Theme.dataLabelTitle
                    }
                }

                // A traceback runs to many lines; the first few say what broke.
                Text {
                    width: parent.width
                    text: entry.modelData.message
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: Theme.dataLabelTitle
                    wrapMode: Text.WrapAnywhere
                    maximumLineCount: 6
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                visible: entry.index < list.count - 1
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: "#1affffff"
            }
        }
    }

    Text {
        anchors.centerIn: list
        visible: System.logEntries.length === 0
        text: System.logLoading ? qsTr("Haetaan…")
            : !Server.connected ? qsTr("Ei yhteyttä palvelimeen")
            : qsTr("Ei varoituksia tai virheitä.")
        font.family: Theme.fontFamily
        font.pixelSize: 14
        color: Theme.dataLabelTitle
    }

    Item {
        id: footer
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 20
        height: closeButton.implicitHeight

        DialogButton {
            id: closeButton
            anchors.right: parent.right
            label: qsTr("Sulje")
            onActivated: System.closeLog()
        }
    }
}

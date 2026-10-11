import QtQuick
import frontend_v2

// What choosing DEBUG in the Lokitaso dropdown opens instead of writing it (its
// `onSelect`): how long DEBUG may run before the level returns to the one it came
// from — or *Toistaiseksi* (minutes 0), no end at all, for development. The duration is the backend's hidden `logging.debugMinutes`, written first
// so the countdown the level then starts already uses it; cancelling writes
// nothing, so the dropdown never changed.
//
// A child of SettingsView like the other dialogs, anchored high: a popup inside a
// view cannot cover the dock band.
ModalDialog {
    id: popup

    property bool shown: false
    // The chosen duration in minutes.
    property int minutes: 30

    readonly property var choices: [
        { "minutes": 15, "label": "15 min" },
        { "minutes": 30, "label": "30 min" },
        { "minutes": 60, "label": "1 h" },
        { "minutes": 120, "label": "2 h" },
        { "minutes": 240, "label": "4 h" },
        { "minutes": 480, "label": "8 h" },
        // For development: no timer at all, DEBUG until the level is changed.
        { "minutes": 0, "label": qsTr("Toistaiseksi") }
    ]

    function open() {
        // Start from what was used last time, when it is one of the choices.
        const last = Settings.valueOf("logging.debugMinutes")
        popup.minutes = choices.some(c => c.minutes === last) ? last : 30
        popup.shown = true
    }
    function close() { popup.shown = false }

    function confirm() {
        Settings.setValue("logging.debugMinutes", popup.minutes)
        Settings.setValue("logging.level", "debug")
        popup.close()
    }

    visible: shown

    onScrimClicked: popup.close()
    cardTopMargin: Theme.gridMargin + 96
    cardWidth: 600
    cardHeight: column.implicitHeight + 40

    Column {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 20
        spacing: 16

        Text {
            width: parent.width
            text: qsTr("Ota DEBUG-lokitaso käyttöön")
            font.family: Theme.fontFamily
            font.pixelSize: 19
            font.bold: true
            color: Theme.dataLabelValue
        }

        Text {
            width: parent.width
            text: qsTr("Yksityiskohtainen loki kirjataan lokitiedostoihin sekä palvelimella että "
                       + "tällä näytöllä. Se täyttää lokit nopeasti, joten taso palautuu "
                       + "edelliseen valitun ajan kuluttua.")
            font.family: Theme.fontFamily
            font.pixelSize: 14
            color: Theme.dataLabelTitle
            wrapMode: Text.WordWrap
        }

        Text {
            text: qsTr("Kesto")
            font.family: Theme.fontFamily
            font.pixelSize: 13
            color: Theme.dataLabelTitle
        }

        // Every duration in view, the chosen one in the accent; wraps if the
        // labels ever outgrow one line.
        Flow {
            width: parent.width
            spacing: 8

            Repeater {
                model: popup.choices

                Rectangle {
                    id: choice

                    required property var modelData

                    readonly property bool selected: popup.minutes === modelData.minutes

                    width: Math.max(62, choiceLabel.implicitWidth + 22)
                    height: 40
                    radius: 8
                    color: selected ? "#664aa8ff"
                                    : (choiceArea.pressed ? Theme.tripComboPressed : Theme.tripComboBg)
                    border.width: 1
                    border.color: selected ? Theme.accent : Theme.tripCardBorder

                    Behavior on color {
                        ColorAnimation { duration: Theme.pressDuration }
                    }

                    Text {
                        id: choiceLabel
                        anchors.centerIn: parent
                        text: choice.modelData.label
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                        color: Theme.dataLabelValue
                    }

                    MouseArea {
                        id: choiceArea
                        anchors.fill: parent
                        onClicked: popup.minutes = choice.modelData.minutes
                    }
                }
            }
        }

        Text {
            width: parent.width
            visible: popup.minutes === 0
            text: qsTr("DEBUG pysyy päällä myös uudelleenkäynnistysten yli, kunnes vaihdat tason.")
            font.family: Theme.fontFamily
            font.pixelSize: 13
            color: "#ffd48a"
            wrapMode: Text.WordWrap
        }

        Row {
            anchors.right: parent.right
            spacing: 10

            DialogButton {
                label: qsTr("Peruuta")
                onActivated: popup.close()
            }

            DialogButton {
                primary: true
                label: qsTr("Ota käyttöön")
                onActivated: popup.confirm()
            }
        }
    }
}

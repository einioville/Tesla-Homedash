import QtQuick
import frontend_v2
import "WeatherUtil.js" as U

// The weather warnings that cover the place, whole: what the Nyt card's strip only
// begins — the headline, when it is in force, the area that covers the place and FMI's
// description. Opened by tapping the strip; a child of WeatherDashboard, which closes it
// when the view goes.
ModalDialog {
    id: popup

    // The warnings that apply here, from the WEATHER_VIEW document.
    property var warnings: []
    property bool shown: false

    function open() { popup.shown = true }
    function close() { popup.shown = false }

    visible: shown && warnings.length > 0

    onScrimClicked: popup.close()
    cardTopMargin: Theme.gridMargin + 60
    cardWidth: 640
    // Ends above the menu's swipe-up strip; a longer list scrolls. 72: the margins
    // round and between header, list and footer.
    cardHeight: Math.min(header.height + list.contentHeight + footer.height + 72,
                         popup.height - cardTopMargin - 72 - Theme.gridMargin)

    Text {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 20
        text: qsTr("Säävaroitukset")
        font.family: Theme.fontFamily
        font.pixelSize: 19
        font.bold: true
        color: Theme.dataLabelValue
    }

    ElasticFlickable {
        id: list
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.bottom: footer.top
        anchors.leftMargin: 20
        anchors.rightMargin: 20
        anchors.topMargin: 16
        anchors.bottomMargin: 16
        clip: true
        contentHeight: entries.implicitHeight

        Column {
            id: entries
            width: list.width
            spacing: 20

            Repeater {
                model: popup.warnings

                Item {
                    id: entry

                    required property var modelData

                    width: entries.width
                    height: details.implicitHeight

                    // The warning's colour as a bar down its side, as FMI marks its levels.
                    Rectangle {
                        width: 6
                        height: parent.height
                        radius: 3
                        color: U.warnColor(entry.modelData.color)
                    }

                    Column {
                        id: details
                        x: 18
                        width: parent.width - x
                        spacing: 6

                        Text {
                            width: parent.width
                            text: entry.modelData.headline || ""
                            font.family: Theme.fontFamily
                            font.pixelSize: 16
                            font.bold: true
                            color: Theme.dataLabelValue
                            wrapMode: Text.WordWrap
                        }

                        Text {
                            width: parent.width
                            visible: text.length > 0
                            text: {
                                const parts = []
                                const when = U.warnWhen(entry.modelData)
                                if (when)
                                    parts.push(qsTr("Voimassa ") + when)
                                const areas = entry.modelData.hereAreas || []
                                if (areas.length)
                                    parts.push(qsTr("koskee aluetta ") + areas.join(", "))
                                return parts.join(" · ")
                            }
                            font.family: Theme.fontFamily
                            font.pixelSize: 13
                            color: Theme.dataLabelTitle
                            wrapMode: Text.WordWrap
                        }

                        Text {
                            width: parent.width
                            visible: text.length > 0
                            text: entry.modelData.description || ""
                            font.family: Theme.fontFamily
                            font.pixelSize: 14
                            color: Theme.dataLabelValue
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }

    Item {
        id: footer
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 20
        height: closeButton.height

        DialogButton {
            id: closeButton
            anchors.right: parent.right
            primary: true
            label: qsTr("Sulje")
            onActivated: popup.close()
        }
    }
}

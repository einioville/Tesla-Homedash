import QtQuick
import frontend_v2
import "WeatherUtil.js" as U

// Weather warnings, whole: the headline, when each is in force, the area that covers the
// place and FMI's description. Opened from the Weather view's strip, the dashboard's hourly
// badges and the Kartta view's legend, each of which hosts its own and closes it when the view
// goes. On frosted glass over the view's `backdrop`, as the road camera dialog is, but higher:
// it is read, not worked, so it sits at reading height rather than centred.
ModalDialog {
    id: popup

    // From the WEATHER_VIEW document: the ones that apply here, or the map's.
    property var warnings: []
    // Where the warnings are for, when they are for one place.
    property string place: ""
    property bool shown: false

    readonly property real topMost: Theme.gridMargin + 60

    function open() { popup.shown = true }
    function close() { popup.shown = false }

    visible: shown && warnings.length > 0

    onScrimClicked: popup.close()
    // Centred on 40 % of the height, never above `topMost`.
    cardTopMargin: Math.max(topMost, Math.round(popup.height * 0.4 - cardHeight / 2))
    cardWidth: 640
    // Ends above the menu's swipe-up strip; a longer list scrolls. 54: the margins
    // between the subtitle, list and footer and below it.
    cardHeight: Math.min(subtitle.y + subtitle.height + list.contentHeight + footer.height + 54,
                         popup.height - topMost - 72 - Theme.gridMargin)

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
    Text {
        id: subtitle
        anchors.left: header.left
        anchors.top: header.bottom
        anchors.topMargin: 2
        text: {
            const count = popup.warnings.length === 1 ? qsTr("1 varoitus")
                                                     : qsTr("%1 varoitusta").arg(popup.warnings.length)
            return popup.place ? popup.place + " · " + count : count
        }
        font.family: Theme.fontFamily
        font.pixelSize: 13
        color: Theme.dataLabelTitle
    }

    ElasticFlickable {
        id: list
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: subtitle.bottom
        anchors.bottom: footer.top
        anchors.leftMargin: 20
        anchors.rightMargin: 20
        anchors.topMargin: 18
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

        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: qsTr("Lähde: Ilmatieteen laitos, lisenssi CC 4.0 BY")
            font.family: Theme.fontFamily
            font.pixelSize: 11
            color: Theme.dataLabelTitle
        }
        DialogButton {
            id: closeButton
            anchors.right: parent.right
            primary: true
            label: qsTr("Sulje")
            onActivated: popup.close()
        }
    }
}

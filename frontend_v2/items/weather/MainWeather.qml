import QtQuick
import frontend_v2

// Weather panel — the Weather view's hourly chart card: twelve hours across, every one
// labelled, scrollable through the whole forecast, over the same live data. Here alone
// the hours a warning is in force in carry a badge; the Weather view has no room for them.
// The pill in the title row's corner opens the Weather view: a tap anywhere on the card would
// be too easily made, and the chart and its badges take taps of their own.
WeatherHourlyCard {
    hours: Weather.view.hourly || []
    hoursVisible: 12
    labelEvery: 1
    warningBadges: true
    noteInset: openPill.width + 8

    Rectangle {
        id: openPill
        z: 3
        anchors.right: parent.right
        anchors.rightMargin: 10
        y: 5
        width: openRow.implicitWidth + 22
        height: 24
        radius: 12
        color: openTap.pressed ? "#40ffffff" : "#26ffffff"

        Row {
            id: openRow
            anchors.centerIn: parent
            spacing: 3

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("Sää")
                color: "white"
                font.family: Theme.fontFamily
                font.pixelSize: 12
            }
            TintedIcon {
                anchors.verticalCenter: parent.verticalCenter
                iconSize: 13
                source: "qrc:/resources/icons/arrow_right.svg"
            }
        }
        MouseArea {
            id: openTap
            anchors.fill: parent
            anchors.margins: -8
            onClicked: Navigation.open("weather")
        }
    }
}

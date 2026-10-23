import QtQuick
import frontend_v2
import "../../app/Format.js" as Format

// The Kartta view's live data — speed, battery level, range and outside temperature — on
// frosted glass over the map (`backdrop`, a sibling of this panel). The glass is the
// notification pill's, darker than the Weather card's radar bar: aerial imagery is bright.
// The car reports the outside temperature only while it is awake, so an hour into its sleep
// the temperature is FMI's for the place (the Weather view's now).
GlassPanel {
    id: root

    property Item backdrop: null

    readonly property int carTempMaxSleepMs: 60 * 60 * 1000
    property real clock: Date.now()
    readonly property var fmiTemp: Weather.view.now ? Weather.view.now.temp : undefined
    readonly property bool fmiOutside: Tesla.asleepSince > 0 && clock - Tesla.asleepSince >= carTempMaxSleepMs
                                       && typeof fmiTemp === "number"

    Timer {
        interval: 60 * 1000
        running: root.active && Tesla.asleepSince > 0
        repeat: true
        triggeredOnStart: true
        onTriggered: root.clock = Date.now()
    }

    implicitWidth: row.implicitWidth + 40
    implicitHeight: 84
    radius: 18
    rimWidth: 0.75
    highlight: false
    backdropSource: backdrop
    backdropOrigin: Qt.point(x - (backdrop ? backdrop.x : 0), y - (backdrop ? backdrop.y : 0))

    component Stat: Column {
        id: stat
        property string value
        property string unit
        property string caption
        spacing: 2

        Row {
            spacing: 5
            Text {
                id: valueText
                text: stat.value
                color: "white"
                font.family: Theme.fontFamily
                font.pixelSize: 30
            }
            Text {
                anchors.baseline: valueText.baseline
                visible: stat.value !== "—"
                text: stat.unit
                color: "#b8c2cc"
                font.family: Theme.fontFamily
                font.pixelSize: 14
            }
        }
        Text {
            text: stat.caption
            color: Theme.cardTitle
            font.family: Theme.fontFamily
            font.pixelSize: 11
            font.letterSpacing: 1.2
        }
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 28

        Stat { value: Format.num(Tesla.vehicleSpeed, "", 0); unit: "km/h"; caption: qsTr("NOPEUS") }
        Stat { value: Format.num(Tesla.batteryLevel, "", 0); unit: "%"; caption: qsTr("AKKU") }
        Stat { value: Format.num(Tesla.estBatteryRange, "", 0); unit: "km"; caption: qsTr("TOIMINTAMATKA") }
        Stat {
            value: Format.num(root.fmiOutside ? root.fmiTemp : Tesla.outsideTemp, "", 1)
            unit: "°C"
            caption: qsTr("ULKONA")
        }
    }
}

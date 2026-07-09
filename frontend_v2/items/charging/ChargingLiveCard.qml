import QtQuick
import QtQuick.Layouts
import frontend_v2

// Compact live charger status strip for the Charging view: current state + session
// energy + live charge/grid power, from the CHARGER_STREAM broadcast. Minimalistic
// translucent-grey card matching the stat tiles. Updates in place (no delegate churn):
// each stat binds its own value, so only the changed field repaints per frame.
Item {
    id: root

    function has(v) { return v !== undefined && v !== null && !isNaN(v) }
    function statusText(s) {
        switch (s) {
            case 2: return qsTr("Lataa")
            case 1: return qsTr("Tauolla")
            case 3: return qsTr("Valmis")
            default: return "—"
        }
    }
    function power(w) { return has(w) ? Math.round(w) + " W" : "—" }
    function energy(kwh) { return has(kwh) ? kwh.toFixed(2) + " kWh" : "—" }

    // One title-over-value stat in the row.
    component LiveStat: Column {
        property string t: ""
        property string v: "—"
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignVCenter
        spacing: 2
        Text {
            text: parent.t
            color: Theme.dataLabelTitle
            font.family: Theme.fontFamily
            font.pixelSize: 14
        }
        Text {
            text: parent.v
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pixelSize: 22
            font.bold: true
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.tripCardRadius
        color: Theme.tripCardBg
        border.width: 1
        border.color: Theme.tripCardBorder
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        spacing: 12

        LiveStat { t: qsTr("Tila");       v: root.statusText(Charging.status) }
        LiveStat { t: qsTr("Istunto");    v: root.energy(Charging.sessionEnergyKwh) }
        LiveStat { t: qsTr("Latausteho"); v: root.power(Charging.chargePowerW) }
        LiveStat { t: qsTr("Verkkoteho"); v: root.power(Charging.gridPowerW) }
    }
}

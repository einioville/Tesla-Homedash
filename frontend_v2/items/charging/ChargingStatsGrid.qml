import QtQuick
import QtQuick.Layouts
import frontend_v2

// The Charging-view month-to-date stats: a 2×5 grid of stat tiles (reusing TripStatCard)
// bound to Charging.monthSummary. Every value degrades to "—" when its metric is NaN /
// missing, so a partial-data month still renders cleanly. Energies are already in kWh
// (unlike the trip grid's Wh), so they format directly.
Item {
    id: root

    readonly property var s: Charging.monthSummary

    function has(v) { return v !== undefined && v !== null && !isNaN(v) }
    function num(v, unit, dec) {
        return has(v) ? v.toFixed(dec) + (unit ? " " + unit : "") : "—"
    }
    function hours(sec) {
        return has(sec) ? (sec / 3600).toFixed(1) + " h" : "—"
    }

    GridLayout {
        anchors.fill: parent
        columns: 2
        rowSpacing: 10
        columnSpacing: 10

        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Laturin energia"); value: root.num(root.s.chargerKwh, "kWh", 1)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Autoon");          value: root.num(root.s.carKwh, "kWh", 1)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Hukka");           value: root.num(root.s.wastedKwh, "kWh", 1)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Hyötysuhde");      value: root.num(root.s.efficiencyPct, "%", 0)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Ajokulutus");      value: root.num(root.s.carWhPerKm, "Wh/km", 0)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Laturikulutus");   value: root.num(root.s.chargerWhPerKm, "Wh/km", 0)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Latauskerrat");    value: root.num(root.s.sessionCount, "", 0)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Latausaika");      value: root.hours(root.s.totalChargeS)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Latauskulut");     value: root.num(root.s.chargingCostEur, "€", 2)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Kotitalous");      value: root.num(root.s.homeGridKwh, "kWh", 1)
        }
        // Total home electricity cost this month (all grid import * flat tariff),
        // spanning both columns as a footer.
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.columnSpan: 2
            title: qsTr("Sähkölasku");      value: root.num(root.s.homeCostEur, "€", 2)
        }
    }
}

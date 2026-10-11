import QtQuick
import QtQuick.Layouts
import frontend_v2
import "../../app/Format.js" as Format

// The Charging-view month-to-date stats: a 2×5 grid of stat tiles (reusing TripStatCard)
// plus a full-width footer tile, bound to Charging.monthSummary. Every value degrades to "—" when its metric is NaN /
// missing, so a partial-data month still renders cleanly. Energies are already in kWh
// (unlike the trip grid's Wh), so they format directly.
Item {
    id: root

    readonly property var s: Charging.monthSummary

    function hours(sec) {
        return Format.has(sec) ? (sec / 3600).toFixed(1) + " h" : "—"
    }

    GridLayout {
        anchors.fill: parent
        columns: 2
        rowSpacing: 10
        columnSpacing: 10

        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Laturin energia"); value: Format.num(root.s.chargerKwh, "kWh", 1)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Autoon");          value: Format.num(root.s.carKwh, "kWh", 1)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Hukka");           value: Format.num(root.s.wastedKwh, "kWh", 1)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Hyötysuhde");      value: Format.num(root.s.efficiencyPct, "%", 0)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Ajokulutus");      value: Format.num(root.s.carWhPerKm, "Wh/km", 0)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Laturikulutus");   value: Format.num(root.s.chargerWhPerKm, "Wh/km", 0)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Latauskerrat");    value: Format.num(root.s.sessionCount, "", 0)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Latausaika");      value: root.hours(root.s.totalChargeS)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Latauskulut");     value: Format.num(root.s.chargingCostEur, "€", 2)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Kotitalous");      value: Format.num(root.s.homeGridKwh, "kWh", 1)
        }
        // Total home electricity cost this month (all grid import, priced per hour at
        // the spot price with the flat tariff as fallback), spanning both columns.
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.columnSpan: 2
            title: qsTr("Sähkölasku");      value: Format.num(root.s.homeCostEur, "€", 2)
        }
    }
}

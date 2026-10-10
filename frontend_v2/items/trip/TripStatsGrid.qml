import QtQuick
import QtQuick.Layouts
import frontend_v2
import "../../app/Format.js" as Format

// The Trips-view stats panel: a 2×4 grid of TripStatCards bound to Trips.summary
// (the selected trip's computed metrics). Every value degrades to "—" when its metric
// is NaN / missing, so a partial-data trip still renders cleanly. Empty (all "—")
// until a trip is picked; cleared with the route when the week changes.
Item {
    id: root

    readonly property var s: Trips.summary

    // The backend packs NaN for a metric it has no data for.
    function time(ms) {
        return Format.has(ms) && ms > 0 ? Qt.formatDateTime(new Date(ms), "HH:mm") : "—"
    }
    function energy(wh) {
        return Format.has(wh) ? (wh / 1000).toFixed(2) + " kWh" : "—"
    }

    GridLayout {
        anchors.fill: parent
        columns: 2
        rowSpacing: 10
        columnSpacing: 10

        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Lähtöaika");    value: root.time(root.s.startMs)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Saapumisaika"); value: root.time(root.s.endMs)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Matka");        value: Format.num(root.s.distanceKm, "km", 1)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Energia");      value: root.energy(root.s.energyWh)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Keskinopeus");  value: Format.num(root.s.avgSpeed, "km/h", 0)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Keskikulutus"); value: Format.num(root.s.whPerKm, "Wh/km", 0)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Huippunopeus"); value: Format.num(root.s.maxSpeed, "km/h", 0)
        }
        TripStatCard {
            Layout.fillWidth: true; Layout.fillHeight: true
            title: qsTr("Akun kulutus"); value: Format.num(root.s.socUsed, "%", 0)
        }
    }
}

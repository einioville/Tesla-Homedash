import QtQuick
import frontend_v2

// The dashboard: a 10×16 grid (10px margins, 10px gaps) holding the map, two
// telemetry lists, the media card, the weather panel and the climate panel, over
// a backdrop in the playing cover's colours (MediaBackdrop) that the climate
// switch's wave runs across (ClimateWave). Cell
// geometry is computed as the Widgets frontend's MainWindow QGridLayout does it,
// so the six cards sit in the same positions on the fixed 1280×800 surface.
Rectangle {
    id: view

    property bool isCurrent: false

    color: Theme.dashboardBackground

    readonly property real gridMargin: Theme.gridMargin
    readonly property real gridSpacing: 10
    readonly property real cellW: (width - 2 * gridMargin - 15 * gridSpacing) / 16
    readonly property real cellH: (height - 2 * gridMargin - 9 * gridSpacing) / 10

    function cellX(col) { return gridMargin + col * (cellW + gridSpacing) }
    function cellY(row) { return gridMargin + row * (cellH + gridSpacing) }
    function spanW(span) { return span * cellW + (span - 1) * gridSpacing }
    function spanH(span) { return span * cellH + (span - 1) * gridSpacing }

    // The light lies where the cards let it through: the map and the media card
    // are opaque, so the cover's own colour pools beside the player, in the weather
    // card, as if spilling from it, and the rest spreads over the cards on the right.
    MediaBackdrop {
        id: backdrop
        anchors.fill: parent
        active: view.isCurrent
        glows: [
            { tone: 0, radius: 520, home: Qt.point(430, 640), reach: Qt.point(150, 110),
              periods: Qt.vector3d(37, 29, 23), phase: 0.0 },
            { tone: 1, radius: 560, home: Qt.point(1000, 200), reach: Qt.point(200, 120),
              periods: Qt.vector3d(43, 31, 27), phase: 1.7 },
            { tone: 2, radius: 480, home: Qt.point(780, 630), reach: Qt.point(220, 130),
              periods: Qt.vector3d(53, 41, 33), phase: 3.1 },
            { tone: 0, radius: 460, home: Qt.point(1150, 560), reach: Qt.point(140, 120),
              periods: Qt.vector3d(47, 34, 29), phase: 4.4 }
        ]
    }

    ClimateWave {
        id: climateWave
        anchors.fill: parent
        backdrop: backdrop
        button: climate.hvacButton
        origin: Qt.point(climate.x + climate.hvacButtonCenter.x, climate.y + climate.hvacButtonCenter.y)
    }

    TeslaMap {
        x: view.cellX(0); y: view.cellY(0)
        width: view.spanW(8); height: view.spanH(6)
        isCurrent: view.isCurrent
    }

    // Driven today / this month + odometer.
    DataEntryList {
        x: view.cellX(8); y: view.cellY(0)
        width: view.spanW(4); height: view.spanH(6)
        entries: [
            { title: "Ajettu Tänään",       value: Tesla.drivenToday,     unit: "km" },
            { title: "Ajettu Tässä Kuussa", value: Tesla.drivenThisMonth, unit: "km" },
            { title: "Odometer",            value: Tesla.odometer,        unit: "km" }
        ]
    }

    // Speed / battery / range.
    DataEntryList {
        x: view.cellX(12); y: view.cellY(0)
        width: view.spanW(4); height: view.spanH(6)
        entries: [
            { title: "Nopeus",      value: Tesla.vehicleSpeed,    unit: "km/h" },
            { title: "Akun Varaus", value: Tesla.batteryLevel,    unit: "%" },
            { title: "Range",       value: Tesla.estBatteryRange, unit: "km" }
        ]
    }

    MediaPlayerCard {
        x: view.cellX(0); y: view.cellY(6)
        width: view.spanW(4); height: view.spanH(4)
        active: view.isCurrent
    }

    MainWeather {
        x: view.cellX(4); y: view.cellY(6)
        width: view.spanW(8); height: view.spanH(4)
    }

    ClimateCard {
        id: climate
        x: view.cellX(12); y: view.cellY(6)
        width: view.spanW(4); height: view.spanH(4)
        isCurrent: view.isCurrent
        waveOutTo: climateWave.outTo
    }

    // Luna — a memorial overlay for our dog. Deliberately its OWN full-view layer
    // on top of every card (NOT part of the grid), so she ambles across the
    // foreground of the whole dashboard. Frozen while the view isn't current;
    // toggled entirely by Theme.lunaEnabled. The layer itself carries no MouseArea,
    // so the cards underneath stay tappable everywhere EXCEPT the small moving patch
    // under Luna's own tap hitbox (tap-to-sit / tap-to-wake).
    Item {
        id: lunaLayer
        anchors.fill: parent
        z: 999
        visible: Theme.lunaEnabled

        Luna {
            running: view.isCurrent && Theme.lunaEnabled
        }
    }
}

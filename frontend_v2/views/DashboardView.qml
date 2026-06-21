import QtQuick
import frontend_v2

// The production dashboard, recreated from the Widgets frontend's MainWindow:
// a 10×16 grid (10px margins, 10px gaps) holding the map, two telemetry lists,
// the media card, the weather panel and the climate panel. Cell geometry is
// computed exactly as the original QGridLayout did, so the six cards land in
// the same positions on the fixed 1280×800 surface. The dock floats over the
// cards (a frosted overlay), so the grid is NOT inset for it.
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

    TeslaMap {
        x: view.cellX(0); y: view.cellY(0)
        width: view.spanW(8); height: view.spanH(6)
        isCurrent: view.isCurrent
    }

    // Driven today / this month + odometer — gradient toward the bottom-right.
    DataEntryList {
        x: view.cellX(8); y: view.cellY(0)
        width: view.spanW(4); height: view.spanH(6)
        gradientCx: 0.75; gradientCy: 1.0
        entries: [
            { title: "Ajettu Tänään",       value: Tesla.drivenToday,     unit: "km" },
            { title: "Ajettu Tässä Kuussa", value: Tesla.drivenThisMonth, unit: "km" },
            { title: "Odometer",            value: Tesla.odometer,        unit: "km" }
        ]
    }

    // Speed / battery / range — gradient toward the bottom-left.
    DataEntryList {
        x: view.cellX(12); y: view.cellY(0)
        width: view.spanW(4); height: view.spanH(6)
        gradientCx: 0.25; gradientCy: 1.0
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
        x: view.cellX(12); y: view.cellY(6)
        width: view.spanW(4); height: view.spanH(4)
        isCurrent: view.isCurrent
    }
}

import QtQuick
import frontend_v2

// A past-hour power graph in the Charging view: the shared HistoryGraph fed from one of
// the Charging singleton's rolling series (grid or charge power), in the minimalistic
// translucent-grey card. Pure renderer — ChargingView wires the singleton's ready/tick
// signals to reload()/advance() (mirrors TripGraphCard's onSeriesReady → reloadFull).
Item {
    id: root

    property string title: ""
    property string unit: "W"
    // A { points, minX, maxX, minY, maxY, count } map from Charging.gridSeries/.chargeSeries.
    property var series: ({})
    // Forwarded to the graph's pulsing "now" marker — these past-hour graphs roll, so the
    // owning view sets this true while it's on screen.
    property bool live: false

    function reload() { graph.reloadFull() }
    function advance() { graph.advanceLive() }

    Rectangle {
        anchors.fill: parent
        radius: Theme.tripCardRadius
        color: Theme.tripCardBg
        border.width: 1
        border.color: Theme.tripCardBorder
    }

    HistoryGraph {
        id: graph
        anchors.fill: parent
        showBackground: false
        // Extra top padding to clear the overlaid title (below); the other three sides
        // keep the default card padding.
        plotMarginTop: 40
        unit: root.unit
        live: root.live
        pointsData: root.series && root.series.points ? root.series.points : []
        dataMinX: root.series && root.series.minX !== undefined ? root.series.minX : 0
        dataMaxX: root.series && root.series.maxX !== undefined ? root.series.maxX : 1
        dataMinY: root.series && root.series.minY !== undefined ? root.series.minY : 0
        dataMaxY: root.series && root.series.maxY !== undefined ? root.series.maxY : 1
        dataCount: root.series && root.series.count !== undefined ? root.series.count : 0
        dataLoading: Charging.historyLoading
    }

    Text {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 16
        text: root.title
        color: Theme.dataLabelTitle
        font.family: Theme.fontFamily
        font.pixelSize: 16
    }
}

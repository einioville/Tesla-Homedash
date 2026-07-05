import QtQuick
import frontend_v2

// The Trips-view detail graph card: the shared HistoryGraph fed from the Trips
// singleton's per-trip series, in a minimalistic translucent-grey card. It is a pure
// renderer — TripsView requests the series (Trips.requestSeries) on trip selection; the
// graph redraws whenever a series arrives.
//
// For now the graph plots ONLY VehicleSpeed (the default graph look — axes + margins).
Item {
    id: root

    // The property this card plots (read by TripsView to request the series).
    readonly property string propertyId: "VehicleSpeed"
    readonly property string unitLabel: "km/h"

    // Graph inspect state, forwarded so TripsView can mirror the cursor on the map.
    readonly property bool inspecting: graph.inspecting
    readonly property real inspectTime: graph.inspectTime

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
        unit: root.unitLabel
        // Feed from the Trips per-trip series instead of the History singleton, so this
        // graph is fully independent of the History view's graph.
        pointsData: Trips.seriesPoints
        dataMinX: Trips.seriesMinX
        dataMaxX: Trips.seriesMaxX
        dataMinY: Trips.seriesMinY
        dataMaxY: Trips.seriesMaxY
        dataCount: Trips.seriesCount
        dataLoading: Trips.seriesLoading

        Connections {
            target: Trips
            function onSeriesReady() { graph.reloadFull() }
        }
    }

    // Static graph title (the dropdown is disabled while the graph is speed-only).
    Text {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 16
        text: qsTr("Nopeus") + " (" + root.unitLabel + ")"
        color: Theme.dataLabelTitle
        font.family: Theme.fontFamily
        font.pixelSize: 16
    }
}

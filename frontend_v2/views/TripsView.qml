import QtQuick
import frontend_v2

// Trips view: a full-screen map with a floating control bar (week + trip
// dropdowns) on top. Pick a week to load its trips, then pick a trip to draw its
// speed-coloured route on the map. State (selected week / trip / drawn route) is
// preserved across view switches — the view is kept alive and nothing is reloaded
// on re-show, so returning shows exactly what you left.
Rectangle {
    id: view

    property bool isCurrent: false
    color: Theme.tripBackground

    // Refresh the week list + per-week trip counts when the view is shown, so labels
    // and the current-week end bound track wall-clock time on this always-on device
    // (the picked week is preserved, so no route reload). The first build happens in
    // WeekSelector.onCompleted.
    onIsCurrentChanged: if (isCurrent) weekSelector.refresh()

    TripMap {
        id: tripMap
        anchors.fill: parent
        isCurrent: view.isCurrent
    }

    // Floating control bar over the map (ComboBox popups render in the window
    // overlay, above the map).
    Rectangle {
        id: controlBar
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.topMargin: Theme.gridMargin
        width: barRow.implicitWidth + 32
        height: barRow.implicitHeight + 20
        radius: Theme.notificationRadius
        color: Theme.tripControlBar
        border.width: 1
        border.color: Theme.tripControlBarBorder

        Row {
            id: barRow
            anchors.centerIn: parent
            spacing: 12

            WeekSelector {
                id: weekSelector
                width: 240
                anchors.verticalCenter: parent.verticalCenter
                onWeekSelected: function(startMs, endMs) {
                    Trips.requestTrips(startMs, endMs)
                }
            }

            TripSelector {
                id: tripSelector
                width: 320
                anchors.verticalCenter: parent.verticalCenter
                onTripSelected: function(startMs, endMs) {
                    Trips.requestRoute(startMs, endMs)
                }
            }
        }
    }
}

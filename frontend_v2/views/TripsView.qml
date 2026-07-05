import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import frontend_v2

// Trips view ("Matkat"): pick a week, then a trip, and inspect it three ways —
//   • left column (60% width): the speed-coloured route map (60% of the stack height)
//     over a VehicleSpeed graph (the remaining 40%);
//   • right column (40% width): the week + trip selector card on top, then a 2×4 grid
//     of computed stat cards.
// The two columns are ANCHORED at explicit widths (not RowLayout-distributed — that
// collapsed to 50/50 / one-column-eats-all with the zero-implicit cards); each column
// is a ColumnLayout only for its internal vertical stacking (one fillHeight item).
// Selecting a trip loads its route, summary stats and the graph's VehicleSpeed series.
// State is preserved across view switches (kept alive, no reload on re-show).
Rectangle {
    id: view

    property bool isCurrent: false
    color: Theme.tripBackground

    // The selected trip's window (0 when none is picked). Drives the summary/route
    // requests and the graph card; cleared to 0 when the week changes.
    property double selectedStartMs: 0
    property double selectedEndMs: 0

    // Usable width for the two columns (view minus the outer margins and the 10px gap
    // between the columns); split 60/40.
    readonly property real contentWidth: width - 2 * Theme.gridMargin - 10
    // Usable height of the left column's map+graph stack (minus the 10px gap); map takes
    // 60%, the graph 40%.
    readonly property real leftStackHeight: height - 2 * Theme.gridMargin - 10

    // Pick a trip: load its route, summary and speed graph. All three requests are made
    // here with the exact window (rather than reacting to a property-binding change), so
    // the graph series is requested reliably.
    function selectTrip(startMs, endMs) {
        view.selectedStartMs = startMs
        view.selectedEndMs = endMs
        Trips.requestRoute(startMs, endMs)
        Trips.requestSummary(startMs, endMs)
        Trips.requestSeries(startMs, endMs, graphCard.propertyId)
    }

    // Refresh the week list + counts when shown, so the week labels track wall-clock
    // time on this always-on device. The picked week/trip is preserved.
    onIsCurrentChanged: if (isCurrent) weekSelector.refresh()

    // Left column (60% width): map (40% of view height) + graph (fills the rest).
    ColumnLayout {
        id: leftColumn
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.leftMargin: Theme.gridMargin
        anchors.topMargin: Theme.gridMargin
        anchors.bottomMargin: Theme.gridMargin
        width: view.contentWidth * 0.60
        spacing: 10

        // --- Map card (60% of the stack height) ------------------------------
        Item {
            id: mapCard
            Layout.fillWidth: true
            Layout.preferredHeight: view.leftStackHeight * 0.60

            TripMap {
                id: tripMap
                anchors.fill: parent
                isCurrent: view.isCurrent
                // Mirror the speed graph's inspect cursor: a heading arrow on the route
                // at the position for the inspected time.
                inspecting: graphCard.inspecting
                inspectTime: graphCard.inspectTime
            }

            // Rounded corners without masking the live map: an odd-even Shape paints the
            // view background back over the four corner slivers only (the TeslaMap
            // technique — no per-frame FBO; gestures fall through).
            Shape {
                anchors.fill: parent
                z: 10
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    fillRule: ShapePath.OddEvenFill
                    strokeWidth: 0
                    strokeColor: "transparent"
                    fillColor: Theme.tripBackground
                    PathRectangle { width: mapCard.width; height: mapCard.height; radius: 0 }
                    PathRectangle {
                        width: mapCard.width; height: mapCard.height
                        radius: Theme.tripCardRadius
                    }
                }
            }

            // Whiteish card border over the rounded map edge.
            Rectangle {
                anchors.fill: parent
                z: 11
                radius: Theme.tripCardRadius
                color: "transparent"
                border.width: 1
                border.color: Theme.tripCardBorder
            }
        }

        // --- Graph card (fills the remaining height ≈ 40%) ------------------
        TripGraphCard {
            id: graphCard
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }

    // Right column (40% width): selector card on top, then the stats grid.
    ColumnLayout {
        id: rightColumn
        anchors.left: leftColumn.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.leftMargin: 10
        anchors.rightMargin: Theme.gridMargin
        anchors.topMargin: Theme.gridMargin
        anchors.bottomMargin: Theme.gridMargin
        spacing: 10

        // --- Week + trip selector card (tall enough for the two-line dropdowns) ---
        Rectangle {
            id: selectorCard
            Layout.fillWidth: true
            Layout.preferredHeight: 64
            radius: Theme.tripCardRadius
            color: Theme.tripCardBg
            border.width: 1
            border.color: Theme.tripCardBorder

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 8

                // Both fillWidth with an equal preferred width → the two boxes get the
                // same width, splitting the card evenly.
                WeekSelector {
                    id: weekSelector
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.alignment: Qt.AlignVCenter
                    onWeekSelected: function(startMs, endMs) {
                        // A new week deselects the trip: clear the selection so the graph
                        // card empties (Trips.requestTrips also clears route/summary/series).
                        view.selectedStartMs = 0
                        view.selectedEndMs = 0
                        Trips.requestTrips(startMs, endMs)
                    }
                }

                TripSelector {
                    id: tripSelector
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.alignment: Qt.AlignVCenter
                    onTripSelected: function(startMs, endMs) {
                        view.selectTrip(startMs, endMs)
                    }
                }
            }
        }

        // --- Stats grid (fills the rest) -------------------------------------
        TripStatsGrid {
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }
}

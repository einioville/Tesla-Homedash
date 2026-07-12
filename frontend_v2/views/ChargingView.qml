import QtQuick
import QtQuick.Layouts
import frontend_v2

// Charging view ("Lataus"): the myenergi charger.
//   • left column (60% width): two stacked past-hour power graphs (grid + charge power);
//   • right column (40% width): a live status strip on top, then the month-to-date stats
//     grid (2×5 of the computed month metrics).
// Matches the Trips view's minimalistic translucent-grey card style. State is preserved
// across view switches (kept alive, no reload on re-show); the live graph buffering +
// month refresh are gated on isCurrent so a hidden view does no per-frame work.
Rectangle {
    id: view

    property bool isCurrent: false
    color: Theme.tripBackground

    // Usable width for the two columns (view minus the outer margins and the 10px gap
    // between the columns); split 60/40, matching TripsView.
    readonly property real contentWidth: width - 2 * Theme.gridMargin - 10

    // Seed/refresh the graphs + month stats when shown; freeze the live graph buffers
    // when hidden (the CHARGER_STREAM tiles in the live strip keep updating regardless).
    onIsCurrentChanged: {
        if (isCurrent) {
            Charging.startLive()
            Charging.requestMonth()
        } else {
            Charging.stopLive()
        }
    }

    // Left column (60%): two past-hour power graphs stacked evenly.
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

        ChargingGraphCard {
            id: gridCard
            Layout.fillWidth: true
            Layout.fillHeight: true
            title: qsTr("Verkkoteho") + " (W)"
            unit: "W"
            series: Charging.gridSeries
            live: view.isCurrent
        }
        ChargingGraphCard {
            id: chargeCard
            Layout.fillWidth: true
            Layout.fillHeight: true
            title: qsTr("Latausteho") + " (W)"
            unit: "W"
            series: Charging.chargeSeries
            live: view.isCurrent
        }
    }

    // Wire each series' ready (fresh seed → reset + refill) and tick (live append →
    // advance without clobbering zoom) signals to its graph card.
    Connections {
        target: Charging
        function onGridReady() { gridCard.reload() }
        function onGridTick() { gridCard.advance() }
        function onChargeReady() { chargeCard.reload() }
        function onChargeTick() { chargeCard.advance() }
    }

    // Right column (40%): live status strip on top, then the month stats grid.
    ColumnLayout {
        anchors.left: leftColumn.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.leftMargin: 10
        anchors.rightMargin: Theme.gridMargin
        anchors.topMargin: Theme.gridMargin
        anchors.bottomMargin: Theme.gridMargin
        spacing: 10

        ChargingLiveCard {
            Layout.fillWidth: true
            Layout.preferredHeight: 72
        }

        ChargingStatsGrid {
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }
}

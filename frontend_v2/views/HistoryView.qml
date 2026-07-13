import QtQuick
import QtQuick.Layouts
import frontend_v2

// History view: pick a property + a time range and read the value back from an
// interactive line graph. State (selected id + range) lives here and drives
// History.requestHistory; the property list is (re)requested whenever the view
// becomes current, so lazily-typed properties fill in as the session runs.
Rectangle {
    id: view

    property bool isCurrent: false
    color: Theme.dashboardBackground

    property string selectedId: ""
    property int rangeCode: 0
    property double customStartMs: 0
    property double customEndMs: 0
    // Live mode (from the RangeSelector toggle): a rolling, self-updating window.
    property bool live: false

    function refresh() {
        if (selectedId === "")
            return
        if (live && rangeCode !== 3) {
            // Rolling live window: seed from history, then stream from telemetry.
            History.startLive(selectedId, rangeCode)
        } else {
            // Static range (custom can't be live, so it always lands here).
            History.stopLive()
            History.requestHistory(selectedId, rangeCode, customStartMs, customEndMs)
        }
    }

    // Kept alive across switches, so the selected property + range persist (the
    // PropertySelector restores its pick by id when the list re-arrives). On
    // becoming current, refresh the property list and re-fetch / re-seed the graph
    // for the preserved selection ("update the data on show"); on leaving, pause
    // the live timer so a hidden view does no work.
    onIsCurrentChanged: {
        if (isCurrent) {
            History.requestProperties()
            refresh()
        } else {
            History.pauseLive()
        }
    }
    Component.onCompleted: if (isCurrent) History.requestProperties()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.gridMargin
        spacing: 10

        // Controls card: the property + range selectors in the same translucent-grey card the
        // Trips / Charging views wrap their selectors in, so the History view shares their look
        // instead of floating bare controls on the background. Height tracks the row's content
        // (so the custom-range date pickers, which appear inline, still fit).
        Rectangle {
            id: selectorCard
            Layout.fillWidth: true
            Layout.preferredHeight: controlsRow.implicitHeight + 16
            radius: Theme.tripCardRadius
            color: Theme.tripCardBg
            border.width: 1
            border.color: Theme.tripCardBorder

            RowLayout {
                id: controlsRow
                anchors.fill: parent
                anchors.margins: 8
                spacing: 12

                PropertySelector {
                    id: propertySelector
                    Layout.preferredWidth: 320
                    Layout.alignment: Qt.AlignVCenter
                    onPropertySelected: function(id) {
                        view.selectedId = id
                        view.refresh()
                    }
                }

                RangeSelector {
                    id: rangeSelector
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    onRangeChanged: function(code, startMs, endMs) {
                        view.rangeCode = code
                        view.customStartMs = startMs
                        view.customEndMs = endMs
                        view.refresh()
                    }
                    onLiveToggled: function(on) {
                        view.live = on
                        view.refresh()
                    }
                }
            }
        }

        HistoryGraph {
            id: historyGraph
            Layout.fillWidth: true
            Layout.fillHeight: true
            unit: propertySelector.selectedUnit
            // Per-property line render mode (config.json → History.properties). Changing the
            // selected property always triggers a fresh fetch → reloadFull(), which rebuilds
            // the path with this mode, so no separate rebuild trigger is needed.
            lineMode: propertySelector.selectedLineMode
            // Pulsing "now" marker only when this view is showing a genuinely rolling window
            // (live toggle on, not a custom range) — and paused when the view isn't current.
            live: view.isCurrent && view.live && view.rangeCode !== 3
            // Data props default to the History singleton; the graph no longer
            // self-subscribes, so drive its reload/live-advance from here.
            Connections {
                target: History
                function onHistoryReady() { historyGraph.reloadFull() }
                function onLiveTick() { historyGraph.advanceLive() }
            }
        }
    }
}

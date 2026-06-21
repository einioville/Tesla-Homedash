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

        RowLayout {
            Layout.fillWidth: true
            spacing: 12

            PropertySelector {
                id: propertySelector
                Layout.preferredWidth: 320
                onPropertySelected: function(id) {
                    view.selectedId = id
                    view.refresh()
                }
            }

            RangeSelector {
                id: rangeSelector
                Layout.fillWidth: true
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

        HistoryGraph {
            Layout.fillWidth: true
            Layout.fillHeight: true
            unit: propertySelector.selectedUnit
        }
    }
}

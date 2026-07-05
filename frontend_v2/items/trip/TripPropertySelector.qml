import QtQuick
import frontend_v2

// Graph-property dropdown for the Trips detail graph. Uses the same graphable-property
// list as the History view (History.properties — shared read-only metadata, so no
// contention), but styled with the dark TripComboBox so its popup matches the Trips
// view rather than flashing the Basic style's light popup. Tracks the pick by id so it
// survives a list refresh (the view re-requests the list on show); auto-selects the
// first entry when the list first arrives, so the graph has something to plot.
TripComboBox {
    id: combo

    model: History.properties
    textRole: "id"

    // The id the user picked, tracked independently of currentIndex so it survives a
    // model refresh (see PropertySelector for the rationale).
    property string selectedId: ""

    readonly property var currentEntry:
        (currentIndex >= 0 && model && currentIndex < model.length) ? model[currentIndex] : null
    readonly property string selectedUnit: currentEntry ? (currentEntry.unit || "") : ""

    signal propertySelected(string id)

    function indexOfId(id) {
        if (!model)
            return -1
        for (let i = 0; i < model.length; ++i)
            if (model[i].id === id)
                return i
        return -1
    }

    onActivated: function(index) {
        if (index >= 0 && index < model.length) {
            combo.selectedId = model[index].id
            propertySelected(combo.selectedId)
        }
    }

    // Keep the selection across list (re)arrivals; default to the first entry on first
    // load or if the picked property vanished, emitting so the graph reloads.
    Connections {
        target: History
        function onPropertiesChanged() {
            if (combo.count === 0)
                return
            const idx = combo.indexOfId(combo.selectedId)
            if (idx >= 0) {
                combo.currentIndex = idx
            } else {
                combo.currentIndex = 0
                combo.selectedId = combo.model[0].id
                combo.propertySelected(combo.selectedId)
            }
        }
    }
}

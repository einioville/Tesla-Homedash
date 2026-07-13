import QtQuick
import frontend_v2

// Dropdown over the graphable-property list (History.properties). Emits
// propertySelected(id) on a pick and auto-selects the first entry when the list
// first arrives, so the graph shows something without an explicit click.
//
// Extends the shared dark-themed TripComboBox (field + popup + delegate restyled to
// the translucent-grey card family), so the History controls match the Trips / Charging
// selectors instead of flashing the Basic style's light popup.
TripComboBox {
    id: combo

    model: History.properties
    textRole: "id"

    // The id the user picked, tracked independently of the model so it survives a
    // list refresh: the view re-requests History.properties every time it becomes
    // current (the list grows as new property types arrive during the session), and
    // a ComboBox keeps its numeric currentIndex — which would point at a different
    // row after the list changes. We restore by id instead, so returning to the
    // view keeps the same property selected rather than snapping back to the first.
    property string selectedId: ""

    // Currently selected property metadata, derived from the model row.
    readonly property var currentEntry:
        (currentIndex >= 0 && model && currentIndex < model.length) ? model[currentIndex] : null
    readonly property string selectedUnit: currentEntry ? (currentEntry.unit || "") : ""
    // How the graph connects this property's readings: "step" (hold, default) or "linear"
    // (point-to-point). Sourced from config.json metadata via History.properties.
    readonly property string selectedLineMode: currentEntry ? (currentEntry.line_mode || "step") : "step"

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

    // When the property list (re)arrives: keep the current selection if it is still
    // present (a programmatic currentIndex change does not re-emit, so the graph is
    // not reloaded); otherwise — first load, or the property vanished — default to
    // the first entry and load it.
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

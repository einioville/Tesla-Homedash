import QtQuick
import frontend_v2

// Dropdown over the trips detected for the selected week (Trips.trips). Each row
// shows the trip's weekday + start–end time and its distance. Emits
// tripSelected(startMs, endMs) on a pick; nothing is drawn until the user picks a
// trip, so the selection resets to "none" whenever the trip list changes.
//
// Uses the shared dark-themed TripComboBox and overrides formatEntry (rather than the
// delegate) so the rows keep the themed background — a custom delegate would drop the
// theming and bring back the white hover square.
TripComboBox {
    id: combo

    signal tripSelected(double startMs, double endMs)

    model: Trips.trips

    // No selection by default; the map draws only on an explicit pick.
    currentIndex: -1
    displayText: currentIndex < 0 ? qsTr("Valitse matka")
                                  : formatTrip(model[currentIndex])
    formatEntry: function(entry) { return formatTrip(entry) }

    function pad(n) { return n < 10 ? "0" + n : "" + n }

    function weekday(d) {
        return [qsTr("Su"), qsTr("Ma"), qsTr("Ti"), qsTr("Ke"),
                qsTr("To"), qsTr("Pe"), qsTr("La")][d.getDay()]
    }

    function formatTrip(entry) {
        if (!entry)
            return ""
        var s = new Date(entry.startMs)
        var e = new Date(entry.endMs)
        var text = weekday(s) + " " + s.getDate() + "." + (s.getMonth() + 1) + ". "
                 + pad(s.getHours()) + ":" + pad(s.getMinutes()) + "–"
                 + pad(e.getHours()) + ":" + pad(e.getMinutes())
        if (!isNaN(entry.distanceKm))
            text += "  ·  " + entry.distanceKm.toFixed(1) + " km"
        return text
    }

    // A fresh trip list (new week / reload) clears the selection: the user must
    // pick a trip again, and the route was already dropped by requestTrips.
    Connections {
        target: Trips
        function onTripsChanged() {
            combo.currentIndex = -1
        }
    }

    onActivated: function(index) {
        if (index >= 0 && index < model.length)
            tripSelected(model[index].startMs, model[index].endMs)
    }
}

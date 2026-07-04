import QtQuick
import frontend_v2

// Dropdown of recent calendar weeks (Mon–Sun, local time), each labelled with the
// number of trips detected in it. Emits weekSelected(startMs, endMs) on a pick and
// auto-selects the current week once, so the Trips view loads immediately.
//
// The list is REBUILT on show (labels + current-week end bound track wall-clock time
// on this 24/7 device) and again whenever the per-week counts arrive from the backend
// (Trips.weekCounts). The picked week is preserved across rebuilds by its start-ms.
TripComboBox {
    id: combo

    signal weekSelected(double startMs, double endMs)

    // How many weeks back to offer.
    property int weeksBack: 14
    // The start-ms of the week the user picked, tracked across model rebuilds. NaN
    // until the first selection.
    property double selectedStartMs: NaN

    textRole: "label"

    // Monday 00:00 (local) of the week `weeksAgo` weeks before today.
    function mondayOf(weeksAgo) {
        var now = new Date()
        var d = new Date(now.getFullYear(), now.getMonth(), now.getDate())  // local midnight
        var dow = (d.getDay() + 6) % 7  // 0 = Monday … 6 = Sunday
        d.setDate(d.getDate() - dow - weeksAgo * 7)
        return d
    }

    function fmt(d) {
        return d.getDate() + "." + (d.getMonth() + 1) + "."
    }

    function baseLabel(i, start, sunday) {
        var prefix = i === 0 ? qsTr("Tämä viikko") + " · "
                   : i === 1 ? qsTr("Viime viikko") + " · " : ""
        return prefix + fmt(start) + "–" + fmt(sunday)
    }

    // Trip count shown after a week's dates. For the SELECTED week the badge is the
    // actual loaded list length (Trips.trips) — so the badge and the trip dropdown
    // share one source and can never disagree for the week you're looking at (this
    // sidesteps both the boundary-crossing-trip and the stale-current-week count/list
    // divergences). Other weeks show the backend's whole-span estimate: a hint that
    // becomes exact the moment that week is selected.
    function countSuffix(startMs) {
        var c = (startMs === selectedStartMs) ? Trips.trips.length
                                              : Trips.weekCounts[String(startMs)]
        if (c === undefined)
            return ""
        return "  ·  " + c + " " + (c === 1 ? qsTr("matka") : qsTr("matkaa"))
    }

    // The week windows (start/end ms) computed fresh from the current date.
    function weekWindows() {
        var arr = []
        var nowMs = Date.now()
        for (var i = 0; i < weeksBack; ++i) {
            var start = mondayOf(i)
            var nextMonday = new Date(start.getTime())
            nextMonday.setDate(nextMonday.getDate() + 7)
            var sunday = new Date(start.getTime())
            sunday.setDate(sunday.getDate() + 6)
            arr.push({
                index: i,
                start: start,
                sunday: sunday,
                startMs: start.getTime(),
                // The current week has no future data, so cap its end at "now".
                endMs: Math.min(nextMonday.getTime(), nowMs)
            })
        }
        return arr
    }

    function buildModel() {
        return weekWindows().map(function (w) {
            return {
                label: baseLabel(w.index, w.start, w.sunday) + countSuffix(w.startMs),
                startMs: w.startMs,
                endMs: w.endMs
            }
        })
    }

    // Rebuild the model (fresh labels + counts) and restore the picked week by its
    // start-ms — no re-emit, so a rebuild never reloads the drawn route.
    function rebuild() {
        var arr = buildModel()
        model = arr
        var idx = -1
        if (!isNaN(selectedStartMs)) {
            for (var i = 0; i < arr.length; ++i) {
                if (arr[i].startMs === selectedStartMs) {
                    idx = i
                    break
                }
            }
        }
        currentIndex = idx >= 0 ? idx : (arr.length > 0 ? 0 : -1)
    }

    // Called by the view when it becomes current: refresh weeks + re-fetch counts.
    function refresh() {
        rebuild()
        Trips.requestWeekCounts(model)
    }

    // Relabel when the counts OR the selected week's trip list change (the selected
    // week's badge is driven by Trips.trips) — but NOT while the dropdown is open:
    // reassigning `model` rebuilds the open popup and resets its hover/scroll. A
    // rebuild requested while open is deferred until the popup closes.
    property bool pendingRebuild: false

    function rebuildOrDefer() {
        if (popup.visible)
            pendingRebuild = true
        else
            rebuild()
    }

    Connections {
        target: Trips
        function onWeekCountsChanged() { combo.rebuildOrDefer() }
        function onTripsChanged() { combo.rebuildOrDefer() }
    }

    Connections {
        target: combo.popup
        function onClosed() {
            if (combo.pendingRebuild) {
                combo.pendingRebuild = false
                combo.rebuild()
            }
        }
    }

    // First build: select + load this week. Counts are fetched by the view's first
    // refresh() (onIsCurrent), which always fires right after this.
    Component.onCompleted: {
        rebuild()
        if (count > 0 && isNaN(selectedStartMs)) {
            currentIndex = 0
            selectedStartMs = model[0].startMs
            weekSelected(model[0].startMs, model[0].endMs)
        }
    }

    onActivated: function(index) {
        if (index >= 0 && index < model.length) {
            selectedStartMs = model[index].startMs
            weekSelected(model[index].startMs, model[index].endMs)
        }
    }
}

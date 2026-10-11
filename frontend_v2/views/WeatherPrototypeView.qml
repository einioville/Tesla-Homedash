import QtQuick
import frontend_v2
import "../items/weather/prototype/WeatherProtoSnapshot.js" as Snap

// PROTOTYPE — the Weather view ("Sää"): variant A of the prototype round (B "Aikajana" and
// C "Tutka" were dropped), over one real FMI snapshot from
// items/weather/prototype/fetch_snapshot.py. Only the radar loop and its lightning are live.
// Throwaway: lives on prototype/weather-view only.
Rectangle {
    id: view

    property bool isCurrent: false
    color: "#0b0e12"

    // No warning covers the place right now. Set true (e.g. from the screenshot probe) to
    // mark the most relevant nationwide one as if it did, to see the warning state.
    property bool demoWarning: false
    // Likewise a made-up storm's lightning on the radar, there being none on most days.
    property bool demoLightning: false

    readonly property var wx: {
        var d = Snap.data
        if (!demoWarning || !d.warnings.length)
            return d
        var pick = Math.max(0, d.warnings.findIndex(w => (w.event || "").toLowerCase().indexOf("liikenne") >= 0))
        return Object.assign({}, d, {
            warnings: d.warnings.map((w, i) => i === pick ? Object.assign({}, w, { appliesHere: true }) : w)
        })
    }

    WeatherProtoDashboard {
        anchors.fill: parent
        wx: view.wx
        active: view.isCurrent
        demoLightning: view.demoLightning
    }
}

import QtQuick
import frontend_v2

// The Weather view ("Sää"), over the backend's WEATHER_VIEW document (`Weather.view`,
// refreshed every 10 minutes); the radar loop and its lightning come straight from FMI.
// Until the first document arrives there is nothing to lay out, so the dashboard waits.
Rectangle {
    id: view

    property bool isCurrent: false
    color: "#0b0e12"

    // No warning covers the place right now. Set true (e.g. from the screenshot probe) to
    // mark the most relevant nationwide one as if it did, to see the warning state.
    property bool demoWarning: false
    // Likewise a made-up storm's lightning on the radar, there being none on most days.
    property bool demoLightning: false
    // And a SmartSymbol (e.g. 1 clear, 77 thunder; 100 and up for night) to colour the backdrop
    // by in place of the current weather.
    property int demoSymbol: 0

    readonly property var wx: {
        var d = Weather.view
        var warnings = d.warnings || []
        if (!demoWarning || !warnings.length)
            return d
        var pick = Math.max(0, warnings.findIndex(w => (w.event || "").toLowerCase().indexOf("liikenne") >= 0))
        return Object.assign({}, d, {
            warnings: warnings.map((w, i) => i === pick ? Object.assign({}, w, { appliesHere: true }) : w)
        })
    }

    Loader {
        anchors.fill: parent
        active: Weather.hasView
        sourceComponent: WeatherDashboard {
            wx: view.wx
            active: view.isCurrent
            demoLightning: view.demoLightning
            demoSymbol: view.demoSymbol
        }
    }

    Text {
        anchors.centerIn: parent
        visible: !Weather.hasView
        text: qsTr("Säätietoja haetaan…")
        color: "#8f9aa6"
        font.family: Theme.fontFamily
        font.pixelSize: 16
    }
}

import QtQuick
import frontend_v2

// The Weather view ("Sää"), over the backend's WEATHER_VIEW document (`Weather.view`,
// refreshed every 10 minutes); the radar loop and its lightning come straight from FMI.
// Until the first document arrives there is nothing to lay out, so the dashboard waits.
Rectangle {
    id: view

    property bool isCurrent: false
    color: "#0b0e12"

    Loader {
        anchors.fill: parent
        active: Weather.hasView
        sourceComponent: WeatherDashboard {
            wx: Weather.view
            active: view.isCurrent
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

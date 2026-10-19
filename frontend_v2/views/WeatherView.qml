import QtQuick
import frontend_v2

// The Weather view ("Sää"), over the backend's WEATHER_VIEW document (`Weather.view`,
// refreshed every 10 minutes); the radar loop and its lightning come straight from FMI.
// Until the first document arrives there is nothing to lay out, so the dashboard waits.
// The Nyt card's camera button opens the road cameras nearest the document's place, and its
// warning strip the warnings that apply there, both on frosted glass over the dashboard.
Rectangle {
    id: view

    property bool isCurrent: false
    color: "#0b0e12"

    // How many of the nearest cameras the dialog steps through.
    readonly property int nearestCameras: 10
    // The button was pressed before the camera list arrived; open it when it does.
    property bool camerasWanted: false

    function openCameras() {
        if (!cameraStations.stations.length) {
            camerasWanted = true
            cameraStations.fetch()
            return
        }
        camerasWanted = false
        var meta = Weather.view.meta
        cameraPopup.openNearest(cameraStations.nearest(meta.lat, meta.lon, nearestCameras))
    }

    onIsCurrentChanged: {
        if (!isCurrent) {
            camerasWanted = false
            cameraPopup.close()
            warningsPopup.close()
        }
    }

    Loader {
        id: dashboard
        anchors.fill: parent
        active: Weather.hasView
        sourceComponent: WeatherDashboard {
            wx: Weather.view
            active: view.isCurrent
            interactive: !cameraPopup.visible && !warningsPopup.visible
            onCamerasRequested: view.openCameras()
            onWarningsRequested: warningsPopup.open()
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

    RoadCameraStations {
        id: cameraStations
        active: view.isCurrent
        onStationsChanged: if (view.camerasWanted) view.openCameras()
    }

    FrostLayer {
        id: frost
        sourceItem: dashboard
        live: view.isCurrent && (cameraPopup.visible || warningsPopup.visible)
        blurMax: Theme.dialogFrostBlur
        brightness: Theme.dialogFrostBrightness
    }

    RoadCameraPopup {
        id: cameraPopup
        backdrop: dashboard
        frost: frost
    }

    WeatherWarningsPopup {
        id: warningsPopup
        backdrop: dashboard
        frost: frost
        place: Weather.view.meta ? Weather.view.meta.place : ""
        warnings: dashboard.item ? dashboard.item.here : []
    }
}

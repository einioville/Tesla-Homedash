import QtQuick
import frontend_v2

// The Weather view ("Sää"), over the backend's WEATHER_VIEW document (`Weather.view`,
// refreshed every 10 minutes); the radar loop and its lightning come straight from FMI.
// Until the first document arrives there is nothing to lay out, so the dashboard waits.
// The Nyt card's camera button opens the road cameras round the home (Theme.roadCameraRadiusKm),
// and its warning strip the warnings that apply at the document's place, both on frosted glass
// over the dashboard.
Rectangle {
    id: view

    property bool isCurrent: false
    color: "#0b0e12"

    // The button was pressed before the camera list arrived; open it when it does.
    property bool camerasWanted: false

    function openCameras() {
        if (!RoadCameraStations.stations.length) {
            camerasWanted = true
            RoadCameraStations.ensure()
            return
        }
        camerasWanted = false
        // With no home set, the place the weather is for.
        var place = Settings.valueOf("home") || Weather.view.meta
        cameraPopup.openNearest(RoadCameraStations.within(place.lat, place.lon, Theme.roadCameraRadiusKm))
    }

    onIsCurrentChanged: {
        if (isCurrent) {
            RoadCameraStations.ensure()
        } else {
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

    Connections {
        target: RoadCameraStations
        function onStationsChanged() {
            if (view.camerasWanted)
                view.openCameras()
        }
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

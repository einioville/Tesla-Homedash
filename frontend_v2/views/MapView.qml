import QtQuick
import frontend_v2

// Full-screen map view (*Kartta*): the dashboard's TeslaMap blown up to fill the whole
// surface, with layers switched from the menu in the bottom-right corner (MapLayerMenu): the
// live data card in the bottom-left, the drive under way, OSM place names, and FMI's radar
// with its timeline at the top. Corners are left square (roundedCorners: false) — the map IS
// the view, so there's no surrounding card for rounded corners to blend into.
//
// isCurrent is forwarded to the map so it freezes its follow animation + center
// binding while this view is hidden: the ViewController keeps this view (and its
// own TeslaMap instance, separate from the dashboard's) resident but frozen, so
// returning to it is instant with no per-frame work while away.
Rectangle {
    id: view

    property bool isCurrent: false
    color: Theme.dashboardBackground

    readonly property bool showStats: Settings.values.mapLayerStats === true
    readonly property bool showRadar: Settings.values.mapLayerRadar === true
    readonly property bool showRoute: Settings.values.mapLayerRoute === true
    readonly property bool showPlaces: Settings.values.mapLayerPlaces === true

    onIsCurrentChanged: if (!isCurrent) layerMenu.open = false

    Binding {
        target: CurrentDrive
        property: "watched"
        value: view.isCurrent && view.showRoute
    }

    TeslaMap {
        id: map
        anchors.fill: parent
        roundedCorners: false
        isCurrent: view.isCurrent
        showRadar: view.showRadar
        showRoute: view.showRoute
        showPlaceNames: view.showPlaces
    }

    WeatherRadarControls {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 20
        visible: map.radar !== null
        radar: map.radar
        backdrop: map
        rimWidth: 0.75
        highlight: false
    }

    MapLiveStats {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 20
        visible: view.showStats
        active: view.isCurrent && visible
        backdrop: map
    }

    MapLayerMenu {
        id: layerMenu
        anchors.fill: parent
        backdrop: map
    }
}

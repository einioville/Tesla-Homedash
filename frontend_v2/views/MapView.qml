import QtQuick
import frontend_v2

// Full-screen map view (*Kartta*): the dashboard's TeslaMap blown up to fill the whole
// surface, with layers switched from the menu in the bottom-right corner (MapLayerMenu): the
// live data card in the bottom-left, the drive under way, OSM place names, and FMI's radar —
// a minimap in the top-right corner, an overlay or both, the overlay alone with its timeline
// upright on the left edge; zoom buttons sit over the layer button. Corners are left square
// (roundedCorners: false) — the map IS the view, so there's no surrounding card for rounded
// corners to blend into.
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
    readonly property bool showWarnings: Settings.values.mapLayerWarnings === true
    readonly property bool showCameras: Settings.values.mapLayerCameras === true
    readonly property var warnings: (Weather.view.warnings || []).filter(w => (w.shapes || []).length > 0)

    onIsCurrentChanged: {
        if (!isCurrent) {
            layerMenu.open = false
            warningsPopup.close()
            cameraPopup.close()
        }
    }

    TeslaMap {
        id: map
        anchors.fill: parent
        roundedCorners: false
        isCurrent: view.isCurrent
        showRadar: view.showRadar
        radarInset: Settings.values.mapRadarInset === true
        radarOverlay: Settings.values.mapRadarOverlay === true
        radarHistoryMin: Settings.values.mapRadarHistory
        radarInsetAlignment: Qt.AlignRight | Qt.AlignTop
        radarInsetSize: Qt.size(300, 220)
        radarInsetMargin: 20
        showWarnings: view.showWarnings
        showCameras: view.showCameras
        onCameraOpened: (stationId) => cameraPopup.open(stationId)
        showRoute: view.showRoute
        interactive: !cameraPopup.visible && !warningsPopup.visible
    }

    // The frosted glass of every panel over the map, made once.
    FrostLayer {
        id: frost
        sourceItem: map
        live: view.isCurrent
    }

    // For the overlay alone: the minimap carries the frame's time and the loop's ticks. Over
    // the live data card when it shows, in the corner otherwise.
    WeatherRadarControls {
        anchors.left: parent.left
        anchors.leftMargin: 20
        anchors.bottom: stats.visible ? stats.top : parent.bottom
        anchors.bottomMargin: stats.visible ? 12 : 20
        vertical: true
        visible: map.radar !== null && !map.radarInset
        radar: map.radar
        backdrop: map
        frost: frost
        rimWidth: 0.75
        highlight: false
    }

    MapLiveStats {
        id: stats
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 20
        visible: view.showStats
        active: view.isCurrent && visible
        backdrop: map
        frost: frost
    }

    WarningLegend {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 20
        visible: view.showWarnings && view.warnings.length > 0
        active: view.isCurrent && visible
        warnings: view.warnings
        backdrop: map
        frost: frost
        onTapped: warningsPopup.open()
    }

    // Over the layer button. The layer menu opens over both.
    MapZoomButtons {
        x: layerMenu.toggleButton.x + (layerMenu.toggleButton.width - width) / 2
        y: layerMenu.toggleButton.y - height - 12
        teslaMap: map
        frost: frost
    }

    MapLayerMenu {
        id: layerMenu
        anchors.fill: parent
        backdrop: map
        frost: frost
        layers: [
            { key: "mapLayerStats", label: qsTr("Ajotiedot") },
            { key: "mapLayerRoute", label: qsTr("Ajettu reitti") },
            { key: "mapLayerCameras", label: qsTr("Kelikamerat") },
            { key: "mapLayerRadar", label: qsTr("Sadetutka"),
              modes: [{ key: "mapRadarInset", label: qsTr("Minikartta") },
                      { key: "mapRadarOverlay", label: qsTr("Kartan päällä") }],
              choice: { key: "mapRadarHistory", label: qsTr("Historia"), options: Theme.radarHistoryChoices } },
            { key: "mapLayerWarnings", label: qsTr("Säävaroitukset") }
        ]
    }

    // The dialogs' glass blurs further than the panels', so they have a frost of their own.
    FrostLayer {
        id: popupFrost
        sourceItem: map
        live: view.isCurrent && (cameraPopup.visible || warningsPopup.visible)
        blurMax: Theme.dialogFrostBlur
        brightness: Theme.dialogFrostBrightness
    }

    RoadCameraPopup {
        id: cameraPopup
        backdrop: map
        frost: popupFrost
    }

    WeatherWarningsPopup {
        id: warningsPopup
        backdrop: map
        frost: popupFrost
        warnings: view.warnings
    }
}

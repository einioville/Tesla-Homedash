import QtQuick
import QtLocation
import QtPositioning
import frontend_v2

// The Weather view's radar card: FMI's radar composite and lightning (RadarLayer) looping over
// a basemap that can be panned and zoomed.
//
// Gestures are TripMap's: one-finger pan, pinch and wheel zoom, scaled by the shared map
// sensitivity; the frames wait for a gesture to end before they are fetched for the new view.
// The zoom stays between minimumZoom and maximumZoom, and the centre within the radar's
// coverage, so the map cannot be lost somewhere the radar does not reach. Like the home map, it
// glides back to the place on its own once left alone for the *Keskitysviive*
// (Theme.mapFollowResumeSec), and is back there whenever the view is opened again.
//
// The basemap here is always EOX Sentinel-2 (BasemapPlugin's satellite type), not the app's
// MML orthophoto: a regional radar view reaches past MML's coverage near any coast, and at
// radar zoom Sentinel-2's 10 m is plenty.
Item {
    id: root

    property real latitude: 61.499
    property real longitude: 23.787
    property real zoom: 7.6
    // The zoom gestures can reach: 5 fits the whole composite (all of Finland) in the card,
    // 10 a town and its surroundings, about where the radar's own resolution runs out.
    property real minimumZoom: 5
    property real maximumZoom: 10
    // Where the place sits, in pixels from the map's centre, so it can be kept clear of
    // the controls laid over the map.
    property point placeOffset: Qt.point(0, 0)
    property bool active: true
    property bool latestOnly: false
    // Off while a dialog lies over the map (TeslaMap.interactive says why).
    property bool interactive: true
    readonly property alias radarLayer: radarLayer
    // The radars' reach, about: the map's centre stays inside it, so a pan cannot leave the
    // radar behind.
    readonly property var coverage: ({ south: 59.5, north: 69.5, west: 20, east: 31 })

    // The place on screen now, following the map.
    readonly property point placePt: {
        map.center; map.zoomLevel; map.width; map.height
        return map.mapReady ? map.fromCoordinate(QtPositioning.coordinate(latitude, longitude), false)
                            : Qt.point(-100, -100)
    }
    // Off the place or its zoom, so the way back is offered.
    readonly property bool moved: map.mapReady
                                  && (Math.abs(map.zoomLevel - zoom) > 0.01
                                      || Math.abs(placePt.x - (width / 2 + placeOffset.x)) > 2
                                      || Math.abs(placePt.y - (height / 2 + placeOffset.y)) > 2)

    clip: true

    onLatitudeChanged: Qt.callLater(goHome)
    onLongitudeChanged: Qt.callLater(goHome)
    onActiveChanged: {
        if (!active) {
            returnTimer.stop()
            if (moved)
                goHome()
        }
    }

    // A gesture holds the map where it is; letting go starts the wait to go back.
    function gestureActive(isActive) {
        if (isActive) {
            homeAnim.stop()
            returnTimer.stop()
        } else if (moved) {
            returnTimer.restart()
        }
    }

    // The centre that puts the place at placeOffset at the given zoom.
    function homeCenter(z) {
        var mpp = 156543.03392 / Math.pow(2, z)
        var home = radarLayer.merc({ latitude: latitude, longitude: longitude })
        return radarLayer.unmerc(home.x - placeOffset.x * mpp, home.y + placeOffset.y * mpp)
    }

    // The Map's own minimumZoomLevel and maximumZoomLevel do not hold it there (the OSM plugin
    // takes any zoom it is given), so the gestures clamp it themselves.
    function zoomTo(z) {
        map.zoomLevel = Math.max(minimumZoom, Math.min(maximumZoom, z))
    }

    function clampCenter(c) {
        return QtPositioning.coordinate(Math.max(coverage.south, Math.min(coverage.north, c.latitude)),
                                        Math.max(coverage.west, Math.min(coverage.east, c.longitude)))
    }

    // Straight to the place at its zoom: on start and when the place changes.
    function goHome() {
        if (!map.mapReady || map.width <= 0 || map.height <= 0)
            return
        homeAnim.stop()
        map.zoomLevel = zoom
        map.center = homeCenter(zoom)
        radarLayer.check()
    }

    // Glides back, for the button.
    function returnHome() {
        homeAnim.stop()
        homeCenterAnim.to = homeCenter(zoom)
        homeZoomAnim.to = zoom
        homeAnim.start()
    }

    BasemapPlugin {
        id: osmPlugin
    }

    Map {
        id: map
        anchors.fill: parent
        plugin: osmPlugin
        zoomLevel: root.zoom
        // Not 0: at a whole zoom and bearing 0 the tiles are filtered Nearest and step in whole
        // pixels under the radar, which moves smoothly (items/tesla/CLAUDE.md).
        bearing: 0.001
        copyrightsVisible: false
        center: QtPositioning.coordinate(root.latitude, root.longitude)

        onMapReadyChanged: Qt.callLater(root.goHome)

        // EOX's imagery always, the same tiles the other maps show outside Finland.
        BasemapSwitch {
            geoMap: map
            allowMml: false
        }

        DragHandler {
            id: panHandler
            enabled: root.interactive
            target: null
            minimumPointCount: 1
            maximumPointCount: 1
            dragThreshold: 0
            property point lastCentroid
            onActiveChanged: {
                if (active)
                    lastCentroid = centroid.position
                root.gestureActive(active)
            }
            onCentroidChanged: {
                if (!active)
                    return
                var from = map.toCoordinate(lastCentroid, false)
                var to = map.toCoordinate(centroid.position, false)
                map.center = root.clampCenter(QtPositioning.coordinate(
                    map.center.latitude + (from.latitude - to.latitude) * Theme.mapSensitivity,
                    map.center.longitude + (from.longitude - to.longitude) * Theme.mapSensitivity))
                lastCentroid = centroid.position
            }
        }

        WheelHandler {
            enabled: root.interactive
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: function(event) {
                root.gestureActive(true)
                root.zoomTo(map.zoomLevel + event.angleDelta.y / 120 * 0.5 * Theme.mapSensitivity)
                root.gestureActive(false)
            }
        }

        PinchHandler {
            id: pinchHandler
            enabled: root.interactive
            target: null
            minimumPointCount: 2
            property real startZoom: root.zoom
            onActiveChanged: {
                if (active)
                    startZoom = map.zoomLevel
                root.gestureActive(active)
            }
            onActiveScaleChanged: {
                if (!active)
                    return
                root.zoomTo(startZoom + Math.log2(activeScale) * Theme.mapSensitivity)
            }
        }
    }

    Timer {
        id: returnTimer
        interval: Theme.mapFollowResumeSec * 1000
        onTriggered: root.returnHome()
    }

    ParallelAnimation {
        id: homeAnim
        CoordinateAnimation {
            id: homeCenterAnim
            target: map
            property: "center"
            duration: 500
            easing.type: Easing.OutCubic
        }
        NumberAnimation {
            id: homeZoomAnim
            target: map
            property: "zoomLevel"
            duration: 500
            easing.type: Easing.OutCubic
        }
    }

    RadarLayer {
        id: radarLayer
        anchors.fill: parent
        geoMap: map
        active: root.active
        latestOnly: root.latestOnly
        holdFetch: panHandler.active || pinchHandler.active
    }

    // Home marker, above the radar.
    Rectangle {
        x: root.placePt.x - width / 2
        y: root.placePt.y - height / 2
        width: 16
        height: 16
        radius: 8
        color: Theme.accent
        border.color: "white"
        border.width: 2
    }

    // Back to the place and its zoom, offered once the map has been moved.
    Rectangle {
        id: homeButton
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 10
        width: 36
        height: 36
        radius: 18
        color: homeTap.pressed ? "#cc2a3038" : "#99161a20"
        border.color: "#40ffffff"
        border.width: 1
        opacity: root.moved ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 260 } }

        Image {
            anchors.centerIn: parent
            width: 20
            height: 20
            source: "qrc:/resources/icons/location.svg"
            sourceSize: Qt.size(40, 40)
        }
        MouseArea {
            id: homeTap
            anchors.fill: parent
            anchors.margins: -6
            onClicked: {
                returnTimer.stop()
                root.returnHome()
            }
        }
    }
}

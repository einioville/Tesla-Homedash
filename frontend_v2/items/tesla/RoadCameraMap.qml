import QtQuick
import QtQuick.Effects
import QtLocation
import QtPositioning
import frontend_v2

// Where a road camera is, in RoadCameraPopup: a north-up map centred on the camera at `zoom`,
// with the OSM place names, the home and the car, so a camera named by its road and junction can
// be placed. Nothing else is drawn on it. It pans and zooms as the Koti dialog's map does, scaled
// by the shared map sensitivity, and goes back to the camera and `zoom` when the camera changes:
// a step from one camera to the next flies there (`fly`), while one placed with the dialog closed
// or after an unknown spot is a cut. An invalid `coordinate` (a camera still loading) hides the
// marker and leaves the map where it was.
Item {
    id: root

    property var coordinate: QtPositioning.coordinate()
    property bool active: true
    // Suburbs are named from 12 (PlaceNames), and at 61° a 336 px map spans about 6 km.
    readonly property real zoom: 12
    readonly property real minimumZoom: 6
    // EOX, the imagery past MML's coverage, has no zoom 19.
    readonly property real maximumZoom: 18
    readonly property int radius: 10
    // The coordinate before the latest, to tell a step between cameras from a first placing.
    property var previous: QtPositioning.coordinate()

    // The OSM plugin takes any zoom it is given, so the gestures clamp it themselves.
    function zoomTo(level) {
        fly.stop()
        map.zoomLevel = Math.max(minimumZoom, Math.min(maximumZoom, level))
    }

    function place() {
        fly.stop()
        map.zoomLevel = zoom
        map.center = coordinate
    }

    Component.onCompleted: {
        previous = coordinate
        if (coordinate.isValid)
            place()
    }

    onCoordinateChanged: {
        var from = previous
        previous = coordinate
        if (!coordinate.isValid)
            return
        if (!active || !from.isValid || !map.mapReady) {
            place()
            return
        }
        // Out far enough that the way is about half the map, no farther than a pinch can go,
        // so the map shows where the next camera lies from the last instead of a blur of tiles.
        var at = map.fromCoordinate(coordinate, false)
        var px = Math.hypot(at.x - map.width / 2, at.y - map.height / 2)
        if (!isFinite(px)) {
            place()
            return
        }
        var out = Math.max(minimumZoom, Math.min(map.zoomLevel, zoom,
                                                 map.zoomLevel - Math.log2(px / (Math.min(map.width, map.height) / 2))))
        flyCenter.to = coordinate
        flyOut.to = out
        fly.ms = Math.min(1600, 600 + 150 * (Math.max(map.zoomLevel, zoom) - out))
        fly.restart()
    }

    ParallelAnimation {
        id: fly
        // The whole flight, longer the farther out it goes.
        property int ms: 600
        CoordinateAnimation {
            id: flyCenter
            target: map
            property: "center"
            duration: fly.ms
            easing.type: Easing.InOutCubic
        }
        SequentialAnimation {
            NumberAnimation {
                id: flyOut
                target: map
                property: "zoomLevel"
                duration: fly.ms / 2
                easing.type: Easing.InOutQuad
            }
            NumberAnimation {
                target: map
                property: "zoomLevel"
                to: root.zoom
                duration: fly.ms / 2
                easing.type: Easing.InOutQuad
            }
        }
    }

    Item {
        anchors.fill: parent
        layer.enabled: true
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: mask
            // RoundedImage's: a smooth edge, not one the mask's antialiasing leaves jagged.
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
        }

        BasemapPlugin {
            id: basemap
        }

        Map {
            id: map
            anchors.fill: parent
            plugin: basemap
            zoomLevel: root.zoom
            copyrightsVisible: false

            BasemapSwitch {
                geoMap: map
                active: root.active
            }

            DragHandler {
                target: null
                maximumPointCount: 1
                property point last
                onActiveChanged: {
                    last = Qt.point(0, 0)
                    if (active)
                        fly.stop()
                }
                onTranslationChanged: {
                    map.pan((last.x - translation.x) * Theme.mapSensitivity,
                            (last.y - translation.y) * Theme.mapSensitivity)
                    last = translation
                }
            }

            PinchHandler {
                target: null
                property real startZoom: root.zoom
                onActiveChanged: if (active) { fly.stop(); startZoom = map.zoomLevel }
                onActiveScaleChanged: if (active) root.zoomTo(startZoom + Math.log2(activeScale) * Theme.mapSensitivity)
            }

            WheelHandler {
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                onWheel: (event) => root.zoomTo(map.zoomLevel + event.angleDelta.y / 120 * 0.5 * Theme.mapSensitivity)
            }

            PlaceLabels {
                geoMap: map
                active: root.active
            }

            HomeMarker {}

            // The car as the telemetry has it; the map is north-up, so the heading is the arrow's turn.
            MapQuickItem {
                visible: Tesla.location && Tesla.location.latitude !== undefined
                z: 6
                coordinate: visible ? QtPositioning.coordinate(Tesla.location.latitude, Tesla.location.longitude)
                                    : QtPositioning.coordinate()
                rotation: Tesla.gpsHeading
                anchorPoint.x: carIcon.width / 2
                anchorPoint.y: carIcon.height / 2
                sourceItem: Image {
                    id: carIcon
                    width: 24
                    height: 24
                    source: "qrc:/resources/icons/arrow.svg"
                    sourceSize: Qt.size(48, 48)
                    smooth: true
                }
            }

            MapQuickItem {
                visible: root.coordinate.isValid
                // Over the home and the car: the camera is what this map is for.
                z: 7
                coordinate: root.coordinate
                anchorPoint.x: 17
                anchorPoint.y: 17
                // RoadCameras' marker, in the accent the chosen tab is drawn in.
                sourceItem: Rectangle {
                    width: 34
                    height: 34
                    radius: 17
                    color: Theme.accent
                    border.color: "white"
                    border.width: 1.5

                    TintedIcon {
                        anchors.centerIn: parent
                        iconSize: 18
                        source: "qrc:/resources/icons/camera.svg"
                    }
                }
            }
        }
    }

    Rectangle {
        id: mask
        anchors.fill: parent
        radius: root.radius
        visible: false
        layer.enabled: true
    }

    Rectangle {
        anchors.fill: parent
        radius: root.radius
        color: "transparent"
        border.color: "#40ffffff"
        border.width: 1
    }
}

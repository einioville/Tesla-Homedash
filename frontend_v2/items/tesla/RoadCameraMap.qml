import QtQuick
import QtQuick.Effects
import QtLocation
import QtPositioning
import frontend_v2

// Where a road camera is, in RoadCameraPopup: a still, north-up map centred on the camera at
// `zoom`, with the OSM place names and the home, so a camera named by its road and junction can
// be placed. It takes no input, and nothing moves it but the camera it shows; an invalid
// `coordinate` (a camera still loading) hides the marker and leaves the map where it was.
Item {
    id: root

    property var coordinate: QtPositioning.coordinate()
    property bool active: true
    // Suburbs are named from 12 (PlaceNames), and at 61° a 336 px map spans about 6 km.
    readonly property real zoom: 12
    readonly property int radius: 10

    onCoordinateChanged: {
        if (coordinate.isValid)
            map.center = coordinate
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

            PlaceLabels {
                geoMap: map
                active: root.active
            }

            HomeMarker {}

            MapQuickItem {
                visible: root.coordinate.isValid
                // Over the home: the camera is what this map is for.
                z: 6
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

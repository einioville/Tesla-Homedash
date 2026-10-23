import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
import QtLocation
import QtPositioning
import frontend_v2

// A map's radar as a minimap in its corner (#86): FMI's radar and lightning (RadarLayer) over a
// small north-up map far enough out for the composite's ~500 m cells to read as weather. Laid
// over the map itself at the dashboard card's zoom, one cell is a third of the card, and a light
// shower turns all of it green. It is centred on the big map's centre, outlines the area the big
// map shows while that is large enough to see, and marks the car. The frame's time is in the
// top-left corner and the loop's place along the bottom edge. A tap opens the Weather view.
//
// Its zoom is `zoomOut` levels out from the big map's, never closer than `maximumZoom`, where
// a cell is about two pixels. Its centre moves in whole pixels of its own, so a big map that
// follows the car redraws it only when the view has moved a pixel at its scale (at zoom 8 a car
// at 100 km/h covers one in about 10 s), not every frame; at a whole zoom and bearing 0 the
// tiles are drawn in whole pixels anyway (items/tesla/CLAUDE.md). The basemap is EOX's, as on
// the Weather view's radar map: at this zoom MML's 0.5 m orthophoto would be wasted.
Item {
    id: root

    // The big map (TeslaMap's Map), whose view is outlined.
    property Map mainMap: null
    property bool active: true
    // The car as the telemetry has it, not eased: its marker moves with each fix, not every
    // frame. An invalid coordinate hides it.
    property var car: QtPositioning.coordinate()
    property real heading: 0
    property alias frameCount: radarLayer.frameCount
    property alias frameMs: radarLayer.frameMs
    property alias newestFrameMs: radarLayer.newestFrameMs
    property alias latestOnly: radarLayer.latestOnly
    readonly property alias radar: radarLayer

    readonly property int zoomOut: 3
    readonly property int maximumZoom: 8
    // The big map's view is outlined from this size up, in px a side; smaller, the car marker
    // stands for it.
    readonly property real outlineMinSize: 16
    readonly property int radius: 10

    readonly property int zoom: mainMap
                                ? Math.max(1, Math.min(Math.round(mainMap.zoomLevel) - zoomOut, maximumZoom))
                                : maximumZoom
    readonly property real metresPerPixel: 156543.03392 / Math.pow(2, zoom)
    // The big map's centre in whole pixels at this zoom, EPSG:3857.
    readonly property int centreX: mainMap ? Math.round(radarLayer.merc(mainMap.center).x / metresPerPixel) : 0
    readonly property int centreY: mainMap ? Math.round(radarLayer.merc(mainMap.center).y / metresPerPixel) : 0

    // The big map's corners on this map, closed; empty while the outline would be too small.
    readonly property var outline: {
        if (!mainMap || !mainMap.mapReady || !map.mapReady)
            return []
        var scale = Math.pow(2, zoom - mainMap.zoomLevel)
        if (Math.min(mainMap.width, mainMap.height) * scale < outlineMinSize)
            return []
        mainMap.center; mainMap.bearing; map.center; map.width; map.height
        var w = mainMap.width
        var h = mainMap.height
        return [Qt.point(0, 0), Qt.point(w, 0), Qt.point(w, h), Qt.point(0, h), Qt.point(0, 0)]
            .map(p => map.fromCoordinate(mainMap.toCoordinate(p, false), false))
    }

    Item {
        id: face
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
            center: radarLayer.unmerc(root.centreX * root.metresPerPixel, root.centreY * root.metresPerPixel)
            copyrightsVisible: false

            BasemapSwitch {
                geoMap: map
                active: root.active
                allowMml: false
            }
        }

        RadarLayer {
            id: radarLayer
            anchors.fill: parent
            geoMap: map
            active: root.active
            // The centre moves a pixel at a time, so a wide margin keeps one box for long.
            margin: 0.5
            maxImageSize: 1024
            dim: 0.35
        }

        Shape {
            anchors.fill: parent
            visible: root.outline.length > 0
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: "white"
                strokeWidth: 1.5
                fillColor: "#1fffffff"
                joinStyle: ShapePath.RoundJoin
                PathPolyline { path: root.outline }
            }
        }

        Image {
            readonly property point at: {
                map.center; map.zoomLevel; map.width; map.height
                return root.car.isValid && map.mapReady ? map.fromCoordinate(root.car, false)
                                                        : Qt.point(-100, -100)
            }
            x: at.x - width / 2
            y: at.y - height / 2
            width: 14
            height: 14
            source: "qrc:/resources/icons/arrow.svg"
            sourceSize: Qt.size(28, 28)
            // The minimap is north-up, so the heading is the arrow's turn.
            rotation: root.heading
            smooth: true
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
        border.color: "#73ffffff"
        border.width: 1
    }

    Rectangle {
        x: 6
        y: 6
        width: time.implicitWidth + 14
        height: 20
        radius: 10
        color: "#a6161a20"

        Text {
            id: time
            anchors.centerIn: parent
            text: Qt.formatTime(radarLayer.frameTime, "HH:mm")
            color: "white"
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }
    }

    // The loop: a tick per frame, lit up to the one shown, as on the Kartta view's bar.
    Rectangle {
        visible: !radarLayer.latestOnly
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 6
        height: 11
        radius: 5.5
        color: "#a6161a20"

        Row {
            id: ticks
            anchors.fill: parent
            anchors.leftMargin: 5
            anchors.rightMargin: 5
            spacing: 2

            Repeater {
                model: radarLayer.frameCount

                Rectangle {
                    required property int index
                    anchors.verticalCenter: parent.verticalCenter
                    width: (ticks.width - ticks.spacing * (radarLayer.frameCount - 1)) / radarLayer.frameCount
                    height: index === radarLayer.frame ? 5 : 3
                    radius: height / 2
                    color: index <= radarLayer.frame ? Theme.accent : "#40ffffff"
                }
            }
        }
    }

    // Holds the press, so a tap with a finger that moves a little does not pan the map below.
    MouseArea {
        anchors.fill: parent
        preventStealing: true
        onClicked: Navigation.open("weather")
    }
}

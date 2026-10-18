import QtQuick
import QtQuick.Shapes
import QtPositioning
import frontend_v2

// The drive under way (CurrentDrive) on a TeslaMap, coloured by speed on the Trips map's scale
// (Theme.speedColor), each segment by the mean of its two fixes. Declare it inside the Map;
// the stretch from the last fix to the car arrow is the map's own two-point line.
//
// A MapPolyline is rebuilt on every camera change, which a following map makes every frame,
// and a line per colour would multiply that. So the drive is one Shape in EPSG:3857 metres from
// its first fix, a ShapePath per speed band holding that band's runs, and the Shape is moved,
// scaled and turned with the map instead: a frame costs one projection, and the paths are
// rebuilt only when the zoom changes their stroke width or a fix arrives. A new fix extends
// the runs of the band it falls in and leaves the other bands alone; a reply that replaces the
// path (CurrentDrive.generation) starts them over.
Item {
    id: root

    // Not `map`: a binding `map: map` can read this property itself.
    property Item geoMap: null

    readonly property int bands: 10
    readonly property real bandKmh: Theme.tripMaxSpeedKmh / bands

    // EPSG:3857 metres of the drive's first fix, and the fix itself.
    property var origin: null
    property var originCoordinate: null
    // Pixels per EPSG:3857 metre at zoom 0, measured off the map once it projects.
    property real pixelsPerMetreAtZoom0: 0
    readonly property real pixelsPerMetre: geoMap ? pixelsPerMetreAtZoom0 * Math.pow(2, geoMap.zoomLevel) : 0

    // What is drawn: per band, its runs; the band of the last segment; how many fixes.
    property var bandRuns: []
    property int lastBand: -1
    property int drawn: 0
    property int drawnGeneration: -1

    function merc(c) {
        var R = 6378137
        return { x: R * c.longitude * Math.PI / 180,
                 y: R * Math.log(Math.tan(Math.PI / 4 + c.latitude * Math.PI / 360)) }
    }

    function unmerc(x, y) {
        var R = 6378137
        return QtPositioning.coordinate((2 * Math.atan(Math.exp(y / R)) - Math.PI / 2) * 180 / Math.PI,
                                        x / R * 180 / Math.PI)
    }

    // Shape coordinates: metres east and south of the first fix.
    function local(c) {
        var m = merc(c)
        return Qt.point(m.x - origin.x, origin.y - m.y)
    }

    function bandOf(kmh) {
        return Math.max(0, Math.min(bands - 1, Math.floor(kmh / bandKmh)))
    }

    function measure() {
        if (pixelsPerMetreAtZoom0 > 0 || !geoMap || !geoMap.mapReady || geoMap.width <= 0)
            return
        var c = geoMap.toCoordinate(Qt.point(geoMap.width / 2, geoMap.height / 2), false)
        var m = merc(c)
        var a = geoMap.fromCoordinate(c, false)
        var b = geoMap.fromCoordinate(unmerc(m.x + 1000, m.y), false)
        pixelsPerMetreAtZoom0 = Math.hypot(b.x - a.x, b.y - a.y) / 1000 / Math.pow(2, geoMap.zoomLevel)
    }

    function update() {
        var path = CurrentDrive.path
        var speeds = CurrentDrive.speeds
        var changed = []
        if (CurrentDrive.generation !== drawnGeneration || path.length < drawn) {
            drawnGeneration = CurrentDrive.generation
            bandRuns = Array.from({ length: bands }, () => [])
            lastBand = -1
            drawn = 0
            origin = path.length ? merc(path[0]) : null
            originCoordinate = path.length ? path[0] : null
            for (var b = 0; b < bands; b++)
                changed[b] = true
        }
        for (var i = Math.max(drawn, 1); i < path.length; i++) {
            var band = bandOf((speeds[i - 1] + speeds[i]) / 2)
            var p = local(path[i])
            if (band !== lastBand) {
                bandRuns[band].push([local(path[i - 1]), p])
                lastBand = band
            } else {
                var runs = bandRuns[band]
                runs[runs.length - 1].push(p)
            }
            changed[band] = true
        }
        drawn = path.length
        for (var k = 0; k < bands; k++)
            if (changed[k])
                bandPaths[k].runs = bandRuns[k].slice()
    }

    Connections {
        target: CurrentDrive
        function onPathChanged() { root.update() }
    }

    Connections {
        target: root.geoMap
        function onMapReadyChanged() { root.measure() }
    }

    Component.onCompleted: {
        measure()
        update()
    }

    component Band: ShapePath {
        property int band
        property var runs: []
        strokeColor: Theme.speedColor((band + 0.5) * root.bandKmh)
        strokeWidth: root.pixelsPerMetre > 0 ? Theme.mapDriveRouteWidth / root.pixelsPerMetre : 0
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        joinStyle: ShapePath.RoundJoin
        PathMultiline { paths: runs }
    }

    readonly property var bandPaths: [b0, b1, b2, b3, b4, b5, b6, b7, b8, b9]

    Item {
        readonly property var place: {
            if (!root.geoMap || !root.originCoordinate || root.pixelsPerMetre <= 0)
                return null
            root.geoMap.center; root.geoMap.zoomLevel; root.geoMap.bearing; root.geoMap.width; root.geoMap.height
            return root.geoMap.fromCoordinate(root.originCoordinate, false)
        }
        visible: place !== null
        x: place ? place.x : 0
        y: place ? place.y : 0
        scale: root.pixelsPerMetre
        rotation: root.geoMap ? -root.geoMap.bearing : 0
        transformOrigin: Item.TopLeft

        Shape {
            preferredRendererType: Shape.CurveRenderer
            Band { id: b0; band: 0 }
            Band { id: b1; band: 1 }
            Band { id: b2; band: 2 }
            Band { id: b3; band: 3 }
            Band { id: b4; band: 4 }
            Band { id: b5; band: 5 }
            Band { id: b6; band: 6 }
            Band { id: b7; band: 7 }
            Band { id: b8; band: 8 }
            Band { id: b9; band: 9 }
        }
    }
}

import QtQuick
import QtQuick.Shapes
import frontend_v2

// The drive under way (CurrentDrive) on a TeslaMap, coloured by speed on the Trips map's scale
// (Theme.speedColor), each segment by the mean of its two fixes. Declare it inside the Map;
// the stretch from the last fix to the car arrow is the map's own two-point line.
//
// One Shape in a GeoFrame from the drive's first fix, a ShapePath per speed band holding that
// band's runs: a frame costs one projection, where a MapPolyline per colour would each be
// rebuilt every frame of a following map. A new fix extends the runs of the band it falls in
// and leaves the other bands alone; a reply that replaces the path (CurrentDrive.generation)
// starts them over.
Item {
    id: root

    // Not `map`: a binding `map: map` can read this property itself.
    property Item geoMap: null

    readonly property int bands: 10
    readonly property real bandKmh: Theme.tripMaxSpeedKmh / bands

    // What is drawn: per band, its runs; the band of the last segment; how many fixes.
    property var bandRuns: []
    property int lastBand: -1
    property int drawn: 0
    property int drawnGeneration: -1

    function bandOf(kmh) {
        return Math.max(0, Math.min(bands - 1, Math.floor(kmh / bandKmh)))
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
            frame.originCoordinate = path.length ? path[0] : null
            for (var b = 0; b < bands; b++)
                changed[b] = true
        }
        for (var i = Math.max(drawn, 1); i < path.length; i++) {
            var band = bandOf((speeds[i - 1] + speeds[i]) / 2)
            var p = frame.local(path[i].latitude, path[i].longitude)
            if (band !== lastBand) {
                bandRuns[band].push([frame.local(path[i - 1].latitude, path[i - 1].longitude), p])
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

    Component.onCompleted: update()

    component Band: ShapePath {
        property int band
        property var runs: []
        strokeColor: Theme.speedColor((band + 0.5) * root.bandKmh)
        strokeWidth: frame.pixelsPerMetre > 0 ? Theme.mapDriveRouteWidth / frame.pixelsPerMetre : 0
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        joinStyle: ShapePath.RoundJoin
        PathMultiline { paths: runs }
    }

    readonly property var bandPaths: [b0, b1, b2, b3, b4, b5, b6, b7, b8, b9]

    GeoFrame {
        id: frame
        geoMap: root.geoMap

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

import QtQuick
import QtQuick.Shapes
import frontend_v2

// A route coloured by speed on a map (Theme.speedColor), each segment by the mean of its two
// fixes: the drive on the car's maps (CurrentDrive.route) and the Trips map's trip
// (Trips.route). Declare it inside the Map.
//
// RouteBands (C++) builds the geometry, in one GeoFrame's metres from the route's first fix,
// and nothing here touches a point. Each of its chunks is a Shape with a ShapePath per speed
// band, carried with the map by the GeoFrame: a frame of a pan or zoom costs that one
// projection and processes no path again, since the strokes are cosmetic — the same width on
// screen at every zoom. A new fix has the one short chunk it lands in processed again. The
// Shapes are asynchronous: a long trip's paths are processed off the GUI thread.
Item {
    id: root

    // Not `map`: a binding `map: map` can read this property itself.
    property Item geoMap: null
    property RouteBands route: null
    property real lineWidth: Theme.mapDriveRouteWidth
    // A line under the whole route, for contrast over bright imagery; none while transparent.
    property color casingColor: "transparent"
    property real casingWidth: lineWidth + 3

    readonly property int bands: 10
    readonly property real bandKmh: Theme.tripMaxSpeedKmh / bands

    // Every drawer of a route sets the same values, so none restores its own on leaving.
    Binding {
        target: root.route
        when: root.route !== null
        property: "bandCount"
        value: root.bands
        restoreMode: Binding.RestoreNone
    }
    Binding {
        target: root.route
        when: root.route !== null
        property: "bandKmh"
        value: root.bandKmh
        restoreMode: Binding.RestoreNone
    }

    component Band: ShapePath {
        property int chunk
        property int revision
        property int band
        strokeColor: Theme.speedColor((band + 0.5) * root.bandKmh)
        strokeWidth: root.lineWidth
        cosmeticStroke: true
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        joinStyle: ShapePath.RoundJoin
        PathMultiline { paths: revision >= 0 ? root.route.runs(chunk, band) : [] }
    }

    GeoFrame {
        id: frame
        geoMap: root.geoMap
        originCoordinate: root.route && root.route.origin.isValid ? root.route.origin : null

        // All of the casing goes under all of the colour, or a chunk's casing would cover
        // the end of the chunk before it.
        Repeater {
            model: root.casingColor.a > 0 ? root.route : null

            Shape {
                required property int index
                required property int revision
                preferredRendererType: Shape.CurveRenderer
                asynchronous: true

                ShapePath {
                    strokeColor: root.casingColor
                    strokeWidth: root.casingWidth
                    cosmeticStroke: true
                    fillColor: "transparent"
                    capStyle: ShapePath.RoundCap
                    joinStyle: ShapePath.RoundJoin
                    PathMultiline { paths: revision >= 0 ? root.route.casing(index) : [] }
                }
            }
        }

        Repeater {
            model: root.route

            Shape {
                id: chunk
                required property int index
                required property int revision
                preferredRendererType: Shape.CurveRenderer
                asynchronous: true

                Band { band: 0; chunk: chunk.index; revision: chunk.revision }
                Band { band: 1; chunk: chunk.index; revision: chunk.revision }
                Band { band: 2; chunk: chunk.index; revision: chunk.revision }
                Band { band: 3; chunk: chunk.index; revision: chunk.revision }
                Band { band: 4; chunk: chunk.index; revision: chunk.revision }
                Band { band: 5; chunk: chunk.index; revision: chunk.revision }
                Band { band: 6; chunk: chunk.index; revision: chunk.revision }
                Band { band: 7; chunk: chunk.index; revision: chunk.revision }
                Band { band: 8; chunk: chunk.index; revision: chunk.revision }
                Band { band: 9; chunk: chunk.index; revision: chunk.revision }
            }
        }
    }
}

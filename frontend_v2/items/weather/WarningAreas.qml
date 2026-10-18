import QtQuick
import QtQuick.Shapes
import QtPositioning
import frontend_v2
import "WeatherUtil.js" as U

// FMI's weather warnings in force (the Weather view's document, Weather.view.warnings) as areas
// on a TeslaMap: each warning's regions filled faintly in its colour and outlined. Declare it
// inside the Map. The regions come simplified to about half a kilometre
// (backend/src/weather_service/weather_view.py, `shapes`) and are drawn in one GeoFrame from
// the middle of Finland.
Item {
    id: root

    // Not `map`: a binding `map: map` can read this property itself.
    property Item geoMap: null
    readonly property var warnings: (Weather.view.warnings || []).filter(w => (w.shapes || []).length > 0)

    GeoFrame {
        id: frame
        geoMap: root.geoMap
        originCoordinate: QtPositioning.coordinate(64, 26)

        Repeater {
            model: root.warnings

            Shape {
                id: area
                required property var modelData
                readonly property color tone: U.warnColor(modelData.color)
                preferredRendererType: Shape.CurveRenderer

                ShapePath {
                    fillColor: Qt.rgba(area.tone.r, area.tone.g, area.tone.b, 0.22)
                    strokeColor: area.tone
                    strokeWidth: frame.pixelsPerMetre > 0 ? 2 / frame.pixelsPerMetre : 0
                    fillRule: ShapePath.WindingFill
                    joinStyle: ShapePath.RoundJoin
                    PathMultiline {
                        paths: area.modelData.shapes.map(ring => ring.map(p => frame.local(p[0], p[1])))
                    }
                }
            }
        }
    }
}

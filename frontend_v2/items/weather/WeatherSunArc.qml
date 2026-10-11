import QtQuick
import QtQuick.Shapes
import frontend_v2
import "WeatherUtil.js" as U

// PROTOTYPE — the day as an arc from sunrise to sunset, with the sun where it is now.
Item {
    id: root

    property var astro: ({})
    property date now: new Date()

    readonly property real rise: U.todayAt(astro.sunriseIso, now)
    readonly property real set: U.todayAt(astro.sunsetIso, now)
    // 0 at sunrise, 1 at sunset; outside the day the sun rests on the horizon.
    readonly property real progress: Math.max(0, Math.min(1, (now.getTime() - rise) / (set - rise)))
    readonly property bool isDay: now.getTime() > rise && now.getTime() < set

    readonly property real r: Math.min(width / 2 - 10, height - 34)
    readonly property real cx: width / 2
    readonly property real cy: r + 8

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer

        // Whole day, faint.
        ShapePath {
            strokeColor: "#33ffffff"
            strokeWidth: 2
            fillColor: "transparent"
            PathAngleArc {
                centerX: root.cx; centerY: root.cy
                radiusX: root.r; radiusY: root.r
                startAngle: 180; sweepAngle: 180
            }
        }
        // Elapsed part, sun-coloured.
        ShapePath {
            strokeColor: "#fed731"
            strokeWidth: 3
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: root.cx; centerY: root.cy
                radiusX: root.r; radiusY: root.r
                startAngle: 180; sweepAngle: 180 * root.progress
            }
        }
        // Horizon.
        ShapePath {
            strokeColor: "#40ffffff"
            strokeWidth: 1
            startX: 0; startY: root.cy
            PathLine { x: root.width; y: root.cy }
        }
    }

    Rectangle {
        readonly property real a: Math.PI * (1 + root.progress)
        x: root.cx + root.r * Math.cos(a) - width / 2
        y: root.cy + root.r * Math.sin(a) - height / 2
        width: 14
        height: 14
        radius: 7
        color: root.isDay ? "#fed731" : "#66fed731"
        border.color: root.isDay ? "#fff4b0" : "transparent"
    }

    Text {
        anchors.left: parent.left
        y: root.cy + 6
        text: "↑ " + (root.astro.sunrise || "")
        color: "#d8dee6"
        font.family: Theme.fontFamily
        font.pixelSize: 13
    }
    Text {
        anchors.right: parent.right
        y: root.cy + 6
        text: "↓ " + (root.astro.sunset || "")
        color: "#d8dee6"
        font.family: Theme.fontFamily
        font.pixelSize: 13
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.cy - 22
        text: root.astro.dayLength ? U.dayLength(root.astro.dayLength) : ""
        color: "white"
        font.family: Theme.fontFamily
        font.pixelSize: 13
    }
}

import QtQuick
import QtQuick.Shapes

// A wind arrow pointing where the wind blows TO (FMI's convention), given the
// meteorological direction it blows FROM.
Item {
    id: root

    property real direction: 0
    property color color: "white"
    property real size: 16

    implicitWidth: size
    implicitHeight: size

    Shape {
        anchors.fill: parent
        rotation: root.direction + 180
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            fillColor: root.color
            strokeColor: "transparent"
            startX: root.size / 2; startY: 0
            PathLine { x: root.size * 0.85; y: root.size }
            PathLine { x: root.size / 2; y: root.size * 0.7 }
            PathLine { x: root.size * 0.15; y: root.size }
            PathLine { x: root.size / 2; y: 0 }
        }
    }
}

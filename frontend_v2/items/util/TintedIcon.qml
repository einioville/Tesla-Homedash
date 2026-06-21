import QtQuick
import Qt5Compat.GraphicalEffects

// Recolours a monochrome SVG/PNG icon to a solid tint — the QML equivalent of
// the Widgets frontend's "render SVG then fill SourceIn" tinting (white weather
// glyphs, red/blue seat + steering states). The source icons are solid black,
// so a hard alpha-masked ColorOverlay is used rather than the luminance-aware
// MultiEffect.colorization (which would leave black icons dark).
Item {
    id: root

    property url source
    property color tint: "#ffffff"
    property int iconSize: 24

    implicitWidth: iconSize
    implicitHeight: iconSize

    Image {
        id: src
        anchors.fill: parent
        source: root.source
        sourceSize.width: root.iconSize
        sourceSize.height: root.iconSize
        fillMode: Image.PreserveAspectFit
        smooth: true
        visible: false
    }

    ColorOverlay {
        anchors.fill: src
        source: src
        color: root.tint
    }
}

import QtQuick
import QtQuick.Effects

// An icon wrapped in a coloured drop-shadow "glow" — mirrors the Widgets
// frontend's QGraphicsDropShadowEffect on the HVAC power button and the
// temperature ± arrows (blur, zero offset, state colour). autoPaddingEnabled
// lets the glow bleed past the icon bounds instead of clipping.
Item {
    id: root

    property url source
    property color glow: "#ffffff"
    property int iconSize: 100
    property int glowRadiusPx: 24
    property real glowStrength: 0.85

    implicitWidth: iconSize
    implicitHeight: iconSize

    Image {
        id: src
        anchors.centerIn: parent
        width: root.iconSize
        height: root.iconSize
        source: root.source
        sourceSize.width: root.iconSize
        sourceSize.height: root.iconSize
        fillMode: Image.PreserveAspectFit
        smooth: true
        visible: false
    }

    MultiEffect {
        anchors.fill: src
        source: src
        autoPaddingEnabled: true
        shadowEnabled: true
        shadowColor: root.glow
        shadowBlur: 1.0
        blurMax: root.glowRadiusPx
        shadowHorizontalOffset: 0
        shadowVerticalOffset: 0
        shadowOpacity: root.glowStrength
    }
}

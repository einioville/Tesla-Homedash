import QtQuick
import QtQuick.Effects
import frontend_v2

// One frosted copy of a backdrop for every GlassPanel laid over it (GlassPanel.frost): the
// backdrop captured at a quarter of its size and blurred once, in the notification glass's
// tone. A panel frosting on its own re-renders the backdrop into textures of its own and blurs
// it again — over a map that follows the car, every frame and for every panel, a few dozen
// render targets on the Kartta view against three here. Declare it beside the backdrop, never
// inside it.
Item {
    id: root

    property Item sourceItem: null
    // Off while nobody sees the panels; the texture keeps its last picture.
    property bool live: true
    // The backdrop's size, by which a panel finds its part of the texture.
    readonly property real sourceWidth: sourceItem ? sourceItem.width : 0
    readonly property real sourceHeight: sourceItem ? sourceItem.height : 0
    readonly property Item texture: frosted
    readonly property size textureSize: Qt.size(Math.max(1, Math.ceil(sourceWidth / 4)),
                                                Math.max(1, Math.ceil(sourceHeight / 4)))

    ShaderEffectSource {
        id: capture
        visible: false
        sourceItem: root.sourceItem
        live: root.live
        textureSize: root.textureSize
        smooth: true
    }

    // Drawn only into `frosted` (hideSource). Its blurMax is the panels' own 64 at a quarter of
    // the size.
    MultiEffect {
        id: blur
        width: root.textureSize.width
        height: root.textureSize.height
        source: capture
        autoPaddingEnabled: false
        blurEnabled: true
        blur: 1.0
        blurMax: 16
        brightness: Theme.notificationFrostBrightness
        saturation: Theme.notificationFrostSaturation
    }

    ShaderEffectSource {
        id: frosted
        visible: false
        sourceItem: blur
        hideSource: true
        live: root.live
        smooth: true
    }
}

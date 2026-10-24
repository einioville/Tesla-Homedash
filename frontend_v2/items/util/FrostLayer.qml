import QtQuick
import QtQuick.Effects
import frontend_v2

// The app's one source of frost (GlassPanel.frost): a backdrop captured at a quarter of its size
// and blurred once, in the notification glass's tone, from which every panel over that backdrop
// cuts its part. One per backdrop — the panels over a map share one, a dialog over it has its own
// since a dialog's frost is stronger. Declare it beside the backdrop, never inside it: a capture
// of an item that holds the panels would hold the panels too.
//
// It throws its effects away and builds them anew each time it goes live and every
// Theme.glassRebuildMs while live. Qt never links an effect again to a texture whose provider was
// destroyed (QSGRhiShaderEffectNode::handleTextureProviderDestroyed only drops it), and the glass
// has gone clear for good that way on the dev box, with no trigger found (items/util/CLAUDE.md).
// A rebuild links everything afresh, so a lost link lasts that long at most, not until a restart.
Item {
    id: root

    property Item sourceItem: null
    // Off while nobody sees the panels; the texture keeps its last picture.
    property bool live: true
    // The blur at a quarter of the size; a dialog's glass blurs further, so the text behind it
    // cannot be read, and darker.
    property real blurMax: 16
    property real brightness: Theme.notificationFrostBrightness
    // The backdrop's size, by which a panel finds its part of the texture.
    readonly property real sourceWidth: sourceItem ? sourceItem.width : 0
    readonly property real sourceHeight: sourceItem ? sourceItem.height : 0
    readonly property Item texture: chain.item ? chain.item.texture : null
    readonly property size textureSize: Qt.size(Math.max(1, Math.ceil(sourceWidth / 4)),
                                                Math.max(1, Math.ceil(sourceHeight / 4)))

    function rebuild() {
        chain.active = false
        chain.active = true
    }

    onLiveChanged: if (live) rebuild()

    Timer {
        interval: Theme.glassRebuildMs
        running: root.live
        repeat: true
        onTriggered: root.rebuild()
    }

    Loader {
        id: chain

        sourceComponent: Item {
            readonly property Item texture: frosted

            ShaderEffectSource {
                id: capture
                visible: false
                sourceItem: root.sourceItem
                live: root.live
                textureSize: root.textureSize
                smooth: true
            }

            // Drawn only into `frosted` (hideSource).
            MultiEffect {
                id: blur
                width: root.textureSize.width
                height: root.textureSize.height
                source: capture
                autoPaddingEnabled: false
                blurEnabled: true
                blur: 1.0
                blurMax: root.blurMax
                brightness: root.brightness
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
    }
}

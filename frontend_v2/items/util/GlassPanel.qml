import QtQuick
import QtQuick.Effects
import frontend_v2

// Reusable "liquid glass" surface — used by the notification pill, the graph's
// inspect readout (HistoryGraph, without the frost), the weather radar's
// controls and the Media view's next-track card (MediaUpNext, a card's fill and rim).
// It captures the region of `backdropSource` directly behind itself, blurs and
// rounds it, then overlays a dark translucent tint, a bright white rim and a
// specular highlight so white content reads clearly. The chrome below is declared
// first, so any children a consumer adds are painted on top of it — no content
// alias (a `default property alias` here would reparent this item's OWN chrome
// into the slot).
//
// The capture needs this panel's top-left in `backdropSource`'s coordinates;
// since the dashboard backdrop fills the window at (0,0), that is just the
// panel's window position. The consumer passes it as `backdropOrigin`, bound
// reactively (e.g. the pill's animated x/y) so the frost
// tracks the panel as it moves. `live` is gated on `active` so the (transient)
// capture+blur cost is paid only while the panel is actually on screen.
Item {
    id: panel

    property Item backdropSource: null
    property bool frostedBackdrop: true
    property bool active: true
    property point backdropOrigin: Qt.point(0, 0)
    property int radius: Theme.notificationRadius
    // The rim and the translucent tint, per instance; the defaults are the
    // notification pill's.
    property real rimWidth: 1.5
    property color rimColor: Theme.notificationBorder
    property color tintTop: Theme.notificationGlassTop
    property color tintBottom: Theme.notificationGlassBottom
    // The bright line just inside the top edge; a thin rim can do without it.
    property bool highlight: true
    // MultiEffect's brightness is added to every channel, so the default darkening turns an
    // already dark backdrop (the weather radar) black; such a panel passes its own.
    property real frostBrightness: Theme.notificationFrostBrightness

    // Its part of a shared frosted backdrop (FrostLayer), in place of a frost of its own — for
    // the panels over a map. `backdropOrigin` places it in that backdrop as it would here.
    property Item frost: null

    readonly property bool frostActive: frostedBackdrop && backdropSource !== null && frost === null

    // Capture just the backdrop region behind the panel. The backdrop is never a
    // parent of this panel, so the capture can't include the panel itself.
    ShaderEffectSource {
        id: capture
        anchors.fill: parent
        visible: false
        live: panel.frostActive && panel.active
        sourceItem: panel.frostActive ? panel.backdropSource : null
        sourceRect: Qt.rect(panel.backdropOrigin.x, panel.backdropOrigin.y,
                             panel.width, panel.height)
    }

    Rectangle {
        id: frostMask
        anchors.fill: parent
        radius: panel.radius
        visible: false
        layer.enabled: panel.frostActive
    }

    // Blur + round the captured backdrop, toned darker so it reads as dark glass.
    MultiEffect {
        anchors.fill: parent
        visible: panel.frostActive
        source: capture
        autoPaddingEnabled: false
        blurEnabled: true
        blur: 1.0
        blurMax: 64
        brightness: panel.frostBrightness
        saturation: Theme.notificationFrostSaturation
        maskEnabled: true
        maskSource: frostMask
    }

    ShaderEffect {
        anchors.fill: parent
        visible: panel.frost !== null && panel.frost.sourceWidth > 0
        property var source: panel.frost ? panel.frost.texture : null
        property rect region: panel.frost && panel.frost.sourceWidth > 0
                              ? Qt.rect(panel.backdropOrigin.x / panel.frost.sourceWidth,
                                        panel.backdropOrigin.y / panel.frost.sourceHeight,
                                        width / panel.frost.sourceWidth,
                                        height / panel.frost.sourceHeight)
                              : Qt.rect(0, 0, 1, 1)
        property size size: Qt.size(width, height)
        property real radius: panel.radius
        fragmentShader: "qrc:/resources/shaders/glassfrost.frag.qsb"
    }

    // Dark translucent tint (brighter at the top) + the rim.
    Rectangle {
        id: glass
        anchors.fill: parent
        radius: panel.radius
        color: "transparent"
        border.width: panel.rimWidth
        border.color: panel.rimColor
        gradient: Gradient {
            GradientStop { position: 0.0; color: panel.tintTop }
            GradientStop { position: 1.0; color: panel.tintBottom }
        }
    }

    // Specular highlight — a thin bright line just inside the top edge. Faded to
    // transparent at both ends so the inset line tapers out instead of showing a
    // hard end-cap (it stops short of the rounded corners by `radius`).
    Rectangle {
        visible: panel.highlight
        anchors.left: glass.left
        anchors.right: glass.right
        anchors.top: glass.top
        anchors.leftMargin: panel.radius
        anchors.rightMargin: panel.radius
        anchors.topMargin: 2
        height: 1
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 0.15; color: Theme.notificationHighlight }
            GradientStop { position: 0.85; color: Theme.notificationHighlight }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }
}

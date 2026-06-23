import QtQuick
import QtQuick.Effects
import frontend_v2

// Reusable "liquid glass" surface — used by the notification pill and the dock.
// It captures the region of `backdropSource` directly behind itself, blurs and
// rounds it, then overlays a dark translucent tint, a bright white rim and a
// specular highlight so white content reads clearly. The chrome below is declared
// first, so any children a consumer adds are painted on top of it — no content
// alias (a `default property alias` here would reparent this item's OWN chrome
// into the slot, the GradientCard pitfall).
//
// The capture needs this panel's top-left in `backdropSource`'s coordinates;
// since the dashboard backdrop fills the window at (0,0), that is just the
// panel's window position. The consumer passes it as `backdropOrigin`, bound
// reactively (e.g. the pill's animated x/y, or the dock's x/y) so the frost
// tracks the panel as it moves. `live` is gated on `active` so the (transient)
// capture+blur cost is paid only while the panel is actually on screen.
Item {
    id: panel

    property Item backdropSource: null
    property bool frostedBackdrop: true
    property bool active: true
    property point backdropOrigin: Qt.point(0, 0)
    property int radius: Theme.notificationRadius

    readonly property bool frostActive: frostedBackdrop && backdropSource !== null

    // Capture just the backdrop region behind the panel. The backdrop is never a
    // parent of this panel, so the capture can't include the panel itself.
    ShaderEffectSource {
        id: capture
        anchors.fill: parent
        visible: false
        live: panel.frostActive && panel.active
        sourceItem: panel.backdropSource
        sourceRect: Qt.rect(panel.backdropOrigin.x, panel.backdropOrigin.y,
                             panel.width, panel.height)
    }

    Rectangle {
        id: frostMask
        anchors.fill: parent
        radius: panel.radius
        visible: false
        layer.enabled: true
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
        brightness: Theme.notificationFrostBrightness
        saturation: Theme.notificationFrostSaturation
        maskEnabled: true
        maskSource: frostMask
    }

    // Dark translucent tint (brighter at the top) + bright white rim.
    Rectangle {
        id: glass
        anchors.fill: parent
        radius: panel.radius
        color: "transparent"
        border.width: 1.5
        border.color: Theme.notificationBorder
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.notificationGlassTop }
            GradientStop { position: 1.0; color: Theme.notificationGlassBottom }
        }
    }

    // Specular highlight — a thin bright line just inside the top edge. Faded to
    // transparent at both ends so the inset line tapers out instead of showing a
    // hard end-cap (it stops short of the rounded corners by `radius`).
    Rectangle {
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

    // Consumer content (declared after this item's chrome) is painted on top.
}

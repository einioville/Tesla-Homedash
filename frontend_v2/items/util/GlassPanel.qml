import QtQuick
import frontend_v2

// The app's one frosted-glass surface, for whatever is placed on glass: the notification pill,
// the map panels, a dialog over a map, the Media view's next-track card, the graph's inspect
// readout. A dark translucent tint, a bright rim and a specular highlight, so white content
// reads clearly, over its part of a FrostLayer (`frost`) — the one place frost is made. With no
// `frost` it is the glass alone (the graph's readout). The chrome below is declared first, so
// any children a consumer adds are painted on top of it — no content alias (a `default property
// alias` here would reparent this item's OWN chrome into the slot).
//
// `backdropOrigin` is the panel's top-left in the coordinates of the frost's source item, bound
// reactively by the consumer (e.g. the pill's animated y) so the frost follows the panel as it
// moves.
Item {
    id: panel

    property Item frost: null
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

    ShaderEffect {
        anchors.fill: parent
        visible: panel.frost !== null && panel.frost.texture !== null && panel.frost.sourceWidth > 0
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

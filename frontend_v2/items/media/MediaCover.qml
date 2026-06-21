import QtQuick
import QtQuick.Effects
import frontend_v2

// Album cover art + its dark halo shadow + tap-to-play/pause. Shared by the
// dashboard card and the fullscreen media view. The shadow is scaled from the
// card's 160 px reference (blur 24, spread 6) so it looks the same at any size.
// RoundedImage already loads the art at the display size from the full-resolution
// source, so a larger coverSize is automatically sharper.
Item {
    id: root

    property real coverSize: 160
    // Corner radius of the art (and its halo). Defaults to the dashboard card
    // radius; the fullscreen view overrides it for gentler, larger rounding.
    property int coverRadius: Theme.cardRadius

    readonly property real shadowBlur: coverSize * (24 / 160)
    readonly property real shadowSpread: coverSize * (6 / 160)

    implicitWidth: coverSize
    implicitHeight: coverSize

    RectangularShadow {
        anchors.fill: cover
        radius: root.coverRadius
        blur: root.shadowBlur
        spread: root.shadowSpread
        offset: Qt.vector2d(0, 0)
        color: "#ff000000"
    }

    RoundedImage {
        id: cover
        anchors.fill: parent
        radius: root.coverRadius
        source: Media.coverArtId
    }

    MouseArea {
        anchors.fill: cover
        onClicked: Media.pausePlay()
    }
}

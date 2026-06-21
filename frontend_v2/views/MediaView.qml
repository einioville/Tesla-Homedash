import QtQuick
import frontend_v2

// Fullscreen media player. The background is a smooth vertical gradient derived
// from the album cover's dominant colour (rich at the top border, fading
// straight down into near-black), cross-fading whenever the track — and thus the
// dominant colour — changes. The cover heads a centred vertical stack with the
// title/artist and the (larger) transport controls + progress bar below it.
// Cover, controls and seek bar are the shared media components, so this view and
// the dashboard card stay in lockstep.
Item {
    id: view

    property bool isCurrent: false

    // Top of the gradient: the live cover dominant colour, cross-faded so the
    // background glides to the new palette when the track changes.
    property color backgroundColor: Media.dominantColor
    Behavior on backgroundColor { enabled: view.isCurrent; ColorAnimation { duration: 400 } }

    // Bottom of the gradient: a heavily darkened variant of the same colour, so
    // the fade settles into near-black at the dock edge.
    readonly property color backgroundBottom:
        Qt.rgba(backgroundColor.r * 0.12,
                backgroundColor.g * 0.12,
                backgroundColor.b * 0.12, 1.0)

    // Smooth, opaque vertical gradient — top border straight down. Two stops only,
    // so the colour interpolates continuously (no visible "level" boundaries like
    // the old corner radial had). Opaque, so this view fully hides the others
    // behind it (see ViewController).
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: view.backgroundColor }
            GradientStop { position: 1.0; color: view.backgroundBottom }
        }
    }

    // One-shot noise tile, generated once and tiled by the GPU, blended at very
    // low opacity over the gradient. It dithers away the 8-bit banding a tall dark
    // gradient would otherwise show — the per-frame cost is just one extra
    // textured quad. Tunable: drop opacity toward 0 to soften, or remove entirely.
    Canvas {
        id: noiseTile
        width: 128
        height: 128
        // opacity:0 (not visible:false) so the Canvas stays in the rendered scene
        // and onPaint reliably fires — an invisible, unconsumed Canvas may never
        // paint, leaving the tile (and the dither) empty. It is 128x128 at 0,0,
        // fully covered by the gradient + content, so it is effectively hidden.
        opacity: 0
        property string url: ""
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx)
                return
            var image = ctx.createImageData(width, height)
            var data = image.data
            for (var i = 0; i < data.length; i += 4) {
                var v = Math.floor(Math.random() * 256)
                data[i] = v
                data[i + 1] = v
                data[i + 2] = v
                data[i + 3] = 255
            }
            ctx.putImageData(image, 0, 0)
            noiseTile.url = noiseTile.toDataURL("image/png")
        }
        Component.onCompleted: requestPaint()
    }

    Image {
        anchors.fill: parent
        source: noiseTile.url
        visible: noiseTile.url.length > 0
        fillMode: Image.Tile
        opacity: 0.02
    }

    // Cover sized to leave room for the title/artist + controls stacked below it.
    readonly property real coverSize:
        Math.max(240, Math.min(view.width - 200, view.height - 380, 420))

    // Centred vertical stack: cover, then title/artist, then transport + seek bar.
    Column {
        anchors.centerIn: parent
        spacing: 28

        MediaCover {
            id: cover
            anchors.horizontalCenter: parent.horizontalCenter
            coverSize: view.coverSize
            // Gentler, larger rounding than the dashboard card, scaled to the
            // big cover so it reads as softly rounded rather than near-square.
            coverRadius: Math.max(Theme.cardRadius, Math.round(view.coverSize * 0.04))
        }

        // Title + artist, below the cover.
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            width: view.coverSize
            spacing: 4

            Text {
                width: parent.width
                text: Media.title.length > 0 ? Media.title : "-"
                color: Theme.dataLabelValue
                font.family: Theme.fontFamily
                font.pointSize: 26
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                visible: Media.mediaType === 2 && Media.artists.length > 0
                text: Media.artists
                color: Theme.dataLabelValue
                font.family: Theme.fontFamily
                font.pointSize: 15
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
            }
        }

        // Transport + progress, below the title.
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(view.width * 0.55, 560)
            spacing: 18

            MediaTransport {
                anchors.horizontalCenter: parent.horizontalCenter
                buttonSize: 56
            }

            MediaSeekBar {
                width: parent.width
                visible: Media.mediaType !== 1   // hidden for radio (no progress)
                active: view.isCurrent
                barHeight: 6
                handleSize: 18
                fontPointSize: 12
            }
        }
    }
}

import QtQuick
import frontend_v2

// Fullscreen media player over the cover-coloured backdrop (MediaBackdrop), its
// main colour a halo behind the cover, with the spectrum of what is playing along
// the bottom edge (MediaSpectrum). The cover heads a centred vertical stack with
// the title/artist and the (larger) transport controls + progress bar below it.
// Cover, controls and seek bar are the shared media components, so this view and
// the dashboard card stay in lockstep.
Item {
    id: view

    property bool isCurrent: false

    // Opaque, so this view fully hides the others behind it (see ViewController).
    Rectangle {
        anchors.fill: parent
        color: Theme.mediaBackground
    }

    // The halo is centred on the cover (the stack below puts it about here) and
    // reaches well past it, the cover hiding its middle; the cover's colours drift
    // in the corners round it, its main one the most. Nothing lies over the light
    // here, so it is stronger than on the dashboard, under translucent cards.
    MediaBackdrop {
        anchors.fill: parent
        active: view.isCurrent
        strength: Theme.mediaBackdropStrength
        glows: [
            { tone: 0, radius: 760, home: Qt.point(640, 280), reach: Qt.point(50, 30),
              periods: Qt.vector3d(31, 23, 19), phase: 0.0 },
            { tone: 1, radius: 520, home: Qt.point(170, 170), reach: Qt.point(140, 110),
              periods: Qt.vector3d(41, 33, 27), phase: 1.3 },
            { tone: 0, radius: 560, home: Qt.point(1110, 630), reach: Qt.point(150, 110),
              periods: Qt.vector3d(47, 37, 29), phase: 2.6 },
            { tone: 2, radius: 480, home: Qt.point(1120, 150), reach: Qt.point(130, 100),
              periods: Qt.vector3d(53, 39, 31), phase: 3.9 },
            { tone: 0, radius: 500, home: Qt.point(160, 650), reach: Qt.point(130, 100),
              periods: Qt.vector3d(43, 35, 25), phase: 5.2 }
        ]
    }

    // One-shot noise tile, generated once and tiled by the GPU, blended at very
    // low opacity over the backdrop. It dithers away the 8-bit banding its broad
    // dark gradients would otherwise show — the per-frame cost is just one extra
    // textured quad. Tunable: drop opacity toward 0 to soften, or remove entirely.
    Canvas {
        id: noiseTile
        width: 128
        height: 128
        // opacity:0 (not visible:false) so the Canvas stays in the rendered scene
        // and onPaint reliably fires — an invisible, unconsumed Canvas may never
        // paint, leaving the tile (and the dither) empty. It is 128x128 at 0,0,
        // fully covered by the backdrop + content, so it is effectively hidden.
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

    // Along the bottom edge, over the backdrop and under everything else.
    MediaSpectrum {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 200
        active: view.isCurrent
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
            // Gentler, larger rounding than the dashboard card's cover, scaled to
            // the big cover so it reads as softly rounded rather than near-square.
            coverRadius: Math.max(Theme.coverRadius, Math.round(view.coverSize * 0.04))
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

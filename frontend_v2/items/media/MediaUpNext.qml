import QtQuick
import QtQuick.Effects
import frontend_v2

// The Media view's "up next" card: what Spotify plays after the current track, on
// frosted glass in the bottom-right corner. It rises from below the screen's edge
// Theme.mediaUpNextLeadMs before the track ends and drops back when the
// track changes or pauses. Laid over the whole view, as is
// `backdropSource`, the view's backdrop the glass frosts. It takes no input, so
// swipes pass through it.
Item {
    id: root

    // The owning view's isCurrent: a hidden view neither asks nor shows, and nor does
    // a display with the card switched off.
    property bool active: false
    property Item backdropSource: null

    // Each ask is a read of Spotify's queue on the backend, so the card asks once a
    // track, this long before it is due: time for the answer and its cover.
    readonly property int askAheadMs: 6000
    readonly property int slideMs: 420
    readonly property int margin: 24
    // Far enough below its place that the shadow is off the screen too.
    readonly property real hiddenOffset: card.height + margin + 40

    readonly property int remainingMs: Media.durationMs - Media.progressMs
    readonly property bool playing:
        active && Theme.mediaUpNextEnabled && Media.mediaType === 2 && Media.isPlaying &&
        Media.durationMs > 0
    readonly property bool asking:
        playing && remainingMs <= Theme.mediaUpNextLeadMs + askAheadMs
    readonly property bool shown:
        playing && remainingMs <= Theme.mediaUpNextLeadMs && Media.nextTitle.length > 0

    // The answer, held while the card drops away: Media clears it on a track change.
    property string title
    property string artists
    property string imageUrl

    onAskingChanged: if (asking) Media.requestNext()

    Connections {
        target: Media
        function onNextChanged() {
            if (Media.nextTitle.length === 0)
                return
            root.title = Media.nextTitle
            root.artists = Media.nextArtists
            root.imageUrl = Media.nextImageUrl
        }
    }

    // Placed by anchors and moved by the transform alone, so laying out the view
    // never animates it.
    Item {
        id: card
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: root.margin
        width: 300
        height: 112
        visible: slide.y < root.hiddenOffset

        transform: Translate {
            id: slide
            y: root.shown ? 0 : root.hiddenOffset
            // Hiding, the overshoot is below the screen, out of sight.
            Behavior on y {
                NumberAnimation {
                    duration: root.slideMs
                    easing.type: Easing.OutBack
                    easing.overshoot: 1.2
                }
            }
        }

        RectangularShadow {
            anchors.fill: panel
            radius: Theme.cardRadius
            blur: 28
            offset: Qt.vector2d(0, 6)
            color: Theme.notificationShadow
        }

        GlassPanel {
            id: panel
            anchors.fill: parent
            // A dashboard card's fill and rim over the frost, undimmed: the
            // notification's dark glass turns black over this dark backdrop.
            radius: Theme.cardRadius
            tintTop: Theme.cardFill
            tintBottom: Theme.cardFill
            frostBrightness: 0
            rimWidth: 1
            rimColor: Theme.cardBorder
            highlight: false
            backdropSource: root.backdropSource
            backdropOrigin: Qt.point(card.x, card.y + slide.y)
            active: card.visible

            // Card.qml's title.
            Text {
                x: 14
                y: 10
                text: qsTr("SEURAAVAKSI")
                color: Theme.cardTitle
                font.family: Theme.fontFamily
                font.pixelSize: 12
                font.letterSpacing: 1.2
            }

            Row {
                x: 14
                y: 34
                width: parent.width - 28
                spacing: 12

                // Fetched by this display from the URL the backend sends, like the
                // current cover (root CLAUDE.md §5.4); a failed fetch leaves the box.
                Rectangle {
                    id: coverBox
                    width: 64
                    height: 64
                    radius: Theme.coverRadius
                    color: Theme.cardFill

                    RoundedImage {
                        anchors.fill: parent
                        radius: Theme.coverRadius
                        fillMode: Image.PreserveAspectCrop
                        source: root.imageUrl
                        onStatusChanged: {
                            if (status === Image.Error)
                                console.warn("Next track cover fetch failed:", root.imageUrl)
                        }
                    }
                }

                Column {
                    width: parent.width - coverBox.width - parent.spacing
                    anchors.verticalCenter: coverBox.verticalCenter
                    spacing: 4

                    Text {
                        width: parent.width
                        text: root.title
                        elide: Text.ElideRight
                        color: Theme.dataLabelValue
                        font.family: Theme.fontFamily
                        font.pixelSize: 18
                    }
                    Text {
                        width: parent.width
                        visible: text.length > 0
                        text: root.artists
                        elide: Text.ElideRight
                        color: Theme.dataLabelTitle
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                    }
                }
            }
        }
    }
}

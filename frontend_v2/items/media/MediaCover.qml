import QtQuick
import QtQuick.Effects
import frontend_v2

// Album cover art + its dark halo shadow + tap-to-play/pause. Shared by the
// dashboard card and the fullscreen media view. The shadow is scaled from the
// card's 160 px reference (blur 24, spread 6) so it looks the same at any size.
// RoundedImage already loads the art at the display size from the full-resolution
// source, so a larger coverSize is automatically sharper.
//
// With `slide` on (the Media view) a new cover slides in from the right as the old
// one leaves to the left, or the other way after the back button
// (Media.coverDirection). It waits for the new picture to load, so nothing slides
// in empty; a change in the middle of a slide finishes that one first.
//
// With `swipe` on (the Media view too) a sideways swipe over the cover skips: to
// the left the next track, to the right the previous one, the way the new cover
// then comes in. The cover follows the finger at half its distance and springs
// back on release; the slide comes with the new picture. A tap plays or pauses.
Item {
    id: root

    property real coverSize: 160
    // Corner radius of the art (and its halo); the fullscreen view overrides it
    // for gentler, larger rounding.
    property int coverRadius: Theme.coverRadius
    property bool slide: false
    // The owning view's isCurrent: a hidden view swaps the cover in place, since
    // an animation renders the whole window while it runs.
    property bool active: true
    property bool swipe: false

    // A swipe skips past swipeCommit px of finger travel, or when flicked that way
    // at swipeFlick px/s; the cover follows to swipeReach at most.
    readonly property real swipeCommit: coverSize * 0.18
    readonly property real swipeFlick: 600
    readonly property real swipeReach: coverSize * 0.3
    property real dragX: 0
    property CoverLayer dragged: null
    readonly property ReleaseVelocity swipeSpeed: ReleaseVelocity {}

    readonly property real shadowBlur: coverSize * (24 / 160)
    readonly property real shadowSpread: coverSize * (6 / 160)
    // A cover and a gap: the two move in step, side by side like pages, and never
    // overlap — two translucent covers over each other turn to mud.
    readonly property real slideDistance: coverSize + 48
    readonly property int slideMs: 560

    // The two layers take turns: `front` shows the current cover, and a new one
    // loads into the other before it slides in.
    property CoverLayer front: layerA
    readonly property CoverLayer back: front === layerA ? layerB : layerA
    property bool pending: false
    property int direction: 1

    implicitWidth: coverSize
    implicitHeight: coverSize

    component CoverLayer: Item {
        property alias source: image.source
        readonly property alias status: image.status

        width: root.coverSize
        height: root.coverSize

        RectangularShadow {
            anchors.fill: image
            radius: root.coverRadius
            blur: root.shadowBlur
            spread: root.shadowSpread
            offset: Qt.vector2d(0, 0)
            color: "#ff000000"
        }

        RoundedImage {
            id: image
            anchors.fill: parent
            radius: root.coverRadius
        }
    }

    CoverLayer { id: layerA }
    CoverLayer { id: layerB; opacity: 0 }

    Component.onCompleted: {
        if (slide)
            layerA.source = Media.coverArtId
        else
            layerA.source = Qt.binding(() => Media.coverArtId)
    }

    Connections {
        target: Media
        enabled: root.slide

        function onCoverArtIdChanged() {
            slideAnim.complete()
            // The first picture has nothing to slide in over.
            if (!root.active || root.front.source.toString().length === 0) {
                root.pending = false
                root.front.source = Media.coverArtId
                return
            }
            root.direction = Media.coverDirection
            root.pending = true
            root.back.source = Media.coverArtId
            if (root.back.status === Image.Ready)
                root.startSlide()
        }
    }

    Connections {
        target: root.back
        enabled: root.pending

        function onStatusChanged() {
            if (root.back.status === Image.Ready)
                root.startSlide()
            else if (root.back.status === Image.Error)
                root.pending = false
        }
    }

    function startSlide() {
        pending = false
        springBack.stop()
        const incoming = back
        const outgoing = front
        incoming.z = 1
        outgoing.z = 0
        incomingX.target = incoming
        incomingFade.target = incoming
        outgoingX.target = outgoing
        outgoingFade.target = outgoing
        incomingX.from = direction * slideDistance
        // From wherever a swipe has left it.
        outgoingX.from = outgoing.x
        outgoingX.to = -direction * slideDistance
        outgoingFade.from = outgoing.opacity
        front = incoming
        slideAnim.restart()
    }

    // Moves the swiped cover, unless a slide has taken it over.
    function follow() {
        if (dragged !== front || slideAnim.running)
            return
        const x = Math.max(-swipeReach, Math.min(swipeReach, dragX * 0.5))
        dragged.x = x
        dragged.opacity = 1 - 0.25 * Math.abs(x) / swipeReach
    }

    function endSwipe(speed) {
        const flicked = Math.abs(speed) >= swipeFlick && Math.sign(speed) === Math.sign(dragX)
        if (Math.abs(dragX) >= swipeCommit || flicked && Math.abs(dragX) > 12) {
            if (dragX < 0)
                Media.skipForward()
            else
                Media.skipBackward()
        }
        if (dragged === front && !slideAnim.running) {
            springX.target = dragged
            springFade.target = dragged
            springBack.restart()
        }
        dragged = null
    }

    ParallelAnimation {
        id: slideAnim
        NumberAnimation {
            id: incomingX
            property: "x"
            to: 0
            duration: root.slideMs
            easing.type: Easing.OutCubic
        }
        // In early, since it starts most of the way on screen.
        NumberAnimation {
            id: incomingFade
            property: "opacity"
            from: 0
            to: 1
            duration: root.slideMs * 0.4
        }
        NumberAnimation {
            id: outgoingX
            property: "x"
            from: 0
            duration: root.slideMs
            easing.type: Easing.OutCubic
        }
        // Out before it slows to a stop at the screen's edge.
        NumberAnimation {
            id: outgoingFade
            property: "opacity"
            to: 0
            duration: root.slideMs * 0.7
        }
    }

    ParallelAnimation {
        id: springBack
        NumberAnimation {
            id: springX
            property: "x"
            to: 0
            duration: 320
            easing.type: Easing.OutBack
            easing.overshoot: 1
        }
        NumberAnimation {
            id: springFade
            property: "opacity"
            to: 1
            duration: 320
            easing.type: Easing.OutCubic
        }
    }

    // A drag past the threshold cancels the tap.
    TapHandler {
        onTapped: Media.pausePlay()
    }

    DragHandler {
        enabled: root.swipe
        target: null
        yAxis.enabled: false

        onActiveChanged: {
            if (active) {
                slideAnim.complete()
                springBack.stop()
                root.dragged = root.front
                root.dragX = activeTranslation.x
                root.swipeSpeed.start(root.dragX)
            } else {
                root.endSwipe(root.swipeSpeed.release(root.dragX))
            }
        }
        onActiveTranslationChanged: {
            if (!active)
                return
            root.dragX = activeTranslation.x
            root.swipeSpeed.move(root.dragX)
            root.follow()
        }
    }
}

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
// then comes in. The cover follows the finger, easing off towards swipeReach. Let
// go short of a skip, it springs back; past one, it slides on from where it is —
// at once when the cover the skip should bring is in memory (Media.coverAfterSkip),
// else when the new cover arrives, waiting where it was let go until then. A slide
// to an expected cover the backend has not named within confirmMs slides back. A
// tap plays or pauses.
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
    // at swipeFlick px/s. The cover moves swipeFollow of the finger's distance at
    // first, easing off towards swipeReach, which it never passes.
    readonly property real swipeCommit: coverSize * 0.18
    readonly property real swipeFlick: 600
    readonly property real swipeFollow: 0.8
    readonly property real swipeReach: coverSize * 0.55
    // A skip whose cover is not in memory waits this long where it was let go for
    // the new one (Spotify's answer and the picture take 1-3 s), then springs back.
    readonly property int swipeHoldMs: 4000
    // How long a slide to an expected cover waits for the backend to name it.
    readonly property int confirmMs: 8000
    property real dragX: 0
    // The finger travel the cover's position at the drag's start stands for, so a
    // cover caught away from the centre does not jump.
    property real dragOrigin: 0
    property CoverLayer dragged: null
    readonly property ReleaseVelocity swipeSpeed: ReleaseVelocity {}
    // Let go past a skip, waiting where it is for the new cover.
    property bool holding: false

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

    // A few seconds into each Spotify track while the view shows, what plays next is
    // asked for, so a swipe finds its cover in memory; the queue can lag the change.
    readonly property bool asksNext: swipe && active && Media.mediaType === 2

    implicitWidth: coverSize
    implicitHeight: coverSize

    onAsksNextChanged: if (asksNext && Media.nextTitle.length === 0) askNextTimer.restart()

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
            confirmTimer.stop()
            // There already: its slide began with the swipe.
            if (Media.coverArtId === root.shownId())
                return
            // The first picture has nothing to slide in over.
            if (!root.active || root.shownId().length === 0) {
                root.settle(Media.coverArtId)
                return
            }
            root.slideTo(Media.coverArtId, root.holding ? root.direction : Media.coverDirection)
        }
    }

    Connections {
        target: Media
        enabled: root.asksNext

        function onTitleChanged() {
            askNextTimer.restart()
        }
    }

    Connections {
        target: root.back
        enabled: root.pending

        function onStatusChanged() {
            if (root.back.status === Image.Ready) {
                root.startSlide()
            } else if (root.back.status === Image.Error) {
                root.pending = false
                root.springBack()
            }
        }
    }

    function shownId() {
        return front.source.toString()
    }

    // Shows a cover in place, nothing moving.
    function settle(source) {
        slideAnim.complete()
        springAnim.stop()
        holdTimer.stop()
        holding = false
        pending = false
        front.source = source
        front.x = 0
        front.opacity = 1
    }

    // Slides `source` in once it has loaded, from wherever the shown cover is.
    function slideTo(source, way) {
        slideAnim.complete()
        holdTimer.stop()
        holding = false
        direction = way
        pending = true
        back.source = source
        if (back.status === Image.Ready)
            startSlide()
    }

    function startSlide() {
        pending = false
        springAnim.stop()
        const incoming = back
        const outgoing = front
        incoming.z = 1
        outgoing.z = 0
        incomingX.target = incoming
        incomingFade.target = incoming
        outgoingX.target = outgoing
        outgoingFade.target = outgoing
        // A page apart, from wherever a swipe has left the outgoing cover.
        outgoingX.from = outgoing.x
        outgoingX.to = -direction * slideDistance
        incomingX.from = outgoing.x + direction * slideDistance
        outgoingFade.from = outgoing.opacity
        front = incoming
        slideAnim.restart()
    }

    function springBack() {
        springX.target = front
        springFade.target = front
        springAnim.restart()
    }

    // Moves the swiped cover, unless a slide has taken it over.
    function follow() {
        if (dragged !== front || slideAnim.running)
            return
        const x = swipeReach * Math.tanh((dragOrigin + dragX) * swipeFollow / swipeReach)
        dragged.x = x
        dragged.opacity = 1 - 0.25 * Math.abs(x) / swipeReach
    }

    // The cover a skip that way brings, if it can be shown now. Not while the one
    // shown is an expected cover the backend has yet to name: where a skip from
    // there lands depends on which the backend has done first, so it waits for that.
    function expectedCover(way) {
        return shownId() === Media.coverArtId ? Media.coverAfterSkip(way) : ""
    }

    function endSwipe(speed) {
        const flicked = Math.abs(speed) >= swipeFlick && Math.sign(speed) === Math.sign(dragX)
        const skips = Math.abs(dragX) >= swipeCommit || flicked && Math.abs(dragX) > 12
        const holdsCover = dragged === front && !slideAnim.running
        dragged = null
        if (!skips) {
            if (holdsCover)
                springBack()
            return
        }
        const way = dragX < 0 ? 1 : -1
        const expected = expectedCover(way)
        if (way > 0)
            Media.skipForward()
        else
            Media.skipBackward()
        // A slide that came in meanwhile has the cover.
        if (!holdsCover)
            return
        if (expected === shownId()) {
            // A restart, or a track off the same album.
            springBack()
        } else if (expected.length > 0) {
            slideTo(expected, way)
            confirmTimer.restart()
        } else {
            holding = true
            direction = way
            holdTimer.restart()
        }
    }

    Timer {
        id: holdTimer
        interval: root.swipeHoldMs
        onTriggered: {
            root.holding = false
            root.springBack()
        }
    }

    Timer {
        id: confirmTimer
        interval: root.confirmMs
        // The skip has not brought the cover expected: back to the one Media names.
        onTriggered: {
            if (Media.coverArtId.length > 0 && Media.coverArtId !== root.shownId())
                root.slideTo(Media.coverArtId, -root.direction)
        }
    }

    Timer {
        id: askNextTimer
        interval: 3000
        onTriggered: if (root.asksNext) Media.requestNext()
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
        id: springAnim
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
                springAnim.stop()
                holdTimer.stop()
                root.holding = false
                root.dragged = root.front
                const at = Math.max(-0.99, Math.min(0.99, root.front.x / root.swipeReach))
                root.dragOrigin = Math.atanh(at) * root.swipeReach / root.swipeFollow
                root.dragX = activeTranslation.x
                root.swipeSpeed.start(root.dragX)
                root.follow()
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

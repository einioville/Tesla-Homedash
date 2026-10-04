import QtQuick
import frontend_v2

// A box whose content slides out from UNDER the item above it, set back a
// little (smaller and dimmer), and then comes forward to sit level with its
// neighbours. Hiding runs it backwards.
//
// The box itself grows from 0 to `fullHeight` while the content travels down
// from one full height above, clipped to the box, so in a Column the content
// emerges from the edge it shares with the item above and pushes everything
// below it down smoothly. That edge is what reads as "under": nothing has to
// be drawn on top of anything, which matters because the cards here are
// translucent and a row has no background of its own to hide behind.
//
// Driven imperatively, because the caller knows what a plain `shown` binding
// cannot: the ORDER. show(delay) / hide(delay) take the delay that makes a run
// of boxes fall like dominoes; snap(shown) places one without animating, for a
// box built while its view appears.
//
// Put the content inside as children; they fill the box's width at
// `fullHeight`, which the caller sets from the content (a row's height).
Item {
    id: reveal

    default property alias content: body.data

    // The content's full height; the box grows to it.
    property real fullHeight: 0

    // 0 = tucked under the item above, 1 = in place.
    property real slide: 1
    // 0 = set back, 1 = level with its neighbours.
    property real lift: 1

    height: fullHeight * slide
    // A Column skips an invisible item outright, so a hidden box takes no
    // spacing either.
    visible: slide > 0
    clip: slide < 1

    function show(delay) {
        concealing.stop()
        if (slide >= 1 && lift >= 1)
            return
        if (slide <= 0)
            lift = 0
        showPause.duration = Math.max(0, delay || 0)
        revealing.restart()
    }

    function hide(delay) {
        revealing.stop()
        if (slide <= 0)
            return
        hidePause.duration = Math.max(0, delay || 0)
        concealing.restart()
    }

    function snap(shown) {
        revealing.stop()
        concealing.stop()
        slide = shown ? 1 : 0
        lift = shown ? 1 : 0
    }

    Item {
        id: body
        width: reveal.width
        height: reveal.fullHeight
        y: -(1 - reveal.slide) * reveal.fullHeight
        scale: Theme.revealSetBackScale + (1 - Theme.revealSetBackScale) * reveal.lift
        opacity: Theme.revealSetBackOpacity + (1 - Theme.revealSetBackOpacity) * reveal.lift
    }

    SequentialAnimation {
        id: revealing

        PauseAnimation { id: showPause }
        NumberAnimation {
            target: reveal
            property: "slide"
            to: 1
            duration: Theme.revealSlideDuration
            easing.type: Easing.OutCubic
        }
        NumberAnimation {
            target: reveal
            property: "lift"
            to: 1
            duration: Theme.revealLiftDuration
            easing.type: Easing.OutCubic
        }
    }

    SequentialAnimation {
        id: concealing

        PauseAnimation { id: hidePause }
        ParallelAnimation {
            NumberAnimation {
                target: reveal
                property: "lift"
                to: 0
                duration: Theme.concealDuration
                easing.type: Easing.InOutCubic
            }
            NumberAnimation {
                target: reveal
                property: "slide"
                to: 0
                duration: Theme.concealDuration
                easing.type: Easing.InOutCubic
            }
        }
    }
}

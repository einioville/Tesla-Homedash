import QtQuick

// Press area for a stepping button (+ / −): a tap steps once, a hold keeps
// stepping. Shared by the climate card's target arrows and the Options view's
// numeric steppers, so both feel the same under a finger.
//
// A tap steps on RELEASE, like any button, so a press that turns into a drag
// (the settings pane scrolling) steps nothing. A hold starts repeating after
// `delay`, and the release that ends a hold adds no extra step — without that,
// any tap held a little too long stepped twice.
//
// `canStep` stops it at a limit: the repeat halts and a tap does nothing, so a
// held button never hammers against a bound. `finished()` fires once the press
// is over however it ended, for a caller that batches its steps and commits
// them in one write.
MouseArea {
    id: area

    // False at a limit.
    property bool canStep: true
    // Hold time before the first repeat, then the time between repeats.
    property int delay: 400
    property int interval: 120

    signal stepped()
    signal finished()

    // Whether this press has already stepped on the timer.
    property bool repeated: false

    onPressed: {
        area.repeated = false
        repeatTimer.interval = area.delay
        repeatTimer.restart()
    }

    onReleased: (mouse) => {
        repeatTimer.stop()
        if (!area.repeated && area.canStep && area.contains(Qt.point(mouse.x, mouse.y)))
            area.stepped()
        area.finished()
    }

    onCanceled: {
        repeatTimer.stop()
        area.finished()
    }

    Timer {
        id: repeatTimer
        repeat: true
        onTriggered: {
            if (!area.canStep) {
                stop()
                return
            }
            interval = area.interval
            area.repeated = true
            area.stepped()
        }
    }
}

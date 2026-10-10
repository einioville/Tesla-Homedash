import QtQuick
import frontend_v2

// Mouse wheel → value steps, for any control that steps a value (a slider, a
// [−] [+] stepper). Lay it over the control; it takes the wheel only, so
// presses, drags and taps go straight through to the control underneath.
//
// The same contract as HoldRepeatArea: `stepped(direction)` per step (+1 for
// wheel away from the user, -1 toward), then `settled()` once the wheel has
// been still for `settleDelay` ms. A caller that writes somewhere expensive
// steps a pending value on `stepped` and commits once on `settled`, so a quick
// spin of five notches is one write, not five.
//
// One step per notch (120 eighths of a degree). A touchpad sends the same
// travel in many small deltas, which are added up, so it steps at the same rate.
//
// While the wheel is over the control it never scrolls the view around it: a
// value that stops changing at its limit while the page starts moving instead
// would be the worse surprise.
MouseArea {
    id: area

    signal stepped(int direction)
    signal settled()

    property int settleDelay: 400

    property real accumulated: 0

    acceptedButtons: Qt.NoButton

    onWheel: (wheel) => {
        const delta = wheel.angleDelta.y !== 0 ? wheel.angleDelta.y : wheel.angleDelta.x
        area.accumulated += delta
        while (Math.abs(area.accumulated) >= 120) {
            const direction = area.accumulated > 0 ? 1 : -1
            area.accumulated -= direction * 120
            area.stepped(direction)
        }
        settle.restart()
        wheel.accepted = true
    }

    Timer {
        id: settle
        interval: area.settleDelay
        onTriggered: {
            area.accumulated = 0
            area.settled()
        }
    }
}

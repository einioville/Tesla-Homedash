import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
import frontend_v2

// HVAC power button, and the timeline of what a switch looks like. The disc and its
// glow take the state's colour: red off, yellow while a switch is under way, green on.
//
// A switch sends a wave out from the button to the card's rim, its light trailing off
// behind the front, and the rim stays lit in yellow while the car is asked. When the
// answer comes, the rim takes the new state's colour as the wave sets off back in, and
// the button turns from the moment the front reaches it until the tail has poured in —
// green when climate came on, red when it went off or the switch failed. The card draws
// the wave (ClimateWave) from `waveFront` and its neighbours, and tells this item how
// far its farthest corner is (`waveExtent`).
//
// Load-bearing:
//  - Pending is the BACKEND's state (HvacPowerStatePending, streamed to every
//    display), so a switch made on any display waves on all of them. A press here
//    shows it at once and holds it until the backend answers; the backend refuses
//    some presses without a word (rate limit, a state it cannot switch from), so
//    after awaitMs with no answer the wave goes back in.
//  - Every colour runs through the hues between — red, orange, yellow, green — as
//    one number (a key: 0 off, 1 pending, 2 on) mapped to HSV. A ColorAnimation
//    goes straight across RGB, through brown.
//  - On the way back the button's colour is driven by the front's position, not by
//    a timer, so it starts exactly when the wave touches the button whatever the
//    easing or the card's size.
//  - A wave runs to its end before the next starts, so an answer that arrives
//    while the wave is still going out turns it back only once it has reached the rim.
//  - Off the screen nothing animates: the view's last state is set as it is.
Item {
    id: starter

    property string powerState: ""
    property int iconSize: 100
    // Gated by the owning view (DashboardView's isCurrent).
    property bool isCurrent: true
    // From the button's centre to the card's farthest corner, in px.
    property real waveExtent: 0
    signal clicked()

    // How long a press waits for the backend to report the switch as pending.
    readonly property int awaitMs: 5000

    // For the card's wave. The front is its leading edge, in px from the button's
    // centre; inbound, it runs toward the button and its tail lies outside it.
    readonly property real waveFront: timeline.front
    readonly property bool waveInbound: timeline.inbound
    readonly property bool waveShown: timeline.waving || waveIn.running
    readonly property bool waveMoving: waveOut.running || waveIn.running
    readonly property color waveColor: hueAt(timeline.rimKey, Theme.glowOff, Theme.glowPending, Theme.glowOn)

    readonly property real buttonRadius: iconSize / 2
    readonly property bool switchable: powerState === "HvacPowerStateOn" || powerState === "HvacPowerStateOff"
    readonly property bool pending: awaiting || powerState === "HvacPowerStatePending"
    // Where the colour settles when nothing is pending. A state the car reports
    // that is neither on nor off (no data yet, preconditioning) stays yellow.
    readonly property real restKey: powerState === "HvacPowerStateOn" ? 2
                                  : powerState === "HvacPowerStateOff" ? 0 : 1

    // A press is waiting for the backend's pending state.
    property bool awaiting: false

    function hueAt(key, off, pending, on) {
        var a = key <= 1 ? off : pending
        var b = key <= 1 ? pending : on
        var f = key <= 1 ? key : key - 1
        return Qt.hsva(a.hsvHue + (b.hsvHue - a.hsvHue) * f,
                       a.hsvSaturation + (b.hsvSaturation - a.hsvSaturation) * f,
                       a.hsvValue + (b.hsvValue - a.hsvValue) * f, 1)
    }

    function press() {
        // The backend switches only from on or off; a press during a switch is spent.
        if (starter.pending || !starter.switchable)
            return
        starter.awaiting = true
        awaitTimer.restart()
        starter.clicked()
    }

    onPowerStateChanged: {
        awaiting = false
        awaitTimer.stop()
    }
    onPendingChanged: Qt.callLater(sync)
    onRestKeyChanged: Qt.callLater(sync)
    onIsCurrentChanged: sync()
    Component.onCompleted: {
        snap()
        timeline.ready = true
    }

    Timer {
        id: awaitTimer
        interval: starter.awaitMs
        onTriggered: starter.awaiting = false
    }

    // What is on screen, and where it is heading.
    QtObject {
        id: timeline
        property real buttonKey: 0
        property real rimKey: 0
        property real front: 0
        property bool inbound: false
        property bool waving: false
        // The way back: from the button's colour when it set off to the answer's.
        property real fromKey: 1
        property real answerKey: 0
        property bool ready: false

        // The button turns while the wave pours in: from the front touching it
        // until the end of the tail has.
        onFrontChanged: {
            if (!inbound || !waveIn.running)
                return
            var poured = Math.max(0, Math.min(1, (starter.buttonRadius - front) / Theme.hvacWaveTail))
            buttonKey = fromKey + (answerKey - fromKey) * poured
        }
    }

    function snap() {
        waveOut.stop()
        waveIn.stop()
        settle.stop()
        timeline.waving = starter.pending
        timeline.inbound = false
        timeline.buttonKey = starter.pending ? 1 : starter.restKey
        timeline.rimKey = timeline.buttonKey
        timeline.front = starter.pending ? starter.waveExtent + Theme.hvacWaveTail : starter.buttonRadius
    }

    function sync() {
        if (!timeline.ready)
            return
        if (!starter.isCurrent) {
            snap()
            return
        }
        if (waveOut.running || waveIn.running)
            return
        if (starter.pending && !timeline.waving) {
            settle.stop()
            timeline.waving = true
            timeline.inbound = false
            timeline.rimKey = 1
            timeline.front = starter.buttonRadius
            waveOut.restart()
        } else if (!starter.pending && timeline.waving) {
            timeline.waving = false
            timeline.inbound = true
            timeline.fromKey = timeline.buttonKey
            timeline.answerKey = starter.restKey
            waveIn.restart()
        } else if (!starter.pending && timeline.buttonKey !== starter.restKey
                   && !(settle.running && settle.to === starter.restKey)) {
            // A change that did not come through a switch here or on another
            // display (climate started from the car's app): the button alone.
            settle.to = starter.restKey
            settle.restart()
        }
    }

    // Out: the button turns yellow as the wave leaves it; the front runs on until
    // the end of its tail has passed the farthest corner.
    ParallelAnimation {
        id: waveOut
        NumberAnimation {
            target: timeline; property: "buttonKey"; to: 1
            duration: Theme.hvacColorDuration; easing.type: Easing.InOutSine
        }
        SequentialAnimation {
            PauseAnimation { duration: 120 }
            NumberAnimation {
                target: timeline; property: "front"
                from: starter.buttonRadius; to: starter.waveExtent + Theme.hvacWaveTail
                duration: Theme.hvacWaveOutDuration; easing.type: Easing.OutQuad
            }
        }
        onFinished: Qt.callLater(starter.sync)
    }

    // Back: the rim takes the answer's colour as the wave sets off from the farthest
    // corner, and runs on until its tail has poured into the button.
    ParallelAnimation {
        id: waveIn
        NumberAnimation {
            target: timeline; property: "rimKey"; to: timeline.answerKey
            duration: Theme.hvacColorDuration; easing.type: Easing.InOutSine
        }
        NumberAnimation {
            target: timeline; property: "front"
            from: starter.waveExtent; to: starter.buttonRadius - Theme.hvacWaveTail
            duration: Theme.hvacWaveInDuration; easing.type: Easing.InOutSine
        }
        onFinished: {
            timeline.buttonKey = timeline.answerKey
            timeline.inbound = false
            Qt.callLater(starter.sync)
        }
    }

    NumberAnimation {
        id: settle
        target: timeline
        property: "buttonKey"
        duration: Theme.hvacColorDuration
        easing.type: Easing.InOutSine
    }

    // The disc and its power glyph (the glyph on a 180-unit grid), drawn rather than
    // an image so the colour can move through every hue between states.
    Item {
        id: disc
        anchors.centerIn: parent
        width: starter.iconSize
        height: starter.iconSize
        visible: false
        layer.enabled: true

        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: starter.hueAt(timeline.buttonKey, Theme.hvacDiscOff, Theme.hvacDiscPending, Theme.hvacDiscOn)
        }

        Shape {
            id: glyph
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            readonly property real u: width / 180

            ShapePath {
                strokeColor: "white"
                strokeWidth: 10 * glyph.u
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathAngleArc {
                    centerX: 90 * glyph.u
                    centerY: 90 * glyph.u
                    radiusX: 39.26 * glyph.u
                    radiusY: 39.26 * glyph.u
                    startAngle: -52.3
                    sweepAngle: 284.1
                }
            }
            ShapePath {
                strokeColor: "white"
                strokeWidth: 10 * glyph.u
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                startX: 90 * glyph.u
                startY: 46.93 * glyph.u
                PathLine { x: 90 * glyph.u; y: 86.93 * glyph.u }
            }
        }
    }

    MultiEffect {
        anchors.fill: disc
        source: disc
        autoPaddingEnabled: true
        shadowEnabled: true
        shadowColor: starter.hueAt(timeline.buttonKey, Theme.glowOff, Theme.glowPending, Theme.glowOn)
        shadowBlur: 1.0
        blurMax: 32
        shadowHorizontalOffset: 0
        shadowVerticalOffset: 0
        shadowOpacity: 0.85
    }

    MouseArea {
        anchors.fill: parent
        onClicked: starter.press()
    }
}

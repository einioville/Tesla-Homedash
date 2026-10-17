import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
import frontend_v2

// HVAC power button, and the timeline of what a switch looks like. The disc and its
// glow take the state's colour: red off, yellow while a switch is under way, green on.
//
// A switch sends a wave out from the button across the dashboard's water (ClimateWave),
// and the backdrop's light it has passed turns yellow. While the car is asked, the
// button sends the next wave each time the last one's tail has passed the farthest
// corner. When the answer comes, the background and
// the button take the new state's colour together — green when climate came on, red
// when it went off or the switch failed — and as the water calms, the background fades
// back to the cover's colours. The dashboard draws the wave from `waveFront`,
// `pushFront` and their neighbours, and tells this item how far it runs (`waveOutTo`).
//
// Load-bearing:
//  - Pending is the BACKEND's state (HvacPowerStatePending, streamed to every
//    display), so a switch made on any display waves on all of them. A press here
//    shows it at once and holds it until the backend answers; the backend refuses
//    some presses without a word (rate limit, a state it cannot switch from), so
//    after awaitMs with no answer the switch ends as it began.
//  - Every colour runs through the hues between — red, orange, yellow, green — as
//    one number (a key: 0 off, 1 pending, 2 on) mapped to HSV. A ColorAnimation
//    goes straight across RGB, through brown.
//  - The first wave runs to the edges before the answer shows, so the whole
//    background is yellow when it turns.
//  - Off the screen nothing animates: the view's last state is set as it is.
Item {
    id: starter

    property string powerState: ""
    property int iconSize: 100
    // Gated by the owning view (DashboardView's isCurrent).
    property bool isCurrent: true
    // Where the first wave runs out to, in px from the button's centre: past the
    // view's farthest corner (ClimateWave).
    property real waveOutTo: 0
    signal clicked()

    // How long a press waits for the backend to report the switch as pending.
    readonly property int awaitMs: 5000

    // For the dashboard's wave, in px from the button's centre. The first wave's front
    // paints the background; the water is pushed at pushFront, which runs with the
    // first wave and then with each one sent after it while the car is asked.
    readonly property real waveFront: timeline.front
    readonly property real pushFront: waveOut.running ? timeline.front : timeline.nextFront
    readonly property bool pushing: waveOut.running || waves.running
    // Each wave's own draw of how it breaks up and of its rings (climatewater.frag's
    // `seed`, `rings`, `lobes` and `shape`), so no two look alike.
    readonly property vector4d waveSeed: timeline.seed
    readonly property vector4d waveRings: timeline.rings
    readonly property vector4d waveLobes: timeline.lobes
    readonly property vector4d waveShape: timeline.shape
    readonly property bool waveShown: timeline.waving
    // How much of the painted colour and of the water show, 1 to 0 as they fade.
    readonly property real paintLevel: timeline.paintLevel
    readonly property real waterLevel: timeline.waterLevel
    // The button's own colours, so the wave is the button's light spreading.
    readonly property real waveKey: timeline.waveKey
    readonly property color waveColor: hueAt(timeline.waveKey, Theme.hvacDiscOff, Theme.hvacDiscPending, Theme.hvacDiscOn)

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
        property real waveKey: 0
        property real front: 0
        property real nextFront: 0
        property vector4d seed: Qt.vector4d(0, 0, 0, 1)
        property vector4d rings: Qt.vector4d(1, 0, 1, 1)
        property vector4d lobes: Qt.vector4d(3, 5, 11, 7)
        property vector4d shape: Qt.vector4d(1, 1, 0.4, 4)
        property real paintLevel: 1
        property real waterLevel: 1
        property bool waving: false
        property real answerKey: 0
        property bool ready: false
    }

    // A wave's draw (climatewater.frag has what each number does), in ranges that
    // keep every wave the same kind of wave. The last ring trails the front by less
    // than the tail, so it too has passed the farthest corner when the next wave sets
    // off.
    function reseed() {
        function between(low, high) { return low + (high - low) * Math.random() }
        function pick(choices) { return choices[Math.floor(choices.length * Math.random())] }
        timeline.seed = Qt.vector4d(between(0, 2 * Math.PI), between(0, 2 * Math.PI),
                                    between(0, 2 * Math.PI), between(0.85, 1.15))
        timeline.rings = Qt.vector4d(pick([1, 2, 3]), between(80, 110), between(0.8, 1.2), between(0.55, 0.8))
        timeline.lobes = Qt.vector4d(pick([2, 3, 4]), pick([5, 6, 7]), pick([9, 11, 13]), pick([5, 6, 7, 8]))
        timeline.shape = Qt.vector4d(between(0.6, 1.4), pick([-1, 1]) * between(0.6, 1.5),
                                     between(0.25, 0.5), pick([3, 4]))
    }

    function snap() {
        waveOut.stop()
        waves.stop()
        answer.stop()
        settle.stop()
        timeline.waving = starter.pending
        timeline.buttonKey = starter.pending ? 1 : starter.restKey
        timeline.waveKey = timeline.buttonKey
        timeline.front = starter.pending ? starter.waveOutTo : starter.buttonRadius
        timeline.paintLevel = 1
        timeline.waterLevel = 1
    }

    function sync() {
        if (!timeline.ready)
            return
        if (!starter.isCurrent) {
            snap()
            return
        }
        if (waveOut.running || answer.running)
            return
        if (starter.pending && !timeline.waving) {
            settle.stop()
            timeline.waving = true
            timeline.waveKey = 1
            timeline.paintLevel = 1
            timeline.waterLevel = 1
            timeline.front = starter.buttonRadius
            reseed()
            waveOut.restart()
        } else if (starter.pending) {
            if (!waves.running)
                waves.restart()
        } else if (timeline.waving) {
            waves.stop()
            timeline.answerKey = starter.restKey
            answer.restart()
        } else if (timeline.buttonKey !== starter.restKey
                   && !(settle.running && settle.to === starter.restKey)) {
            // A change that did not come through a switch here or on another
            // display (climate started from the car's app): the button alone.
            settle.to = starter.restKey
            settle.restart()
        }
    }

    // Out: the button turns yellow as the wave leaves it; the front runs on, at the
    // water's own speed, until the end of its tail has passed the view's farthest
    // corner.
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
                from: starter.buttonRadius; to: starter.waveOutTo
                duration: Theme.hvacWaveOutDuration
            }
        }
        onFinished: Qt.callLater(starter.sync)
    }

    // While the car is asked: the next wave, pushed out as the first was, each one
    // setting off as the last one's tail passes the farthest corner.
    SequentialAnimation {
        id: waves
        loops: Animation.Infinite
        ScriptAction { script: starter.reseed() }
        NumberAnimation {
            target: timeline; property: "nextFront"
            from: starter.buttonRadius; to: starter.waveOutTo
            duration: Theme.hvacWaveOutDuration
        }
    }

    // The answer: the background and the button take its colour together, the water
    // calms, and the background fades back to the cover's colours as it does.
    ParallelAnimation {
        id: answer
        NumberAnimation {
            target: timeline; property: "waveKey"; to: timeline.answerKey
            duration: Theme.hvacColorDuration; easing.type: Easing.InOutSine
        }
        NumberAnimation {
            target: timeline; property: "buttonKey"; to: timeline.answerKey
            duration: Theme.hvacColorDuration; easing.type: Easing.InOutSine
        }
        NumberAnimation {
            target: timeline; property: "waterLevel"; to: 0
            duration: Theme.hvacWaterFade; easing.type: Easing.InOutSine
        }
        SequentialAnimation {
            PauseAnimation { duration: Theme.hvacColorDuration }
            NumberAnimation {
                target: timeline; property: "paintLevel"; to: 0
                duration: Theme.hvacWavePaintFade; easing.type: Easing.InOutSine
            }
        }
        onFinished: {
            timeline.waving = false
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

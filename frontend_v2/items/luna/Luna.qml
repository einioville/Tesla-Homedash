import QtQuick

// Luna — a little memorial for our dog. She lives along the bottom of the
// dashboard: ambling left and right, pausing to stand or sit, forever. Tapping
// her sits her down — even mid-stroll (the hitbox rides along with her).
//
// She is driven by a tiny, DATA-DRIVEN behaviour state machine so new behaviours
// (sleeping, eating, …) are a drop-in later — see `behaviours` below:
//   1. add the frame art under resources/Luna/ (and to CMakeLists' resources),
//   2. add an entry to `behaviours` (frames + timing + weight),
//   3. list its name in `enabledBehaviours`.
// Nothing else needs to change; the picker, frame cycler and rest/walk plumbing
// already handle any number of behaviours.
//
// The sprite art faces RIGHT; when she walks left the image is mirrored
// horizontally (a Scale transform), so one set of frames covers both directions.
//
// All per-frame work (frame cycling + the walk animation) is gated on `running`,
// so a parent can freeze her when the dashboard isn't visible — matching the
// ViewController's freeze-while-hidden convention. When `running` goes false she
// stops mid-stride and resumes with a fresh stroll when it returns.
Item {
    id: luna

    // --- Public knobs -----------------------------------------------------
    // Master gate for all animation/scheduling. Bind to (view is current &&
    // feature enabled); false freezes her in place.
    property bool running: true

    // Her rendered height as a fraction of the parent's height (~5% ≈ a small
    // dog trotting along the floor). Width follows from the sprite's aspect.
    property real heightFraction: 0.05

    // How far her feet sit above the parent's bottom edge (px). Aligns her with
    // the dashboard's card "floor" (the grid margin) by default.
    property real bottomMargin: 10

    // Amble speed in px/second. Size-relative so the gait reads the same if she
    // is resized — she covers a little under one body-length per stride cycle.
    property real walkSpeed: width * 2.2

    // Tap-target padding (px) grown around the sprite so she's easy to tap on the
    // touchscreen. The hitbox is a child of the sprite, so it follows her.
    property real hitPadding: 8

    // --- Sizing / placement ----------------------------------------------
    // All poses are exported on a 150px-TALL canvas with the feet on the bottom
    // edge, but at their own native WIDTH — side-view walk/stand = 183×150, the
    // front-view sit = 92×150. We anchor on HEIGHT: each pose renders at
    // `heightFraction` of the parent's height (times its optional `heightScale`),
    // and WIDTH follows from that pose's own native aspect — no frame is
    // distorted, and the front-view sit reads narrower than the side-view walker,
    // as a real dog does. `y` plants her bottom on the floor line, so a taller
    // pose would grow UPWARD with her feet staying put.
    readonly property var _pose: behaviours[behaviour] || behaviours["idle"]
    readonly property real _baseHeight: (parent ? parent.height : 0) * heightFraction
    height: _baseHeight * (_pose.heightScale || 1.0)
    width: height * (_pose.nativeW / _pose.nativeH)
    y: (parent ? parent.height : 0) - height - bottomMargin

    // --- Sprite frames ----------------------------------------------------
    readonly property string _dir: "qrc:/resources/Luna/"
    readonly property var _walkFrames: [
        _dir + "walking_1.png", _dir + "walking_2.png",
        _dir + "walking_3.png", _dir + "walking_4.png",
        _dir + "walking_5.png"
    ]
    readonly property string _stationaryFrame: _dir + "stationary.png"
    readonly property string _sittingFrame: _dir + "sitting_1.png"

    // --- Behaviour registry ----------------------------------------------
    // Each behaviour: which frames to show, how fast to cycle them (ms; 0 = a
    // single held frame), whether it moves her across the floor, its random
    // selection weight, its dwell range (ms, for non-moving behaviours), and the
    // frames' native size in px — all poses share the 150px-tall canvas, only the
    // width varies. An optional `heightScale` (rendered-height multiplier vs the
    // base, default 1) lets a pose render taller/shorter if its art isn't on the
    // shared canvas. Add sleeping/eating here, then to `enabledBehaviours`.
    readonly property var behaviours: ({
        "idle":    { frames: [_stationaryFrame], frameInterval: 0,   moves: false, weight: 1.0, minMs: 1600, maxMs: 5200,  nativeW: 183, nativeH: 150 },
        "walking": { frames: _walkFrames,        frameInterval: 110, moves: true,  weight: 2.2,                            nativeW: 183, nativeH: 150 },
        "sitting": { frames: [_sittingFrame],    frameInterval: 0,   moves: false, weight: 0.9, minMs: 4000, maxMs: 11000, nativeW: 92,  nativeH: 150 }
        // "sleeping": { frames: [_dir+"sleeping_1.png", _dir+"sleeping_2.png"], frameInterval: 340, moves: false, weight: 0.6, minMs: 7000, maxMs: 16000, nativeW: <px>, nativeH: <px> },
        // "eating":   { frames: [_dir+"eating_1.png",   _dir+"eating_2.png"],   frameInterval: 180, moves: false, weight: 0.5, minMs: 3500, maxMs: 9000,  nativeW: <px>, nativeH: <px> },
    })
    readonly property var enabledBehaviours: ["idle", "walking", "sitting"]

    // --- Runtime state ----------------------------------------------------
    property string behaviour: "idle"
    property var currentFrames: [_stationaryFrame]
    property int frameIndex: 0
    property bool facingRight: true

    readonly property int _frameInterval: (behaviours[behaviour] && behaviours[behaviour].frameInterval) || 0
    readonly property bool _animatingFrames: currentFrames.length > 1 && _frameInterval > 0

    // --- Render -----------------------------------------------------------
    Image {
        id: sprite
        anchors.fill: parent
        source: luna.currentFrames[luna.frameIndex] || luna._stationaryFrame
        fillMode: Image.PreserveAspectFit
        // Downscaled pixel art: mipmapped bilinear minification stays stable
        // (no shimmer) while she moves, unlike nearest-neighbour.
        smooth: true
        mipmap: true
        // Mirror horizontally when she heads left; the art natively faces right.
        transform: Scale {
            origin.x: luna.width / 2
            xScale: luna.facingRight ? 1 : -1
        }
    }

    // Tap-to-sit hitbox. A child of the sprite Item, so it tracks her position as
    // she walks (and grows when she sits). Padded out for an easy touch target.
    MouseArea {
        anchors.fill: parent
        anchors.margins: -luna.hitPadding
        onClicked: luna.sit()
    }

    // Advances the walk (or any multi-frame) cycle. Auto-pauses via `running`.
    Timer {
        id: frameTimer
        repeat: true
        running: luna.running && luna._animatingFrames
        interval: Math.max(1, luna._frameInterval)
        onTriggered: luna.frameIndex = (luna.frameIndex + 1) % luna.currentFrames.length
    }

    // Holds a non-moving behaviour (idle/sleeping/eating) for its dwell, then
    // decides what to do next.
    Timer {
        id: restTimer
        repeat: false
        onTriggered: luna._scheduleNext()
    }

    // Carries her across the floor at a constant speed; on natural completion she
    // pauses before the next decision. Stopping it (running → false) does NOT
    // emit finished(), so a freeze never triggers a stray transition.
    NumberAnimation {
        id: walkAnim
        target: luna
        property: "x"
        easing.type: Easing.Linear
        onFinished: luna._startRest("idle")
    }

    // --- Behaviour machine ------------------------------------------------
    function _randRange(min, max) {
        return min + Math.random() * (max - min)
    }

    // Weighted-random pick among the currently enabled behaviours.
    function _pickBehaviour() {
        var total = 0
        for (var i = 0; i < enabledBehaviours.length; i++)
            total += behaviours[enabledBehaviours[i]].weight
        var r = Math.random() * total
        for (i = 0; i < enabledBehaviours.length; i++) {
            r -= behaviours[enabledBehaviours[i]].weight
            if (r <= 0)
                return enabledBehaviours[i]
        }
        return enabledBehaviours[0]
    }

    function _scheduleNext() {
        if (!running)
            return
        var name = _pickBehaviour()
        if (behaviours[name].moves)
            _startWalk(name)
        else
            _startRest(name)
    }

    // Public: sit her down now, interrupting whatever she's doing (a tap, or a
    // caller). She holds the sit for its dwell, then resumes wandering.
    function sit() {
        if (!running)
            return
        walkAnim.stop()     // stop mid-stride if she was walking
        restTimer.stop()    // cancel any pending decision
        _startRest("sitting")
    }

    // Switches pose while keeping her CENTRED over the same floor spot: poses
    // have different widths (the front-view sit is narrower than the side-view
    // walker) and `x` anchors her left edge, so an uncompensated switch would
    // visibly shunt her sideways. Clamped so the recentre never pushes her
    // off-screen at the edges.
    function _applyBehaviour(name) {
        var cx = x + width / 2
        behaviour = name
        currentFrames = behaviours[name].frames
        frameIndex = 0
        var maxX = Math.max(0, (parent ? parent.width : width) - width)
        x = Math.max(0, Math.min(maxX, cx - width / 2))
    }

    function _startRest(name) {
        var cfg = behaviours[name]
        _applyBehaviour(name)
        restTimer.interval = _randRange(cfg.minMs, cfg.maxMs)
        restTimer.restart()
    }

    function _startWalk(name) {
        if (!parent)
            return
        _applyBehaviour(name)

        var minX = 0
        var maxX = Math.max(0, parent.width - width)
        var target = _randRange(minX, maxX)

        // Enforce a real stroll so she doesn't just twitch in place: if the
        // random target is too close, head off toward the roomier side.
        var minDist = width * 1.5
        if (Math.abs(target - x) < minDist) {
            if (x < (minX + maxX) / 2)
                target = Math.min(maxX, x + _randRange(minDist, minDist * 4))
            else
                target = Math.max(minX, x - _randRange(minDist, minDist * 4))
        }

        facingRight = target >= x
        var dist = Math.abs(target - x)
        walkAnim.to = target
        walkAnim.duration = Math.max(250, (dist / walkSpeed) * 1000)
        walkAnim.restart()
    }

    onRunningChanged: {
        if (running) {
            _scheduleNext()             // resume with a fresh decision
        } else {
            walkAnim.stop()             // freeze mid-stride
            restTimer.stop()
        }
    }

    Component.onCompleted: {
        // Drop her in at a random spot along the floor, then start wandering.
        if (parent)
            x = _randRange(0, Math.max(0, parent.width - width))
        if (running)
            _scheduleNext()
    }
}

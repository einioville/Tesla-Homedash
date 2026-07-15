import QtQuick

// Luna — a little memorial for our dog. She lives along the bottom of the
// dashboard, ambling left and right and pausing between strolls to stand, sniff
// the ground, sit, nap, or eat — forever.
//
// She is driven by a tiny, DATA-DRIVEN behaviour state machine. Every pose is one
// entry in the `behaviours` registry (frames + timing + native size); how each is
// TRIGGERED falls into four groups:
//   • random pool  — picked at each decision point, weighted (see `enabledBehaviours`):
//                    idle (stand), walking, sitting, sleeping.
//   • post-walk    — sniffing: she sniffs the ground wherever a stroll ends.
//   • scheduled    — eating: fires at fixed LOCAL clock hours (`eatingHours`, 07:00
//                    & 16:00) once each per day and lasts one eating dwell (~5 min).
//   • tap          — a tap sits her (even mid-stroll); a SECOND tap within
//                    `sleepTapWindowMs` settles her into a nap; tapping a SLEEPING Luna
//                    wakes her (she walks off); a tap while eating is ignored. RIGHT-
//                    click forces a meal now — a mouse-only dev/test hook the deployed
//                    touchscreen never triggers.
//
// Adding art later — sleeping/eating/sniffing already ship LIVE but with PLACEHOLDER
// frames (an existing pose stands in), so the whole machine — timing, transitions,
// the meal clock — runs today and only the pictures are stand-ins. To drop in real art:
//   1. add the frame PNGs under resources/Luna/ and list them in CMakeLists' resources,
//   2. point that behaviour's `frames` (and its `nativeW`/`nativeH`) at the new art.
// For a brand-new behaviour, also add its `behaviours` entry and — if it should be
// randomly chosen — its name to `enabledBehaviours`. Nothing else changes; the picker,
// frame cycler, scheduler and rest/walk plumbing handle any behaviour and frame count.
//
// The sprite art faces RIGHT; when she walks left the image is mirrored
// horizontally (a Scale transform), so one set of frames covers both directions.
//
// All per-frame work (frame cycling, the walk animation, the meal clock) is gated
// on `running`, so a parent can freeze her when the dashboard isn't visible —
// matching the ViewController's freeze-while-hidden convention. When `running` goes
// false she stops mid-stride and resumes with a fresh decision when it returns.
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

    // Local clock hours (24h) at which she eats, once per day each. Time-triggered,
    // outside the random pool; each meal lasts the "eating" behaviour's dwell (~5 min).
    property var eatingHours: [7, 16]

    // After a TAP sits her, the window (ms) in which a SECOND tap settles her into a
    // nap instead of just re-sitting — a deliberate "sit, then lie down" gesture. Left
    // alone past it she just serves out her sit dwell and wanders off as usual.
    property int sleepTapWindowMs: 5000

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
    // selection weight (only used for the random pool — see `enabledBehaviours`),
    // its dwell range (ms, for non-moving behaviours), and the frames' native size
    // in px — all poses share the 150px-tall canvas, only the width varies. An
    // optional `heightScale` (rendered-height multiplier vs the base, default 1)
    // lets a pose render taller/shorter if its art isn't on the shared canvas.
    //
    // sniffing/sleeping/eating currently REUSE an existing frame as a PLACEHOLDER
    // (noted per row) so the machine runs before their art exists — swap `frames`
    // and `nativeW`/`nativeH` for the real sprites (and add them to CMakeLists) later.
    readonly property var behaviours: ({
        "idle":     { frames: [_stationaryFrame], frameInterval: 0,   moves: false, weight: 1.0, minMs: 1600,   maxMs: 5200,   nativeW: 183, nativeH: 150 },
        "walking":  { frames: _walkFrames,        frameInterval: 110, moves: true,  weight: 2.2,                                nativeW: 183, nativeH: 150 },
        "sitting":  { frames: [_sittingFrame],    frameInterval: 0,   moves: false, weight: 0.9, minMs: 4000,   maxMs: 11000,  nativeW: 92,  nativeH: 150 },
        // Post-walk (not pooled): she sniffs the ground wherever a stroll ends.
        "sniffing": { frames: [_stationaryFrame], frameInterval: 0,   moves: false, weight: 0.0, minMs: 2200,   maxMs: 6000,   nativeW: 183, nativeH: 150 },  // placeholder art = stationary
        // Random pool: the occasional ~5 min nap; tapping her wakes her (see _wake).
        "sleeping": { frames: [_sittingFrame],    frameInterval: 0,   moves: false, weight: 0.4, minMs: 270000, maxMs: 330000, nativeW: 92,  nativeH: 150 },  // placeholder art = sitting
        // Scheduled (not pooled): fires at `eatingHours` each day, ~5 min fixed.
        "eating":   { frames: [_stationaryFrame], frameInterval: 0,   moves: false, weight: 0.0, minMs: 300000, maxMs: 300000, nativeW: 183, nativeH: 150 }   // placeholder art = stationary
    })
    // The RANDOM POOL she picks from at each decision point. sniffing (post-walk) and
    // eating (scheduled) are triggered directly and are deliberately excluded here.
    readonly property var enabledBehaviours: ["idle", "walking", "sitting", "sleeping"]

    // --- Runtime state ----------------------------------------------------
    property string behaviour: "idle"
    property var currentFrames: [_stationaryFrame]
    property int frameIndex: 0
    property bool facingRight: true

    // Meal-clock internals: how often the local time is polled, and the identity of
    // the last meal window already eaten ("<date>@<hour>") so each window fires once.
    readonly property int _scheduleTickMs: 30000
    property string _lastEatenWindow: ""

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

    // Tap hitbox. A child of the sprite Item, so it tracks her position as she walks
    // (and grows when she sits). Padded out for an easy touch target. LEFT tap/touch
    // goes to _handleTap (sit / nap / wake / ignore, per her current state); RIGHT click
    // is a mouse-only dev/test hook that forces a meal now (a touchscreen, with no right
    // button, never triggers it).
    MouseArea {
        anchors.fill: parent
        anchors.margins: -luna.hitPadding
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: (mouse) => {
            if (mouse.button === Qt.RightButton)
                luna._forceEat()
            else
                luna._handleTap()
        }
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
    // stops to sniff the ground before the next decision. Stopping it (running →
    // false) does NOT emit finished(), so a freeze never triggers a stray transition.
    NumberAnimation {
        id: walkAnim
        target: luna
        property: "x"
        easing.type: Easing.Linear
        onFinished: luna._startRest("sniffing")
    }

    // Meal clock. Ticks coarsely (she eats for minutes) while she's active and
    // starts her eating when the LOCAL time enters an `eatingHours` window she has
    // not eaten yet today. Frozen with everything else when `running` is false.
    Timer {
        id: mealTimer
        repeat: true
        running: luna.running
        interval: luna._scheduleTickMs
        onTriggered: luna._checkMealtime()
    }

    // Opened (via restart) when a tap sits her; while it runs, a second tap naps her.
    // Its RUNNING state is the whole signal — no onTriggered needed; when it lapses the
    // nap gesture simply closes. See _handleTap / sleepTapWindowMs.
    Timer {
        id: sleepWindowTimer
        repeat: false
        interval: luna.sleepTapWindowMs
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
    // caller). She holds the sit for its dwell, then resumes wandering. Sitting also
    // opens the brief tap-again-to-nap window (see sleepTapWindowMs / _handleTap).
    function sit() {
        if (!running)
            return
        walkAnim.stop()             // stop mid-stride if she was walking
        restTimer.stop()            // cancel any pending decision
        _startRest("sitting")
        sleepWindowTimer.restart()  // ...and open the "tap again to nap" window
    }

    // Tap dispatch: what a tap does depends on what she's up to. A tap WAKES her from a
    // nap (she sets off walking); a tap while eating is ignored so a stray touch can't
    // cut dinner short; a tap while she's sitting AND still inside the post-sit window
    // (see sleepTapWindowMs) settles her into a nap; any other tap just sits her.
    function _handleTap() {
        if (!running)
            return
        if (behaviour === "sleeping")
            _wake()
        else if (behaviour === "eating")
            return
        else if (behaviour === "sitting" && sleepWindowTimer.running)
            _startSleep()
        else
            sit()
    }

    // Woken from a nap by a tap: drop the rest of the sleep dwell and set off walking.
    function _wake() {
        restTimer.stop()    // cancel the remaining nap
        _startWalk("walking")
    }

    // A second tap shortly after sitting (see _handleTap) settles her into a nap.
    function _startSleep() {
        sleepWindowTimer.stop()     // window consumed
        _startRest("sleeping")      // restarts restTimer with the nap dwell
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

    // Scheduled meals. Called on each meal-clock tick (and on resume): if the LOCAL
    // time is inside an `eatingHours` window she hasn't eaten yet today, she starts
    // eating and this returns true. The window is one eating-dwell wide and keyed by
    // date+hour so it fires once per day. Returns false when no meal was started —
    // including when she is ALREADY eating (an active meal has its own dwell timer).
    function _checkMealtime() {
        if (!running || behaviour === "eating")
            return false
        var now = new Date()
        var windowMs = behaviours["eating"].minMs
        for (var i = 0; i < eatingHours.length; i++) {
            var start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), eatingHours[i], 0, 0, 0)
            var elapsed = now.getTime() - start.getTime()
            if (elapsed >= 0 && elapsed < windowMs) {
                var key = now.toDateString() + "@" + eatingHours[i]
                if (_lastEatenWindow !== key) {
                    _lastEatenWindow = key
                    _startEating()
                    return true
                }
                return false    // already ate this window
            }
        }
        return false
    }

    // Interrupt whatever she's doing and start her meal; its dwell (~5 min) runs her
    // back to a normal decision afterwards, like any other rest.
    function _startEating() {
        walkAnim.stop()     // stop mid-stride if a mealtime landed while walking
        restTimer.stop()    // cancel any pending decision / current rest
        _startRest("eating")
    }

    // Dev/test affordance: eat right now, bypassing the `eatingHours` schedule. Wired to
    // RIGHT-click (mouse only), so it's inert on the deployed touchscreen. Does NOT touch
    // `_lastEatenWindow`, so it never suppresses a real scheduled meal.
    function _forceEat() {
        if (!running || behaviour === "eating")
            return
        _startEating()
    }

    // Start (or restart, on unfreeze) her activity: if a meal is due right now she
    // eats, otherwise she makes a fresh decision. Keying off _checkMealtime's RETURN
    // (not the behaviour name) is what lets a freeze that happened MID-meal recover —
    // a stale "eating" pose left by the freeze no longer blocks a fresh decision.
    function _resume() {
        if (!running)
            return
        if (!_checkMealtime())
            _scheduleNext()
    }

    onRunningChanged: {
        if (running) {
            _resume()                   // re-check the meal clock, else a fresh decision
        } else {
            walkAnim.stop()             // freeze mid-stride
            restTimer.stop()
            sleepWindowTimer.stop()     // drop any half-open nap-tap window
        }
    }

    Component.onCompleted: {
        // Drop her in at a random spot along the floor, then start her up. A meal may
        // already be due at launch, so go through the same resume path as an unfreeze.
        if (parent)
            x = _randRange(0, Math.max(0, parent.width - width))
        _resume()
    }
}

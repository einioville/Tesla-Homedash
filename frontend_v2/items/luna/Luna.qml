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
// Every behaviour now has real art. To add or replace a pose's frames:
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
    // ONE shared art scale for every frame: the STANDING dog is `_refArtHeight`
    // (150) art px tall, and `heightFraction` maps that standing height onto the
    // screen. Frames are tight-cropped at that scale — a crouched sniff is simply
    // FEWER art px tall — and every frame renders at its TRUE size through the same
    // scale (see the sprite Image: sourceSize × _artScale). So a pose's PNG
    // dimensions ARE its rendered proportions: rescaling a PNG rescales the pose on
    // screen, and no frame is ever stretched to fit a box. The item itself is the
    // behaviour's BOUNDING BOX (`nativeW`/`nativeH` = its largest frame's art px,
    // per axis) — it drives placement, movement maths and the tap hitbox, while the
    // frames draw inside it anchored to her rear + the floor. `y` plants the box on
    // the floor line. The optional per-behaviour `heightScale` remains a fine-tune
    // for a pose that reads too big/small without re-exporting its art.
    readonly property int _refArtHeight: 150
    readonly property var _pose: behaviours[behaviour] || behaviours["idle"]
    readonly property real _baseHeight: (parent ? parent.height : 0) * heightFraction
    // Screen px per art px for the current pose.
    readonly property real _artScale: (_baseHeight / _refArtHeight) * (_pose.heightScale || 1.0)
    height: _pose.nativeH * _artScale
    width: _pose.nativeW * _artScale
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
    // Sniff poses: _1 = head raised, _2/_3 = nose at the ground (slightly different
    // head heights — the bob). Tight-cropped at the shared art scale, so each pose
    // has its own size and renders exactly as exported.
    readonly property var _sniffFrames: [
        _dir + "sniffing_1.png", _dir + "sniffing_2.png", _dir + "sniffing_3.png"
    ]
    // Sleeping: one curled pose is all the nap needs. It still lives in an ARRAY, and
    // the behaviour's frameInterval is already set, so appending a second frame here
    // (a breathing pose) is the ONLY edit needed to animate her — the frame cycler
    // stays dormant while a behaviour has just one frame.
    readonly property var _sleepFrames: [
        _dir + "sleeping_1.png"
    ]
    // Eating: she stands over the bowl (_1/_3) and dips in to eat (_2/_4). The two
    // head-up frames were drawn ~1.37x larger than the two dips — the bowl, the same
    // object in all four, measures ~63px across in _1/_3 vs ~47px in _2/_4 — so the
    // behaviour carries a `frameScale` to bring them onto one scale (see its row).
    readonly property var _eatFrames: [
        _dir + "eating_1.png", _dir + "eating_2.png",
        _dir + "eating_3.png", _dir + "eating_4.png"
    ]

    // --- Behaviour registry ----------------------------------------------
    // Each behaviour: which frames to show, how fast to cycle them (ms; 0 = a
    // single held frame), whether it moves her across the floor, its random
    // selection weight (only used for the random pool — see `enabledBehaviours`),
    // its dwell range (ms, for non-moving behaviours), and `nativeW`/`nativeH` —
    // the behaviour's BOUNDING BOX in art px: its largest frame per axis (equal to
    // the frame size when all frames match). Frames render at TRUE art scale inside
    // that box (see Sizing). An optional `heightScale` (default 1) fine-tunes a
    // pose that reads too big/small without re-exporting its art.
    //
    // `nativeW`/`nativeH` are the max of the behaviour's frame sizes per axis (the
    // per-row comments list them). A stale box never distorts art under the true-scale
    // model — it only widens the hitbox — but keep it current when frames are re-exported.
    //
    // Optional per-behaviour extras (absent → plain round-robin at frameInterval):
    //   frameHold  — per-frame-INDEX hold ms overriding frameInterval for that frame
    //                (e.g. the sniff's head-up frame lingers longer than one bob tick).
    //   frameStep  — function(currentIndex) → next index: a custom, possibly
    //                stochastic frame order (the sniff bob). Round-robin when absent.
    //   frameScale — per-frame-INDEX size multiplier, for a behaviour whose frames were
    //                drawn at inconsistent scales (the eating set). 1 = as exported.
    //                Fixes RELATIVE sizes within the behaviour; use `heightScale` to
    //                resize the pose as a whole.
    readonly property var behaviours: ({
        "idle":     { frames: [_stationaryFrame], frameInterval: 0,   moves: false, weight: 1.0, minMs: 1600,   maxMs: 5200,   nativeW: 183, nativeH: 150 },
        "walking":  { frames: _walkFrames,        frameInterval: 110, moves: true,  weight: 2.2,                                nativeW: 183, nativeH: 150 },
        "sitting":  { frames: [_sittingFrame],    frameInterval: 0,   moves: false, weight: 0.9, minMs: 4000,   maxMs: 11000,  nativeW: 92,  nativeH: 150 },
        // Post-walk (not pooled): she sniffs the ground wherever a stroll ends —
        // planted on the spot; WALKING is what carries her to the next sniff spot.
        // Starts head-up (_1, held a beat), then bobs nose-down 2<->3 and only
        // sometimes lifts back to _1.
        "sniffing": {
            frames: _sniffFrames, frameInterval: 150,
            frameHold: [420, 150, 150],                     // [head-up, bob, bob] ms
            frameStep: function (i) {
                if (i === 0)
                    return 1                                // head drops back down
                return Math.random() < 0.15 ? 0             // occasional head lift...
                                            : (i === 1 ? 2 : 1)  // ...else bob 2<->3
            },
            moves: false, weight: 0.0, minMs: 2600, maxMs: 7000,
            nativeW: 219, nativeH: 130                      // bbox of 219x130 / 211x100 / 216x100
        },
        // Random pool: the occasional ~5 min nap; tapping her wakes her (see _wake).
        // One held frame today — frameInterval is a pre-set slow "breathing" cadence
        // that stays dormant until a second frame is added to _sleepFrames.
        "sleeping": { frames: _sleepFrames,       frameInterval: 1100, moves: false, weight: 0.4, minMs: 270000, maxMs: 330000, nativeW: 184, nativeH: 90 },   // 184x90
        // Scheduled (not pooled): fires at `eatingHours` each day, ~5 min fixed. Head
        // mostly IN the bowl (the two dip frames trading off), lifting now and then to
        // chew — the same shape as the sniff bob, one notch slower.
        "eating": {
            frames: _eatFrames, frameInterval: 600,
            frameHold: [1040, 600, 1040, 600],              // [up, dip, up, dip] ms (2x slower)
            frameStep: function (i) {
                if (i === 0 || i === 2)                     // head up → back into the bowl
                    return i + 1
                return Math.random() < 0.2 ? i - 1          // ...occasionally lift to chew
                                           : (i === 1 ? 3 : 1)   // ...else dip <-> dip
            },
            // The head-up frames were drawn ~1.37x larger than the dips; these bring all
            // four onto one scale. If she reads too big/small OVERALL while eating, add
            // a `heightScale` rather than editing these four.
            frameScale: [0.88, 1.21, 0.88, 1.21],
            moves: false, weight: 0.0, minMs: 300000, maxMs: 300000,
            nativeW: 218, nativeH: 158                      // scaled bbox: 217x158/218x109/209x158/194x109
        }
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
    // Hold time for the CURRENT frame: frameHold[frameIndex] when the behaviour
    // defines it (the sniff's lingering head-up frame), else the flat frameInterval.
    readonly property int _frameHoldMs: {
        var cfg = behaviours[behaviour]
        return (cfg && cfg.frameHold && cfg.frameHold[frameIndex] !== undefined)
            ? cfg.frameHold[frameIndex]
            : _frameInterval
    }
    // Size multiplier for the CURRENT frame: frameScale[frameIndex] when the behaviour
    // defines it (the eating set's mixed-scale art), else 1 — art renders as exported.
    readonly property real _frameScale: {
        var cfg = behaviours[behaviour]
        return (cfg && cfg.frameScale && cfg.frameScale[frameIndex] !== undefined)
            ? cfg.frameScale[frameIndex]
            : 1.0
    }

    // --- Render -----------------------------------------------------------
    Image {
        id: sprite
        // Each frame renders at its TRUE art scale — sourceSize × _artScale — so the
        // dog is the same size in every frame and only the pose's real extent varies.
        // Anchored to the item's left/bottom (her rear + the floor), so frames of
        // different sizes within one behaviour (the sniff poses) keep the body
        // planted while the nose stretches. The facing mirror flips around the
        // ITEM's centre, which maps her rear to the item's right edge when she faces
        // left — still planted, every frame.
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        width: sourceSize.width * luna._artScale * luna._frameScale
        height: sourceSize.height * luna._artScale * luna._frameScale
        source: luna.currentFrames[luna.frameIndex] || luna._stationaryFrame
        fillMode: Image.PreserveAspectFit   // box is exactly proportional → pure scaling
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

    // Advances the walk (or any multi-frame) cycle. Auto-pauses via `running`. The
    // interval re-binds per frame so a behaviour can hold individual frames longer
    // (frameHold); the step order defers to the behaviour's frameStep when present.
    Timer {
        id: frameTimer
        repeat: true
        running: luna.running && luna._animatingFrames
        interval: Math.max(1, luna._frameHoldMs)
        onTriggered: luna._advanceFrame()
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

    // One frame-cycler tick: the behaviour's custom frameStep (possibly stochastic —
    // the sniff bob) when defined, else plain round-robin.
    function _advanceFrame() {
        var cfg = behaviours[behaviour]
        frameIndex = (cfg && cfg.frameStep)
            ? cfg.frameStep(frameIndex)
            : (frameIndex + 1) % currentFrames.length
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

import QtQuick
import frontend_v2

// View host: builds each view in the background shortly after startup (or at
// once if it is selected first), then keeps it ALIVE in memory so its state
// survives a switch away — e.g. the History view keeps its
// selected property + time window, ready exactly as you left it. The 4 GB Pi has
// memory to spare for a handful of resident views.
//
// One view at a time is LIVE: the current one, or in the menu the one settled at
// the front (`liveIndex`). The rest are FROZEN, not torn down: their per-frame
// work — the map's follow animation + center binding, the media colour fades,
// the seek ticker, the HVAC breath glow — is gated on the `isCurrent` property
// bound below, so a view nobody is looking at does no animated/rendered work
// and stops stealing GPU/CPU from the one that is. Cheap data bindings stay
// live (scalar updates that don't paint while hidden), so a view coming live
// is already showing current values.
//
// The views stand round a cylinder (frontend_v2/CLAUDE.md, *View switching*). A
// switch backs the current view away until its neighbours show, turns the
// cylinder and brings the new view forward. An edge swipe turns it under the
// finger; a swipe up from the bottom (driven from Main.qml) opens it as a menu
// to spin and pick from.
Item {
    id: host

    property var model: []
    property int currentIndex: 0
    // A view picked by a swipe or from the menu. Main.qml owns the selection: it
    // sets currentIndex to `index`, and the turn already under way plays on.
    signal chosen(int index)

    // Carousel geometry, in px and degrees.
    readonly property real tiltDeg: 32          // between neighbours on the cylinder
    readonly property real backedScale: 0.66    // the front view's size when backed away
    readonly property real panelGap: 40         // between neighbours, before perspective
    readonly property real eyeDistance: 1600    // smaller = stronger perspective
    readonly property real sideShade: 0.45      // darkening of a view one step round
    readonly property real menuZoom: 1.45       // how far back the menu stands, in backings-away
    readonly property real labelGap: 48         // a view's name below it in the menu, panel px
    // A backed-away view's frame, panel px: corners rounded this much and a light
    // edge, both growing in as it backs away so a full-screen view stays square.
    readonly property real cornerRadius: 18
    readonly property real edgeWidth: 3
    readonly property color edgeColor: "#59ffffff"
    // Gestures. Only a drag that starts in a side edge strip turns the views, so
    // the map, the graphs and the sliders keep their own horizontal drags.
    readonly property real swipeEdge: 28
    readonly property real swipeBackDistance: 160   // finger travel that backs the view away fully
    readonly property real menuPullDistance: 300    // swipe-up travel that draws the menu out fully
    readonly property real menuCloseDistance: 120   // a drag down this far closes the menu
    readonly property real dragThreshold: 12        // menu: travel before a press becomes a drag
    readonly property real flickVelocity: 900       // px/s: a release this fast completes a gesture

    readonly property int count: model.length
    readonly property real tiltRad: tiltDeg * Math.PI / 180
    // The cylinder whose faces are the views, `panelGap` apart.
    readonly property real radius: (width + panelGap) / (2 * Math.tan(tiltRad / 2))
    // How far the cylinder moves back for the front view to shrink to backedScale.
    readonly property real backDepth: eyeDistance * (1 / backedScale - 1)

    // The view on screen while idle; trails currentIndex until a turn completes.
    property int shownIndex: 0
    // "idle"; "swipe" (an edge swipe under the finger); "pull" (the swipe up
    // drawing the menu out); "menu" (open, still or spinning); "turn" (on the
    // way to targetIndex); "settle" (back to shownIndex after a gesture let go).
    property string phase: "idle"
    readonly property bool moving: phase !== "idle"
    // The cylinder's rotation, in views: `center` faces the front. Fractional
    // mid-turn and unbounded — positions wrap.
    property real center: 0
    // 0 = the front view fills the screen, 1 = backed away, menuZoom = the menu.
    property real zoom: 0
    // The view a turn ends on (or a swipe would), built before the motion.
    property int targetIndex: -1
    property int swipeDirection: 1

    // Views not built yet are built one by one once the app has settled, each
    // then drawn for a moment beneath the current view so it renders once: the
    // menu and the turns show real content from the start, the map has fetched
    // its tiles and the GPU compiled the view's pipelines, instead of a view's
    // first glimpse paying for them. Built asynchronously, so the current view
    // keeps its frames; one needed meanwhile finishes at once (see the Loader).
    readonly property int prebuildDelay: 3000   // ms after startup
    readonly property int prebuildHold: 1000    // ms a fresh view is drawn hidden
    // The view being built in the background, -1 when none.
    property int warmIndex: -1

    function prebuildNext() {
        for (let i = 0; i < count; ++i) {
            const panel = panelRepeater.itemAt(i)
            if (panel !== null && !panel.built) {
                warmIndex = i
                return
            }
        }
        warmIndex = -1
    }

    Timer {
        interval: host.prebuildDelay
        running: true
        onTriggered: host.prebuildNext()
    }
    Timer {
        id: prebuildHoldTimer
        interval: host.prebuildHold
        onTriggered: host.prebuildNext()
    }
    property bool labelsShown: false
    readonly property real labelOpacity: labelsShown
                                         ? Math.max(0, Math.min(1, (zoom - 0.5) / (menuZoom - 0.5)))
                                         : 0

    function wrap(i) {
        return ((i % count) + count) % count
    }

    // `d` views of rotation, taken the short way round.
    function wrapped(d) {
        return d - count * Math.round(d / count)
    }

    // How many views round from the front view `i` stands.
    function positionOf(i) {
        return wrapped(i - center)
    }

    readonly property int frontIndex: count > 0 ? wrap(Math.round(center)) : 0

    // The view whose `isCurrent` is on: the current view, and in the menu the
    // one at the front once it has stayed there for menuLiveDelay — so a spin
    // does not wake every view it passes, and the one it stops on comes live
    // (a map following the car, fresh data for History, Charging and Trips).
    property int liveIndex: 0
    readonly property int menuLiveDelay: 400

    onFrontIndexChanged: if (phase === "menu") liveDelay.restart()

    Timer {
        id: liveDelay
        interval: host.menuLiveDelay
        onTriggered: if (host.phase === "menu") host.liveIndex = host.frontIndex
    }

    // Left open and still — not spinning, no finger on it — for
    // Theme.menuAutoPickMs, the menu opens the view at the front. Any touch
    // starts the wait over.
    Timer {
        interval: Theme.menuAutoPickMs
        running: host.phase === "menu" && !glideAnimation.running && !menuInput.pressed
        onTriggered: host.choose(host.frontIndex)
    }

    // A view `position` steps round the cylinder as a perspective matrix over
    // its own rectangle — the eye on the screen's centre line, the cylinder
    // `backDepth * zoom` further back — plus where it lands on screen. Row 3 is
    // the perspective divide; z is left at 0, so nothing is clipped against the
    // scene graph's depth range.
    function poseAt(position) {
        const w = width, h = height, k = 1 / eyeDistance
        const a = position * tiltRad
        const s = Math.sin(a), c = Math.cos(a)
        const x = radius * s
        const depth = radius * (c - 1) - backDepth * zoom
        const w0 = 1 - (s * w / 2 + depth) * k    // the divide at the left edge
        const w1 = 1 - (-s * w / 2 + depth) * k   // ... and at the right edge
        const left = w / 2 + (x - c * w / 2) / w0
        const right = w / 2 + (x + c * w / 2) / w1
        // The near edge is the taller one; the menu's name goes below it.
        const near = Math.min(w0, w1)
        return {
            matrix: Qt.matrix4x4(c + w / 2 * s * k, 0, 0, x - c * w / 2 + w / 2 * w0,
                                 h / 2 * s * k,     1, 0, -h / 2 + h / 2 * w0,
                                 0,                 0, 1, 0,
                                 s * k,             0, 0, w0),
            onScreen: w0 > 0 && w1 > 0 && right > 0 && left < w,
            left: left,
            right: right,
            top: h / 2 - h / 2 / near,
            bottom: h / 2 + (h / 2 + labelGap + 80) / near
        }
    }

    // On-screen distance from the front to a neighbour at `z`: the drag that
    // turns the cylinder one step, so a view follows the finger.
    function stepPx(z) {
        const depth = radius * (Math.cos(tiltRad) - 1) - backDepth * z
        return radius * Math.sin(tiltRad) / (1 - depth / eyeDistance)
    }

    // The frontmost view under a point, or -1.
    function viewAt(x, y) {
        let best = -1
        let bestPosition = Infinity
        for (let i = 0; i < count; ++i) {
            const p = Math.abs(positionOf(i))
            if (!(p <= 2.2) || p >= bestPosition)
                continue
            const pose = poseAt(positionOf(i))
            if (x >= pose.left && x <= pose.right && y >= pose.top && y <= pose.bottom) {
                best = i
                bestPosition = p
            }
        }
        return best
    }

    onCurrentIndexChanged: {
        liveIndex = currentIndex
        // A change made mid-turn is picked up when the turn completes. Otherwise
        // the turn starts once this pass is over, after the Loader bindings below
        // have built the target, so building it cannot eat into the animation.
        if (phase !== "turn")
            Qt.callLater(host.turnToCurrent)
    }

    // The screensaver hides the host: a menu left open would greet the wake.
    onVisibleChanged: if (!visible && phase !== "turn") toIdle()

    function turnToCurrent() {
        if (phase === "turn" || currentIndex === shownIndex)
            return
        if (!visible || count < 2) {
            shownIndex = currentIndex
            toIdle()
            return
        }
        goTo(currentIndex, 1, false)
    }

    // Turns to `target` from wherever the cylinder stands, the short way round
    // and past every view between, backing away to at least `peak` first.
    function goTo(target, peak, fromGesture) {
        // Builds it now, before the motion starts (see the Loader).
        targetIndex = target
        let rel = wrapped(target - center)
        // Halfway round is as short either way: turn forward to a later view,
        // back to an earlier one.
        if (Math.abs(rel) === count / 2)
            rel = target > frontIndex ? count / 2 : -count / 2
        phase = "turn"
        liveIndex = target
        glide(center + rel, Math.max(zoom, peak), 0, fromGesture)
    }

    // A view picked in the menu, or the front one when it is dismissed.
    function choose(index) {
        goTo(index, zoom, true)
        if (index !== currentIndex)
            chosen(index)
    }

    function toIdle() {
        glideAnimation.stop()
        phase = "idle"
        zoom = 0
        center = shownIndex
        targetIndex = -1
        labelsShown = false
        liveIndex = currentIndex
    }

    function beginSwipe(dir) {
        if (phase !== "idle")
            return
        swipeDirection = dir
        center = shownIndex
        zoom = 0
        // Built at once, so a completed swipe turns without a pause.
        targetIndex = wrap(shownIndex + dir)
        phase = "swipe"
    }

    // `distance`: px the finger has travelled in from the edge.
    function swipeTo(distance) {
        if (phase !== "swipe")
            return
        zoom = Math.max(0, Math.min(1, distance / swipeBackDistance))
        center = shownIndex + swipeDirection * Math.max(0, Math.min(1, distance / stepPx(1)))
    }

    // `velocity`: px/s in the swipe's direction at release.
    function endSwipe(velocity) {
        if (phase !== "swipe")
            return
        const turned = Math.abs(center - shownIndex)
        if (turned >= 0.5 || velocity >= flickVelocity && turned >= 0.1) {
            choose(targetIndex)
        } else {
            phase = "settle"
            glide(shownIndex, zoom, 0, true)
        }
    }

    // `distance`: px the swipe up has travelled.
    function pullMenu(distance) {
        if (phase === "idle" && distance > 0 && count > 1) {
            center = shownIndex
            labelsShown = true
            phase = "pull"
        }
        if (phase === "pull")
            zoom = menuZoom * Math.max(0, Math.min(1, distance / menuPullDistance))
    }

    // `velocity`: px/s upwards at release.
    function endMenuPull(velocity) {
        if (phase !== "pull")
            return
        if (zoom >= 0.6 * menuZoom || velocity >= flickVelocity && zoom >= 0.15 * menuZoom) {
            phase = "menu"
            glide(center, menuZoom, menuZoom, true)
        } else {
            phase = "settle"
            glide(center, zoom, 0, true)
        }
    }

    // Stops the menu square on the view nearest the front, or — let go as a
    // flick (`velocity`, px/s) — lets it run on with the finger's speed first.
    function spinMenu(velocity) {
        const front = Math.round(center)
        let to = front
        if (Math.abs(velocity) >= flickVelocity)
            to = Math.max(front - 3, Math.min(front + 3, Math.round(center - velocity * 0.25 / stepPx(zoom))))
        glide(to, menuZoom, menuZoom, true)
    }

    // From wherever zoom and center stand: back away to `peak`, turn to
    // `toCenter`, come forward to `endZoom`, each phase overlapping the next by
    // viewPhaseOverlap. A glide carrying on from a finger starts at speed
    // (OutCubic) instead of easing in.
    function glide(toCenter, peak, endZoom, fromGesture) {
        const backMs = Math.round(Theme.viewBackDuration * Math.max(0, peak - zoom))
        const span = Math.abs(toCenter - center)
        // A turn of several steps (a menu pick or flick, a home return) runs
        // faster per step.
        const spinMs = Math.round(Theme.viewTurnDuration * (span <= 1 ? span : 1 + 0.4 * (span - 1)))
        const forwardMs = Math.round(Theme.viewForwardDuration * Math.min(1.3, Math.max(0, peak - endZoom)))
        const spinDelay = Math.max(0, backMs - Theme.viewPhaseOverlap)
        zoomBack.to = peak
        zoomBack.duration = backMs
        zoomBack.easing.type = fromGesture ? Easing.OutCubic : Easing.InOutSine
        zoomHold.duration = Math.max(0, spinDelay + spinMs - Theme.viewPhaseOverlap - backMs)
        zoomForward.to = endZoom
        zoomForward.duration = forwardMs
        spinPause.duration = spinDelay
        spinStep.to = toCenter
        spinStep.duration = spinMs
        spinStep.easing.type = fromGesture ? Easing.OutCubic : Easing.InOutCubic
        glideAnimation.restart()
    }

    function glideDone() {
        if (phase === "menu")
            return
        if (phase === "turn")
            shownIndex = targetIndex
        toIdle()
        if (currentIndex !== shownIndex)
            Qt.callLater(host.turnToCurrent)
    }

    ParallelAnimation {
        id: glideAnimation

        SequentialAnimation {
            NumberAnimation {
                id: zoomBack
                target: host
                property: "zoom"
            }
            PauseAnimation { id: zoomHold }
            NumberAnimation {
                id: zoomForward
                target: host
                property: "zoom"
                easing.type: Easing.InOutCubic
            }
        }
        SequentialAnimation {
            PauseAnimation { id: spinPause }
            NumberAnimation {
                id: spinStep
                target: host
                property: "center"
            }
        }

        onFinished: host.glideDone()
    }

    // A shape that contains no point: the views' input gate (in the Repeater).
    QtObject {
        id: noPoint

        function contains(point: point): bool {
            return false
        }
    }

    // The space round the views once they back away. The corner covers below
    // are this colour.
    Rectangle {
        anchors.fill: parent
        z: -10
        color: "#000000"
        visible: host.moving
    }

    Repeater {
        id: panelRepeater
        model: host.model

        Item {
            id: panel
            required property int index
            required property var modelData

            readonly property bool current: index === host.currentIndex
            readonly property bool live: index === host.liveIndex
            readonly property real position: host.moving ? host.positionOf(index) : NaN
            // Past two steps round a view is out of sight at any zoom.
            readonly property var pose: Math.abs(position) <= 2.2 ? host.poseAt(position) : null
            // Paint and accept input only while shown; hidden views stay loaded
            // but frozen (see header).
            readonly property bool built: viewLoader.status === Loader.Ready
            // Built in the background and drawn beneath the current view (see
            // prebuildNext), which is opaque.
            readonly property bool warming: index === host.warmIndex && built
            readonly property bool shown: host.moving ? pose !== null && pose.onScreen
                                                      : index === host.shownIndex || warming
            // The frame grows in over the first backing away.
            readonly property real framing: host.moving ? Math.min(1, host.zoom) : 0
            readonly property real corner: host.cornerRadius * framing

            width: host.width
            height: host.height
            z: pose ? -Math.abs(position) : (index === host.shownIndex ? 0 : -1)
            visible: shown
            enabled: shown

            transform: Matrix4x4 {
                matrix: panel.pose ? panel.pose.matrix : Qt.matrix4x4()
            }

            Item {
                anchors.fill: parent
                // Moving, a view is drawn into a texture and the texture is
                // turned: the scene graph cannot batch items under a perspective
                // matrix, so several live views drawn through one would cost a
                // draw call per item per frame. A still view renders once. The
                // transparent 2 px margin lets the filtering smooth the slanted
                // edges.
                layer.enabled: host.moving && panel.shown
                layer.smooth: true
                layer.mipmap: true
                layer.sourceRect: Qt.rect(-2, -2, width + 4, height + 4)

                // Moving or warming, a view only shows: no press reaches it, not even the
                // ones its pointer handlers would still see under the menu's
                // MouseArea (a graph's touch inspect would come on). Press
                // delivery skips a clipping item, children and all, when its
                // shape does not contain the point; hover delivery tests only
                // the bounds, so hover is stopped above the views instead
                // (`hoverBlock`). `enabled: false` would block both, but restyle
                // the controls that follow it — sliders, text fields, History's
                // LIVE button.
                Item {
                    anchors.fill: parent
                    clip: host.moving || panel.warming
                    containmentMask: host.moving || panel.warming ? noPoint : null

                    Loader {
                        id: viewLoader
                        anchors.fill: parent
                        sourceComponent: panel.modelData.component

                        // Load when selected, as a turn's target or in the background,
                        // then stay loaded (state kept in memory). `keep` follows
                        // `wanted`, not `active`: set from onActiveChanged it would be
                        // written while `active` itself is, a binding loop.
                        readonly property bool needed: panel.current || panel.live
                                                       || host.moving && panel.index === host.targetIndex
                        readonly property bool wanted: needed || panel.index === host.warmIndex
                        property bool keep: false
                        onWantedChanged: if (wanted) keep = true
                        Component.onCompleted: keep = wanted
                        active: wanted || keep
                        // A background build spreads over frames; turning it off
                        // finishes one in progress at once, for a view needed now.
                        asynchronous: !needed
                        onLoaded: if (panel.index === host.warmIndex)
                                      prebuildHoldTimer.restart()

                        Binding {
                            target: viewLoader.item
                            property: "isCurrent"
                            value: panel.live
                            when: viewLoader.status === Loader.Ready
                        }
                    }

                    // A view not built yet (the background builds take a few seconds
                    // after startup): its icon. The menu names it below.
                    Rectangle {
                        anchors.fill: parent
                        visible: viewLoader.status !== Loader.Ready
                        color: Theme.dashboardBackground

                        TintedIcon {
                            anchors.centerIn: parent
                            source: panel.modelData.icon
                            iconSize: 160
                            tint: Theme.viewLabel
                        }
                    }
                }
            }

            // Turned away from the front, a view darkens.
            Rectangle {
                anchors.fill: parent
                color: "#000000"
                opacity: panel.pose ? Math.min(1, Math.abs(panel.position)) * host.sideShade : 0
                visible: opacity > 0
                antialiasing: true
            }

            // The rounded corners: a ring in the space's colour whose inner
            // edge is the rounded frame covers the view's square corners (and
            // the shade's). Drawn over the view rather than masking it, so the
            // layer stays a plain texture. The ring reaches `cover` px past the
            // view, well inside the gap to its neighbour; it must be at least
            // (√2 − 1) × the radius to fill a corner.
            Rectangle {
                readonly property real cover: 16
                x: -cover
                y: -cover
                width: parent.width + 2 * cover
                height: parent.height + 2 * cover
                radius: panel.corner + cover
                color: "transparent"
                border.width: cover
                border.color: "#000000"
                visible: panel.corner > 0
                antialiasing: true
            }
            Rectangle {
                anchors.fill: parent
                radius: panel.corner
                color: "transparent"
                border.width: host.edgeWidth
                border.color: host.edgeColor
                opacity: panel.framing
                visible: panel.framing > 0
                antialiasing: true
            }

            Text {
                y: parent.height + host.labelGap
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: panel.modelData.name
                color: Theme.viewLabel
                font.family: Theme.fontFamily
                font.pixelSize: 72
                opacity: host.labelOpacity
                visible: opacity > 0
            }
        }
    }

    // Moving, no hover reaches the views (see the input gate in the panels): a
    // graph under the pointer would draw its inspect line.
    Item {
        anchors.fill: parent
        z: 1

        HoverHandler {
            id: hoverBlock
            enabled: host.moving
            blocking: true
        }
    }

    // The menu's input; mid-turn it only keeps the views' input off.
    MouseArea {
        id: menuInput

        property real startX: 0
        property real startY: 0
        property real startCenter: 0
        property string axis: ""          // "" until the press becomes a drag, then "x" or "y"
        property bool stoppedSpin: false  // the press caught a spin still running

        readonly property ReleaseVelocity speed: ReleaseVelocity {}

        anchors.fill: parent
        z: 1
        enabled: host.phase === "menu" || host.phase === "turn" || host.phase === "settle"
        acceptedButtons: Qt.AllButtons
        preventStealing: true

        onPressed: (mouse) => {
            axis = ""
            if (host.phase !== "menu")
                return
            stoppedSpin = glideAnimation.running
            glideAnimation.stop()
            startX = mouse.x
            startY = mouse.y
            startCenter = host.center
            speed.start(mouse.x)
        }
        onPositionChanged: (mouse) => {
            if (host.phase !== "menu")
                return
            const dx = mouse.x - startX
            const dy = mouse.y - startY
            if (axis === "" && Math.max(Math.abs(dx), Math.abs(dy)) > host.dragThreshold)
                axis = Math.abs(dx) >= Math.abs(dy) ? "x" : "y"
            if (axis !== "x")
                return
            speed.move(mouse.x)
            host.center = startCenter - dx / host.stepPx(host.zoom)
        }
        onReleased: (mouse) => {
            if (host.phase !== "menu")
                return
            if (axis === "x") {
                host.spinMenu(speed.release(mouse.x))
            } else if (axis === "y") {
                if (mouse.y - startY >= host.menuCloseDistance)
                    host.choose(host.frontIndex)
                else
                    host.spinMenu(0)
            } else if (stoppedSpin) {
                // A tap that stops a spin only stops it.
                host.spinMenu(0)
            } else {
                const index = host.viewAt(mouse.x, mouse.y)
                host.choose(index >= 0 ? index : host.frontIndex)
            }
        }
        onWheel: (wheel) => wheel.accepted = true
    }

    // The swipe strips: the right edge brings in the next view, the left the
    // previous. They lie UNDER the views: a DragHandler on top would accept the
    // press and starve the button or row beneath it (QTBUG-145896, as with the
    // keyboard's outside-press catcher in Main.qml), whereas one underneath still
    // sees a press the view accepted — delivery carries on to pointer handlers —
    // and takes the drag over once it turns horizontal past the threshold. A tap
    // or a vertical scroll never does, so those stay with the view. Once it has
    // the drag nothing takes it back, the map's own DragHandler included.
    Repeater {
        model: [-1, 1]

        Item {
            id: edge
            required property int modelData
            readonly property int direction: modelData
            // px the finger has come in from the edge.
            property real travelled: 0
            readonly property ReleaseVelocity speed: ReleaseVelocity {}

            x: direction < 0 ? 0 : host.width - width
            width: host.swipeEdge
            height: host.height
            z: -20
            enabled: host.count > 1 && (host.phase === "idle"
                                        || host.phase === "swipe" && host.swipeDirection === direction)

            DragHandler {
                target: null
                yAxis.enabled: false
                grabPermissions: PointerHandler.CanTakeOverFromAnything

                onActiveChanged: {
                    if (active) {
                        edge.travelled = -activeTranslation.x * edge.direction
                        edge.speed.start(edge.travelled)
                        host.beginSwipe(edge.direction)
                    } else {
                        host.endSwipe(edge.speed.release(edge.travelled))
                    }
                }
                onActiveTranslationChanged: {
                    if (!active)
                        return
                    edge.travelled = -activeTranslation.x * edge.direction
                    edge.speed.move(edge.travelled)
                    host.swipeTo(edge.travelled)
                }
            }
        }
    }
}

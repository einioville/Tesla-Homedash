import QtQuick
import QtQuick.Shapes
import QtQuick.Effects
import QtGraphs
import frontend_v2

// Interactive line graph for one property's history.
//
//  - Data, axis bounds and point count are DATA-SOURCE-AGNOSTIC: they come from the
//    pointsData / dataMinX… / dataCount / dataLoading properties, which default to the
//    History singleton but can be bound to any source (the Trips view feeds them from
//    the Trips singleton's per-trip series). The owning view drives reloadFull() on a
//    fresh load and advanceLive() on a live tick, so the graph itself subscribes to no
//    singleton and two independent instances never share state.
//  - The visible x-window [viewMinX, viewMaxX] can be panned/zoomed; the y-axis
//    auto-fits the visible data (with a little padding) so nothing clips. The x-axis
//    is time: tick marks + labels snap to nice clock boundaries and adapt to the window
//    (times for hour-scale spans, dates for day-scale). Gridlines are off, only the line
//    and the axis lines show.
//
// Interaction:
//   Touch  — one finger moves the inspection line; two fingers pinch to zoom the
//            x-window and slide to pan it.
//   Mouse  — hover moves the inspection line; the wheel zooms the x-window around
//            the cursor; right-drag pans it.
//   A "Palauta" button restores the full extent of the loaded range.
Item {
    id: root

    property string unit: ""

    // How consecutive readings are connected. "step" (default): hold the previous value
    // horizontally, then jump — right for sampled / held signals (VehicleSpeed, setpoints)
    // where telemetry only sends on change and the in-between is unknown. "linear": a
    // straight point-to-point line — right for accumulators / continuous quantities
    // (Odometer, energy counters, OutsideTemp) whose value genuinely tracks ~linearly
    // between readings. Sourced per-property from config.json; buildStepped() and valueAt()
    // branch on it, and the glow / y-fit / live marker follow from those two.
    property string lineMode: "step"

    // --- Gradient glow under the line (the modern look; tweak here) -----------
    // A translucent area fill under the line that fades to transparent toward the plot
    // floor — the "glow" that makes the graph read as modern instead of a bare stroke.
    // Colour tracks the line (Theme.accent) by default; a host can override per graph.
    // glowOpacity is the alpha directly under the line (the fade bottoms out at 0). These
    // two are the knobs to iterate on the look.
    property color glowColor: Theme.accent
    property real glowOpacity: 0.35

    // --- Outer glow on the line itself (the bloom; tweak here) ----------------
    // A soft blurred halo behind the crisp line. Kept OFF by default — it read as too blurry —
    // but the machinery stays so it can be re-enabled and tuned. It is a blurred copy of the
    // stepped path (via MultiEffect — the same glow tech as GlowIcon / GlassPanel), drawn
    // behind the real line. lineGlowRadius is the blur reach in px, lineGlowStrength the overall
    // opacity, lineGlowWidth the stroke fed into the blur (a wider source → a denser bloom).
    // Flip lineGlowEnabled true to bring it back (a tighter look wants a smaller radius/width).
    property bool lineGlowEnabled: false
    property real lineGlowRadius: 14
    property real lineGlowStrength: 0.85
    property real lineGlowWidth: 6

    // Horizontal gridline colour. ~25% white so the lines read over the plain dark card, not
    // just where the brighter gradient sits behind them (10% was invisible on the dark areas).
    property color gridLineColor: "#40ffffff"

    // Draw-in animation: the plot content (line + fill glow) fades from 0 → 1 on every fresh
    // load, so switching property / range feels alive. Driven by drawInAnim, which reloadFull
    // restarts; a live tick (advanceLive) deliberately does NOT restart it, so the per-second
    // roll stays smooth instead of blinking. 1 = fully shown (the resting state).
    property real drawIn: 1

    // Live "now" marker: when true, a pulsing dot is drawn at the latest value (the rolling
    // right edge). Hosts set it for graphs whose newest point really is "now" — the History
    // view in live mode and the rolling Charging past-hour graphs — and leave it false for
    // static graphs (a past trip), where a pulsing "now" would be misleading.
    property bool live: false

    // Cached stepped path in DATA coordinates, rebuilt only when the data / extent changes
    // (in reloadFull / advanceLive) — the same array handed to the LineSeries. glowPolyline
    // maps it to plot-local pixels, so panning/zooming only remaps, never re-steps.
    property var steppedData: []

    // The glow outline in plot-local pixels: the cached stepped points mapped through the
    // current axis window + plot geometry, bracketed by two floor points so the filled Shape
    // closes down to the baseline. Rebinds whenever the window (xAxis / yAxis), the plot area
    // or the data changes, so the glow stays locked under the line through every pan / zoom.
    readonly property var glowPolyline: {
        const a = graph.plotArea
        const src = root.steppedData
        const n = src.length
        const xspan = xAxis.max - xAxis.min
        const yspan = yAxis.max - yAxis.min
        if (n === 0 || a.width <= 0 || a.height <= 0 || xspan <= 0 || yspan <= 0)
            return []
        const w = a.width, h = a.height
        const x0 = xAxis.min, yTop = yAxis.max
        // Clamp mapped pixel coordinates to a bounded off-screen range. Points far outside
        // the visible window (the full-extent endpoints, and any point many view-widths away)
        // map to enormous pixels when zoomed in tight — and the fill Shape's CurveRenderer
        // triangulates the WHOLE path (its clip is only a rasteriser scissor, not a geometry
        // clip), which ASSERTS and aborts the app once a vertex exceeds 2^21 px
        // (qtriangulator.cpp). LIM sits far off-screen — glowClip scissors it away, and the
        // in/near-window points that shape the visible fill are never clamped — so the visible
        // glow is unchanged; it only stops the off-screen tail from blowing past the limit.
        const LIM = 1 << 15
        function clamp(v) { return v < -LIM ? -LIM : (v > LIM ? LIM : v) }
        function px(dx) { return clamp((dx - x0) / xspan * w) }
        function py(dy) { return clamp((yTop - dy) / yspan * h) }
        const out = []
        out.push(Qt.point(px(src[0].x), h))
        for (let i = 0; i < n; ++i)
            out.push(Qt.point(px(src[i].x), py(src[i].y)))
        out.push(Qt.point(px(src[n - 1].x), h))
        return out
    }

    // The line-only outline in plot-local pixels: glowPolyline without its two floor-bracket
    // points, i.e. just the stepped path the line traces. The (disabled) outer-glow Shape strokes this.
    readonly property var linePolyline:
        glowPolyline.length > 2 ? glowPolyline.slice(1, glowPolyline.length - 1) : []

    // The built-in card background. Now the same minimalistic translucent-grey card the
    // Trips / Charging graph cards draw, so all three graph surfaces share one look. The
    // Trips / Charging views set this false and supply their own (identical) card; the
    // History view keeps this built-in one.
    property bool showBackground: true

    // Card padding: the gap between the card edge and the plot area, per side — the space
    // where the card's own frame (its translucent fill + rounded border) shows around the
    // graph. These map straight to GraphsView's own margins, which default to a chunky 20px
    // all round — pure padding ON TOP OF the axis-label area (plotArea already excludes the
    // axis areas). We drive them ourselves and pair them with a transparent graph background
    // (below), so this is the ONLY inset: the graph itself adds no padding of its own and
    // blends into the card instead of floating an opaque rectangle inside it. A host that
    // overlays a title on the graph (the Trip / Charging cards) bumps plotMarginTop to
    // reserve room for it; the History view has no inner title and keeps the default.
    property real plotMarginTop: 16
    property real plotMarginBottom: 16
    property real plotMarginLeft: 16
    property real plotMarginRight: 16

    // Data source (defaults to the History singleton; the Trips view overrides these).
    // pointsData is [{ x: epochMs, y: value }] ascending; the bounds fit the axes.
    property var pointsData: History.points
    property real dataMinX: History.minX
    property real dataMaxX: History.maxX
    property real dataMinY: History.minY
    property real dataMaxY: History.maxY
    property int dataCount: History.pointCount
    property bool dataLoading: History.loading

    // Full extent of the loaded range, and the currently visible sub-window.
    property real fullMinX: 0
    property real fullMaxX: 1
    property real viewMinX: 0
    property real viewMaxX: 1

    // True while the user is panning/zooming. In live mode this suspends auto-
    // follow so a per-second tick doesn't yank the view from under them; "Palauta"
    // (viewFull) and a fresh load (resetView) clear it.
    property bool userControlled: false

    // y-fit over the visible window (recomputed when the window or data changes).
    readonly property var yFit: fitY(viewMinX, viewMaxX)
    readonly property real yPad: {
        const span = yFit.max - yFit.min
        return span > 0 ? span * 0.08 : 1.0
    }
    readonly property bool viewIsFull:
        Math.abs(viewMinX - fullMinX) < 1 && Math.abs(viewMaxX - fullMaxX) < 1

    // Adaptive x-axis (time) ticks over the visible window: ~5 marks snapped to nice clock
    // boundaries. The step drives BOTH the axis tick spacing (xAxis.tickInterval) and the
    // label format — a day-scale step shows a date, a smaller step a time — so labels can
    // never duplicate. Anchored to local midnight so ticks land on round clock times.
    readonly property real xTickStep: niceTimeStep((viewMaxX - viewMinX) / 5)
    readonly property real xTickAnchor: localMidnight(viewMinX)

    // Inspection state, exposed so a host can mirror the cursor elsewhere (the Trips
    // view drops a marker on the map at the inspected time). inspectTime is the epoch-ms
    // time under the cursor; only meaningful while `inspecting`.
    readonly property bool inspecting: overlay.inspecting
    readonly property real inspectTime: overlay.dataX

    Rectangle {
        anchors.fill: parent
        visible: root.showBackground
        radius: Theme.tripCardRadius
        color: Theme.tripCardBg
        border.width: 1
        border.color: Theme.tripCardBorder
    }

    // Gradient glow under the line, drawn as ONE clean filled Shape rather than a QtGraphs
    // AreaSeries — the area renderer triangulates our stepped path (points share x on every
    // vertical jump) into visible diagonal streaks. glowClip is pinned to the plot area and
    // clips, so panned/zoomed content outside the window can't spill. The ShapePath traces
    // the stepped path in plot-local pixels and closes down to the floor, filled with a
    // vertical LinearGradient that fades to transparent. Declared BEFORE the GraphsView so
    // the line — which the GraphsView draws over its transparent plot area — sits on top of
    // the glow. The inspect overlay is declared after the GraphsView, so it stays on top.
    Item {
        id: glowClip
        visible: root.dataCount > 0 && root.glowPolyline.length > 0
        opacity: root.drawIn
        x: graph.plotArea.x
        y: graph.plotArea.y
        width: graph.plotArea.width
        height: graph.plotArea.height
        clip: true

        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
                strokeWidth: 0
                strokeColor: "transparent"
                startX: root.glowPolyline.length > 0 ? root.glowPolyline[0].x : 0
                startY: root.glowPolyline.length > 0 ? root.glowPolyline[0].y : 0
                fillGradient: LinearGradient {
                    x1: 0
                    y1: 0
                    x2: 0
                    y2: glowClip.height
                    GradientStop { position: 0.0; color: Qt.rgba(root.glowColor.r, root.glowColor.g, root.glowColor.b, root.glowOpacity) }
                    GradientStop { position: 0.55; color: Qt.rgba(root.glowColor.r, root.glowColor.g, root.glowColor.b, root.glowOpacity * 0.22) }
                    GradientStop { position: 1.0; color: Qt.rgba(root.glowColor.r, root.glowColor.g, root.glowColor.b, 0.0) }
                }
                PathPolyline { path: root.glowPolyline }
            }
        }
    }

    // Outer glow on the line: a blurred copy of the stepped path, drawn behind the crisp line
    // so the line reads as lit. The source Shape (hidden) strokes the same pixel polyline as
    // the line; MultiEffect blurs it into a soft accent halo. blurEnabled (not shadowEnabled)
    // renders ONLY the blurred version — no crisp second line to fight the real one on top.
    // Same plot-area clip as the fill glow, and declared before the GraphsView so the crisp
    // line sits on top. Reuses glowColor, so the fill glow, line and bloom stay one colour.
    Item {
        id: lineGlowClip
        visible: root.lineGlowEnabled && root.dataCount > 0 && root.linePolyline.length > 1
        x: graph.plotArea.x
        y: graph.plotArea.y
        width: graph.plotArea.width
        height: graph.plotArea.height
        clip: true

        Shape {
            id: lineGlowSource
            anchors.fill: parent
            visible: false
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
                strokeColor: root.glowColor
                strokeWidth: root.lineGlowWidth
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                PathPolyline { path: root.linePolyline }
            }
        }

        MultiEffect {
            anchors.fill: lineGlowSource
            source: lineGlowSource
            autoPaddingEnabled: false
            blurEnabled: true
            blur: 1.0
            blurMax: root.lineGlowRadius
            opacity: root.lineGlowStrength
        }
    }

    GraphsView {
        id: graph
        anchors.fill: parent
        opacity: root.drawIn
        marginTop: root.plotMarginTop
        marginBottom: root.plotMarginBottom
        marginLeft: root.plotMarginLeft
        marginRight: root.plotMarginRight

        // Transparent background so the card behind the graph shows through — the
        // translucent-grey Rectangle (History's built-in one, or the Trip / Charging card). Without
        // this the default theme paints an opaque rectangle over the card, which reads
        // as "the card disappeared". Only the two background flags are overridden; axis
        // line / label colours keep the default theme, so the graph looks unchanged
        // apart from blending into its card. The LineSeries sets its own colour.
        theme: GraphsTheme {
            backgroundVisible: false
            plotAreaBackgroundVisible: false
            // Whisper-faint horizontal gridlines (only the Y axis enables its grid, below)
            // so a value can be read off the axis without dropping the inspect line. Kept
            // very low-alpha so it adds depth without clutter; no sub-grid.
            grid.mainColor: root.gridLineColor
            grid.mainWidth: 1
        }

        axisX: ValueAxis {
            id: xAxis
            min: root.viewMinX
            max: root.viewMaxX
            // Time axis. Tick MARKS sit on clock boundaries (tickInterval/tickAnchor); the
            // labels are drawn by labelDelegate, which the axis positions natively UNDER
            // each tick (no hand-placed overlay to misalign). labelFormat emits the raw
            // epoch-ms as a plain full-precision integer ("%.0f") that the delegate reparses
            // and formats as a time or date per the step — so labels never duplicate.
            labelsVisible: true
            labelFormat: "%.0f"
            tickInterval: root.xTickStep
            tickAnchor: root.xTickAnchor
            gridVisible: false     // no vertical gridlines (only the Y axis's faint horizontals)
            subGridVisible: false
            labelDelegate: Item {
                id: xLabelDelegate
                property string text   // assigned by the axis: the epoch-ms label value
                implicitWidth: xLabelText.implicitWidth
                implicitHeight: xLabelText.implicitHeight
                Text {
                    id: xLabelText
                    anchors.centerIn: parent
                    text: {
                        const ms = parseFloat(xLabelDelegate.text)
                        return isNaN(ms) ? "" : root.formatTimeTick(ms, root.xTickStep)
                    }
                    color: Theme.dataLabelTitle
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                }
            }
        }
        axisY: ValueAxis {
            id: yAxis
            min: root.yFit.min - root.yPad
            max: root.yFit.max + root.yPad
            // Faint horizontal gridlines aligned with the value labels (colour from the
            // theme's grid.mainColor above); the X axis keeps its grid off so only
            // horizontals show. No minor gridlines.
            gridVisible: true
            subGridVisible: false
        }

        LineSeries {
            id: series
            width: 2
            color: Theme.accent
            // The path geometry is built explicitly in buildStepped() per the property's
            // lineMode, so the default straight-segment style renders exactly what we
            // intend: "step" holds each reading then jumps (telemetry only sends on change,
            // so a sampled value holds until the next instead of sloping toward it), while
            // "linear" connects readings point-to-point for accumulators / continuous
            // signals. Building the path ourselves avoids relying on any renderer line style.
            // (A smooth spline was tried and reverted: it turned a genuinely flat/held
            // value into a wobble, misrepresenting the data.)
        }
    }

    // A fresh load: reset the view to the full extent and refill the series. The
    // owning view calls this when its data source signals new data (History.onHistoryReady
    // / Trips.onSeriesReady).
    function reloadFull() {
        root.resetView()
        root.steppedData = root.buildStepped(root.pointsData)
        series.replace(root.steppedData)
        drawInAnim.restart()
    }

    // The fade-in: sets drawIn to 0 and eases it back to 1 (bound to the plot content's
    // opacity). restart() re-fires it from the start on each fresh load.
    NumberAnimation {
        id: drawInAnim
        target: root
        property: "drawIn"
        from: 0.0
        to: 1.0
        duration: 420
        easing.type: Easing.OutCubic
    }
    // A live window advanced one tick: redraw and follow "now" unless the user is
    // inspecting (then keep their window; the bounds still update so panning stays
    // clamped to the rolled data). Never resetView here — that would clobber the
    // user's zoom every tick. Only the History view's live mode uses this.
    function advanceLive() {
        root.fullMinX = root.dataMinX
        root.fullMaxX = root.dataMaxX
        if (!root.userControlled) {
            root.viewMinX = root.dataMinX
            root.viewMaxX = root.dataMaxX
        }
        root.steppedData = root.buildStepped(root.pointsData)
        series.replace(root.steppedData)
    }
    Component.onCompleted: if (root.dataCount > 0) { resetView(); root.steppedData = root.buildStepped(root.pointsData); series.replace(root.steppedData); drawInAnim.restart() }

    // Interactive overlay: pointer handlers for inspect + pan/zoom. Sized to the
    // GraphsView so handler positions share the plotArea coordinate space.
    Item {
        id: overlay
        anchors.fill: graph

        readonly property bool inspecting:
            root.dataCount > 0 && !pinch.active && !mousePan.active
            && (hoverH.hovered || touchH.active)
        readonly property real cursorX:
            touchH.active ? touchH.point.position.x : hoverH.point.position.x
        readonly property real clampedX: root.clampToPlot(cursorX)
        readonly property real dataX: root.pixelToTime(clampedX)
        readonly property real dataY: root.valueAt(dataX)
        // Pixel y of the inspected value (overlay coords = graph coords) — so the highlight dot
        // lands exactly on the line.
        readonly property real dataYPixel: root.valueToPixel(dataY)

        // Mouse hover → inspect.
        HoverHandler { id: hoverH }

        // One-finger touch → inspect.
        PointHandler {
            id: touchH
            acceptedDevices: PointerDevice.TouchScreen
        }

        // Two-finger touch → pinch-zoom + pan the x-window. target:null so we
        // drive the view ourselves from the gesture, keeping the data point under
        // the centroid fixed while scaling and panning as the centroid moves.
        PinchHandler {
            id: pinch
            target: null
            property real startMinX: 0
            property real startMaxX: 0
            property real startFocalT: 0

            onActiveChanged: {
                if (active) {
                    startMinX = root.viewMinX
                    startMaxX = root.viewMaxX
                    startFocalT = root.pixelToTime(root.clampToPlot(centroid.position.x))
                }
            }
            onActiveScaleChanged: root.applyPinch(pinch)
            onActiveTranslationChanged: if (pinch.active) root.applyPinch(pinch)
            onCentroidChanged: if (pinch.active) root.applyPinch(pinch)
        }

        // Mouse wheel → zoom the x-window around the cursor.
        WheelHandler {
            id: wheelH
            target: null
            acceptedDevices: PointerDevice.Mouse
            onWheel: (event) => {
                const factor = event.angleDelta.y > 0 ? (1 / 1.2) : 1.2
                root.zoomAround(wheelH.point.position.x, factor)
            }
        }

        // Mouse left-drag → pan the x-window (content follows the cursor).
        DragHandler {
            id: mousePan
            target: null
            acceptedDevices: PointerDevice.Mouse
            acceptedButtons: Qt.LeftButton
            property real lastTx: 0
            onActiveChanged: if (active) lastTx = 0
            onActiveTranslationChanged: {
                const dx = activeTranslation.x - lastTx
                lastTx = activeTranslation.x
                root.panByPixels(dx)
            }
        }

        // Vertical inspect cursor.
        Rectangle {
            visible: overlay.inspecting
            width: 2
            color: "#ffffff"
            x: overlay.clampedX - width / 2
            y: graph.plotArea.y
            height: graph.plotArea.height
        }

        // Highlight where the inspect line meets the graph line: a soft accent halo behind a
        // crisp white dot ringed in the accent colour, tying it to the line + glow.
        Rectangle {
            visible: overlay.inspecting && !isNaN(overlay.dataY)
            width: 22
            height: 22
            radius: width / 2
            color: Qt.rgba(root.glowColor.r, root.glowColor.g, root.glowColor.b, 0.30)
            x: overlay.clampedX - width / 2
            y: overlay.dataYPixel - height / 2
        }
        Rectangle {
            visible: overlay.inspecting && !isNaN(overlay.dataY)
            width: 12
            height: 12
            radius: width / 2
            color: "#ffffff"
            border.width: 2
            border.color: root.glowColor
            x: overlay.clampedX - width / 2
            y: overlay.dataYPixel - height / 2
        }

        // Live "now" marker: a solid accent core with a slow radar-style pulse ring, at the
        // latest value (the rolling right edge). Shown only when the host marks the graph live
        // AND "now" is inside the visible window (hidden once the user pans back into history).
        // Independent of `inspecting`, so it keeps pulsing whether or not the cursor is down.
        Item {
            id: liveDot
            readonly property real liveT: root.dataMaxX
            readonly property real liveV: root.valueAt(root.dataMaxX)
            visible: root.live && root.dataCount > 0 && !isNaN(liveV)
                     && liveT >= root.viewMinX && liveT <= root.viewMaxX
            x: root.timeToPixel(liveT)
            y: root.valueToPixel(liveV)

            // Expanding + fading pulse ring, looped while the marker is visible.
            Rectangle {
                id: livePulse
                anchors.centerIn: parent
                width: 12
                height: 12
                radius: width / 2
                color: root.glowColor
                SequentialAnimation {
                    running: liveDot.visible
                    loops: Animation.Infinite
                    ParallelAnimation {
                        NumberAnimation { target: livePulse; property: "scale"; from: 1.0; to: 3.2; duration: 1500; easing.type: Easing.OutQuad }
                        NumberAnimation { target: livePulse; property: "opacity"; from: 0.5; to: 0.0; duration: 1500; easing.type: Easing.OutQuad }
                    }
                }
            }
            // Solid core dot with a white ring (accent-filled, so it reads as the live point
            // distinct from the white-filled inspect dot).
            Rectangle {
                anchors.centerIn: parent
                width: 11
                height: 11
                radius: width / 2
                color: root.glowColor
                border.width: 2
                border.color: "#ffffff"
            }
        }

        // Inspect readout: time at the cursor + held value, in a "liquid glass" pill matching
        // the dock and notification containers (GlassPanel + a floating drop shadow). The
        // frosted-blur backdrop is intentionally off: the tooltip lives inside the graph, so a
        // real backdrop source would have to be an ancestor and would capture the panel itself.
        // Without it GlassPanel degrades to the glass chrome — dark translucent tint, bright
        // white rim, specular highlight — which reads cleanly over the dark card.
        RectangularShadow {
            anchors.fill: readout
            visible: readout.visible
            radius: readout.radius
            blur: 24
            spread: 0
            offset: Qt.vector2d(0, 6)
            color: Theme.notificationShadow
        }

        GlassPanel {
            id: readout
            visible: overlay.inspecting && !isNaN(overlay.dataY)
            frostedBackdrop: false
            radius: Theme.notificationRadius
            width: readoutCol.implicitWidth + 28
            height: readoutCol.implicitHeight + 20
            x: Math.min(overlay.clampedX + 12,
                        graph.plotArea.x + graph.plotArea.width - width)
            y: graph.plotArea.y + 6

            Column {
                id: readoutCol
                anchors.centerIn: parent
                spacing: 2

                Text {
                    text: isNaN(overlay.dataX) ? ""
                          : Qt.formatDateTime(new Date(overlay.dataX), "dd.MM HH:mm:ss")
                    color: Theme.dataLabelTitle
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                }
                Text {
                    text: isNaN(overlay.dataY) ? ""
                          : overlay.dataY.toFixed(2) + (root.unit ? " " + root.unit : "")
                    color: Theme.notificationText
                    font.family: Theme.fontFamily
                    font.pixelSize: 16
                    font.bold: true
                }
            }
        }
    }

    // Restore the full extent of the loaded range. Declared after the overlay so
    // its tap is not intercepted by the overlay's handlers.
    TextButton {
        visible: !root.viewIsFull && root.dataCount > 0
        anchors.right: graph.right
        anchors.top: graph.top
        anchors.margins: 18
        label: qsTr("Palauta")
        onClicked: root.viewFull()
    }

    // Placeholder while empty: distinguishes "loading" from "no stored history".
    Text {
        anchors.centerIn: graph
        visible: root.dataCount === 0
        text: root.dataLoading ? "Ladataan…" : "Ei dataa"
        color: Theme.viewLabel
        font.family: Theme.fontFamily
        font.pixelSize: 20
    }

    // --- View management ------------------------------------------------------
    function resetView() {
        root.userControlled = false
        fullMinX = root.dataMinX
        fullMaxX = root.dataMaxX
        viewMinX = root.dataMinX
        viewMaxX = root.dataMaxX
    }
    function viewFull() {
        // "Palauta" re-engages live auto-follow.
        root.userControlled = false
        viewMinX = fullMinX
        viewMaxX = fullMaxX
    }
    function clampWidth(w) {
        const fullSpan = fullMaxX - fullMinX
        const minSpan = Math.max(1, fullSpan / 5000)  // limit how far we can zoom in
        return Math.max(minSpan, Math.min(w, fullSpan))
    }
    function setView(newMin, newMax) {
        const fullSpan = fullMaxX - fullMinX
        const width = newMax - newMin
        if (width >= fullSpan) { viewMinX = fullMinX; viewMaxX = fullMaxX; return }
        if (newMin < fullMinX) { newMin = fullMinX; newMax = newMin + width }
        if (newMax > fullMaxX) { newMax = fullMaxX; newMin = newMax - width }
        viewMinX = newMin
        viewMaxX = newMax
    }
    function zoomAround(focalPx, factor) {
        root.userControlled = true
        const a = graph.plotArea
        if (a.width <= 0) return
        const oldWidth = viewMaxX - viewMinX
        if (oldWidth <= 0) return
        const focalT = pixelToTime(clampToPlot(focalPx))
        const newWidth = clampWidth(oldWidth * factor)
        const frac = (focalT - viewMinX) / oldWidth
        const newMin = focalT - frac * newWidth
        setView(newMin, newMin + newWidth)
    }
    function panByPixels(dxPixels) {
        root.userControlled = true
        const a = graph.plotArea
        if (a.width <= 0) return
        const span = viewMaxX - viewMinX
        // Dragging right shows earlier data, so the content follows the cursor.
        const dt = -dxPixels / a.width * span
        setView(viewMinX + dt, viewMaxX + dt)
    }
    function applyPinch(p) {
        if (!p.active) return
        root.userControlled = true
        const a = graph.plotArea
        if (a.width <= 0) return
        const startWidth = p.startMaxX - p.startMinX
        const newWidth = clampWidth(startWidth / p.activeScale)
        const curFrac = (clampToPlot(p.centroid.position.x) - a.x) / a.width
        const newMin = p.startFocalT - curFrac * newWidth
        setView(newMin, newMin + newWidth)
    }

    // --- Pixel <-> data mapping (GraphsView has no built-in conversion) -------
    function clampToPlot(px) {
        const a = graph.plotArea
        return Math.max(a.x, Math.min(px, a.x + a.width))
    }
    function pixelToTime(px) {
        const a = graph.plotArea
        if (a.width <= 0)
            return xAxis.min
        return xAxis.min + (px - a.x) / a.width * (xAxis.max - xAxis.min)
    }
    // Forward maps (data → plot pixels), the inverse of pixelToTime, using the same axis
    // range the line is drawn with. Shared by the inspect highlight dot and the live marker.
    function timeToPixel(t) {
        const a = graph.plotArea
        const span = xAxis.max - xAxis.min
        return span <= 0 ? a.x : a.x + (t - xAxis.min) / span * a.width
    }
    function valueToPixel(v) {
        const a = graph.plotArea
        const span = yAxis.max - yAxis.min
        return span <= 0 ? a.y : a.y + (yAxis.max - v) / span * a.height
    }

    // --- Adaptive x-axis time ticks -------------------------------------------
    // Smallest "nice" clock step (ms) >= raw, from 1s up to ~4 weeks, so a ~5-tick target
    // lands on round times/dates instead of arbitrary epoch values.
    function niceTimeStep(raw) {
        const steps = [1000, 2000, 5000, 10000, 15000, 30000,           // seconds
                       60000, 120000, 300000, 600000, 900000, 1800000,  // minutes
                       3600000, 7200000, 10800000, 21600000, 43200000,  // hours
                       86400000, 172800000, 604800000, 1209600000, 2419200000]  // days
        for (let i = 0; i < steps.length; ++i)
            if (steps[i] >= raw)
                return steps[i]
        return steps[steps.length - 1]
    }
    // Epoch-ms of the local-time midnight at or before t — the tick anchor, so ticks fall
    // on round clock boundaries in the display timezone. (Day-scale ticks step by a fixed
    // 24h from here, so they can drift an hour across a DST change; harmless for a date label.)
    function localMidnight(t) {
        const d = new Date(t)
        d.setHours(0, 0, 0, 0)
        return d.getTime()
    }
    // Label for one tick, chosen by the step: day-scale steps read as a date, minute/hour
    // steps as a time, second steps as a time with seconds. Format follows the step, so
    // adjacent labels are always distinct.
    function formatTimeTick(t, step) {
        const d = new Date(t)
        if (step >= 86400000)
            return Qt.formatDateTime(d, "dd.MM")
        if (step >= 60000)
            return Qt.formatDateTime(d, "HH:mm")
        return Qt.formatDateTime(d, "HH:mm:ss")
    }

    // Expand the raw readings into an explicit path in DATA coordinates, clamped to the
    // full extent [lo, hi], per root.lineMode — drawn with the straight line style so the
    // path geometry we build IS what shows (no reliance on renderer step support). Data
    // logic still uses the raw pointsData, so the inspect readout and y-fit stay consistent
    // (valueAt() branches on lineMode the same way).
    function buildStepped(pts) {
        const n = pts.length
        if (n === 0)
            return []
        const lo = root.fullMinX
        const hi = root.fullMaxX
        if (root.lineMode === "linear")
            return buildLinearPath(pts, lo, hi)
        // --- "step" (hold-forward), the default ---
        // A horizontal segment at the held value out to the next timestamp, then a
        // vertical jump to the new value — a true step (no slope). Right for sampled /
        // held signals, whose in-between telemetry never sent is unknown.
        const out = []
        // Value held at the left edge: the y of the last point at or before lo (the
        // boundary the live roller keeps, or the first point), so the line starts
        // flat at the edge even when the first reading predates the window. Clamping
        // to [lo, hi] also keeps the path x-monotonic when a boundary point sits to
        // the left of the window.
        let heldY = pts[0].y
        let i = 0
        while (i < n && pts[i].x <= lo) {
            heldY = pts[i].y
            ++i
        }
        out.push(Qt.point(lo, heldY))
        // Step through points inside (lo, hi]: hold the previous value to the new
        // time, then jump to the new value (a true step, no slope).
        for (; i < n && pts[i].x <= hi; ++i) {
            out.push(Qt.point(pts[i].x, heldY))
            out.push(Qt.point(pts[i].x, pts[i].y))
            heldY = pts[i].y
        }
        // Hold the last value forward to the right edge ("held until now" in live
        // mode); a single reading thus draws as a flat line across the window.
        out.push(Qt.point(hi, heldY))
        return out
    }

    // "linear" (point-to-point) path in DATA coordinates, clamped to [lo, hi]: an
    // interpolated point at the left edge, every raw reading strictly inside the window,
    // then an interpolated point at the right edge. Right for accumulators / continuous
    // quantities whose value genuinely tracks ~linearly between readings. The edge values
    // match valueAt()'s "linear" branch (hold at the ends when the edge lies outside the
    // data), so a value held constant across the window still draws as one flat line —
    // identical to the step build's boundary-fill case.
    function buildLinearPath(pts, lo, hi) {
        const n = pts.length
        const out = []
        out.push(Qt.point(lo, interpAt(pts, lo)))
        for (let i = 0; i < n; ++i) {
            if (pts[i].x > lo && pts[i].x < hi)
                out.push(Qt.point(pts[i].x, pts[i].y))
        }
        out.push(Qt.point(hi, interpAt(pts, hi)))
        return out
    }

    // Linear interpolation of the raw ascending series at time dx: the value on the
    // straight segment between the two readings bracketing dx, clamped to the endpoints
    // outside the data range. Binary-searches for the bracketing pair.
    function interpAt(pts, dx) {
        const n = pts.length
        if (n === 0)
            return NaN
        if (dx <= pts[0].x)
            return pts[0].y
        if (dx >= pts[n - 1].x)
            return pts[n - 1].y
        // Largest index with pts[i].x <= dx.
        let lo = 0
        let hi = n - 1
        while (lo < hi) {
            const mid = (lo + hi + 1) >> 1
            if (pts[mid].x <= dx)
                lo = mid
            else
                hi = mid - 1
        }
        const a = pts[lo]
        const b = pts[lo + 1]
        const span = b.x - a.x
        if (span <= 0)
            return a.y
        return a.y + (b.y - a.y) * (dx - a.x) / span
    }

    // Value at x for the inspect readout, y-fit edge values and the live marker —
    // consistent with the rendered line. "linear": interpolate between the bracketing
    // readings. "step" (default): hold-forward — the value of the most recent point at
    // or before x (binary search over the ascending raw series).
    function valueAt(dx) {
        const pts = root.pointsData
        const n = pts.length
        if (n === 0)
            return NaN
        if (root.lineMode === "linear")
            return interpAt(pts, dx)
        if (dx <= pts[0].x)
            return pts[0].y
        if (dx >= pts[n - 1].x)
            return pts[n - 1].y
        let lo = 0
        let hi = n - 1
        while (lo < hi) {
            const mid = (lo + hi + 1) >> 1
            if (pts[mid].x <= dx)
                lo = mid
            else
                hi = mid - 1
        }
        return pts[lo].y
    }

    // Min/max y over a time window, including the held edge values so the step
    // line stays inside the re-fitted y-axis. Binary-searches the visible slice.
    function fitY(tMin, tMax) {
        const pts = root.pointsData
        const n = pts.length
        if (n === 0)
            return { min: 0, max: 1 }
        let mn = Infinity
        let mx = -Infinity
        const yL = valueAt(tMin)
        if (!isNaN(yL)) { mn = Math.min(mn, yL); mx = Math.max(mx, yL) }
        // First index with x >= tMin.
        let lo = 0
        let hi = n
        while (lo < hi) {
            const m = (lo + hi) >> 1
            if (pts[m].x < tMin) lo = m + 1
            else hi = m
        }
        for (let i = lo; i < n && pts[i].x <= tMax; ++i) {
            mn = Math.min(mn, pts[i].y)
            mx = Math.max(mx, pts[i].y)
        }
        const yR = valueAt(tMax)
        if (!isNaN(yR)) { mn = Math.min(mn, yR); mx = Math.max(mx, yR) }
        if (mn === Infinity)
            return { min: root.dataMinY, max: root.dataMaxY }
        return { min: mn, max: mx }
    }
}

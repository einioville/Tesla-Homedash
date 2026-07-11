import QtQuick
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

    // The built-in dark-gradient card background. The Trips view sets this false and
    // supplies its own minimalistic card, so the History view keeps its dashboard card.
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

    GradientCard {
        anchors.fill: parent
        visible: root.showBackground
        gradientCx: 0.5
        gradientCy: 0.0
    }

    GraphsView {
        id: graph
        anchors.fill: parent
        marginTop: root.plotMarginTop
        marginBottom: root.plotMarginBottom
        marginLeft: root.plotMarginLeft
        marginRight: root.plotMarginRight

        // Transparent background so the card behind the graph shows through — the
        // Trip / Charging translucent Rectangle, or the History GradientCard. Without
        // this the default theme paints an opaque rectangle over the card, which reads
        // as "the card disappeared". Only the two background flags are overridden; axis
        // line / label colours keep the default theme, so the graph looks unchanged
        // apart from blending into its card. The LineSeries sets its own colour.
        theme: GraphsTheme {
            backgroundVisible: false
            plotAreaBackgroundVisible: false
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
            gridVisible: false     // only the line shows in the plot area
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
            gridVisible: false
            subGridVisible: false
        }

        LineSeries {
            id: series
            width: 2
            color: Theme.accent
            // Steps are built explicitly in buildStepped() (a horizontal hold then
            // a vertical jump per reading), so the default straight style renders a
            // true step. Telemetry only sends a value when it changes, so each
            // reading holds until the next instead of sloping toward it; building
            // the path ourselves avoids relying on the renderer's step line style.
        }
    }

    // A fresh load: reset the view to the full extent and refill the series. The
    // owning view calls this when its data source signals new data (History.onHistoryReady
    // / Trips.onSeriesReady).
    function reloadFull() {
        root.resetView()
        series.replace(root.buildStepped(root.pointsData))
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
        series.replace(root.buildStepped(root.pointsData))
    }
    Component.onCompleted: if (root.dataCount > 0) { resetView(); series.replace(root.buildStepped(root.pointsData)) }

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

        // Inspect readout: time at the cursor + held value.
        Rectangle {
            visible: overlay.inspecting && !isNaN(overlay.dataY)
            color: "#cc1b2230"
            border.color: Theme.dockBorder
            border.width: 1
            radius: 6
            width: readoutCol.implicitWidth + 16
            height: readoutCol.implicitHeight + 12
            x: Math.min(overlay.clampedX + 10,
                        graph.plotArea.x + graph.plotArea.width - width)
            y: graph.plotArea.y + 6

            Column {
                id: readoutCol
                anchors.centerIn: parent
                spacing: 2

                Text {
                    text: isNaN(overlay.dataX) ? ""
                          : Qt.formatDateTime(new Date(overlay.dataX), "dd.MM HH:mm:ss")
                    color: "#c0c0c0"
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                }
                Text {
                    text: isNaN(overlay.dataY) ? ""
                          : overlay.dataY.toFixed(2) + (root.unit ? " " + root.unit : "")
                    color: "#ffffff"
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

    // Expand the raw readings into an explicit step path: a horizontal segment at
    // the held value out to the next timestamp, then a vertical jump to the new
    // value. Drawn with the straight line style this yields true steps (no slope),
    // independent of any renderer step support. Data logic still uses the raw
    // History.points, so the inspect readout and y-fit are unaffected.
    function buildStepped(pts) {
        const n = pts.length
        if (n === 0)
            return []
        const lo = root.fullMinX
        const hi = root.fullMaxX
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

    // Step (hold-forward) lookup: the value at x is that of the most recent point
    // at or before x. Binary search over the ascending raw series.
    function valueAt(dx) {
        const pts = root.pointsData
        const n = pts.length
        if (n === 0)
            return NaN
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

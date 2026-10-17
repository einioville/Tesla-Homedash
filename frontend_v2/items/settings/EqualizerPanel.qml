import QtQuick
import QtQuick.Shapes
import frontend_v2

// The graphic equalizer — the `status: "equalizer"` widget of Media ›
// Taajuuskorjain (SettingsPane resolves the name). Five bands drawn as knobs on
// a smooth curve with the graphs' gradient glow under it; the bass shelf is the
// ordinary slider row beneath this widget, and lifts the curve's low end.
//
// The band gains are HIDDEN backend settings, and the frontend strips hidden
// entries before any widget sees them, so the band list (keys, labels, range)
// comes from the subsection's own `bands` and the values from Settings.valueOf.
// The equalizer's runtime state rides on the bass row's entry.
//
// Writes follow the settings' commit rules: a drag or a wheel spin moves only
// the knob, and the value is written once — on release, or when the wheel has
// settled — because each write is a config.json save, a hook and a schema
// broadcast. Until the schema confirms it, the knob holds the written value
// (`pending`) rather than jumping back to the old one in between.
//
// Only a press ON a knob grabs: anywhere else in the plot the press goes to the
// page, so the card never becomes a dead zone the page cannot be scrolled from.
//
// Behind the curve, while something plays, the spectrum of what reaches the
// speakers (MediaSpectrum, recorded after the filters) on the plot's own
// frequency axis — so a knob moved shows its effect on the sound under it.
Item {
    id: panel

    // The Settings view's isCurrent: the spectrum is recorded only while it is.
    property bool live: false

    // --- Schema -------------------------------------------------------------
    // This card's subsection, found by id: a status widget is handed nothing.
    readonly property var section: {
        const groups = Settings.groups
        for (let i = 0; i < groups.length; ++i) {
            const sections = groups[i].sections !== undefined ? groups[i].sections : []
            for (let j = 0; j < sections.length; ++j) {
                if (sections[j].id === "equalizer" && sections[j].origin === "backend")
                    return sections[j]
            }
        }
        return null
    }
    readonly property var bands: section !== null && section.bands !== undefined ? section.bands : []
    readonly property int count: bands.length
    readonly property real minGain: count > 0 ? bands[0].min : -12
    readonly property real maxGain: count > 0 ? bands[0].max : 12

    readonly property string bassKey: "audio.bassBoost"
    readonly property var bassEntry: {
        const entries = section !== null && section.settings !== undefined ? section.settings : []
        for (let i = 0; i < entries.length; ++i) {
            if (entries[i].key === panel.bassKey)
                return entries[i]
        }
        return null
    }
    // "detecting" → "unavailable" | "off" | "on", or "failed" when a start did
    // not come up (backend/src/audio_service/CLAUDE.md).
    readonly property string eqState: bassEntry !== null && bassEntry.runtime !== undefined
                                      ? bassEntry.runtime.state : ""
    readonly property bool available: eqState !== "unavailable"

    // --- Values -------------------------------------------------------------
    // valueOf is an invokable, which captures no dependency; valuesRevision does.
    readonly property var savedGains: {
        const revision = Settings.valuesRevision
        const out = []
        for (let i = 0; i < count; ++i)
            out.push(Number(Settings.valueOf(bands[i].key)) || 0)
        return out
    }
    readonly property real savedBass: {
        const revision = Settings.valuesRevision
        return Number(Settings.valueOf(panel.bassKey)) || 0
    }

    // Written values the schema has not confirmed yet, by key.
    property var pending: ({})
    // The band a drag or a wheel spin is moving, and where it has it.
    property int previewBand: -1
    property real previewGain: 0

    // What each knob is set to now: the finger, else a pending write, else saved.
    readonly property var gains: {
        const out = []
        for (let i = 0; i < count; ++i) {
            const key = bands[i].key
            out.push(i === previewBand ? previewGain
                                       : pending[key] !== undefined ? pending[key] : savedGains[i])
        }
        return out
    }
    readonly property real bass: pending[bassKey] !== undefined ? pending[bassKey] : savedBass
    readonly property bool flat: bass === 0 && gains.every(gain => gain === 0)

    onSavedGainsChanged: {
        for (let i = 0; i < count; ++i) {
            if (pending[bands[i].key] === savedGains[i])
                settle(bands[i].key)
        }
    }
    onSavedBassChanged: if (pending[bassKey] === savedBass) settle(bassKey)

    Connections {
        target: Settings
        // A refused write leaves the saved value as it was; the knob goes back.
        function onWriteFailed(key, message) { panel.settle(key) }
        // An unchanged write brings no schema to confirm it.
        function onWriteSucceeded(key, applied) { if (applied === "unchanged") panel.settle(key) }
    }

    function settle(key) {
        if (pending[key] === undefined)
            return
        const next = Object.assign({}, pending)
        delete next[key]
        pending = next
    }

    function write(key, value) {
        const next = Object.assign({}, pending)
        next[key] = value
        pending = next
        Settings.setValue(key, value)
    }

    // Ends a drag or a wheel spin: writes the band if it moved.
    //
    // The write goes in BEFORE the band is let go. Releasing it first re-evaluates
    // the knob's value against the old saved one and re-enables its animation in
    // the same instant, so the knob set off back toward the old value and then
    // returned once the pending write arrived.
    function finishPreview(commitIt) {
        const i = previewBand
        if (i < 0)
            return
        const gain = previewGain
        const key = bands[i].key
        const current = pending[key] !== undefined ? pending[key] : savedGains[i]
        if (commitIt && gain !== current)
            write(key, gain)
        previewBand = -1
    }

    // Flat: every band and the bass back to 0, one write per value that is not.
    function reset() {
        finishPreview(false)
        for (let i = 0; i < count; ++i) {
            if (gains[i] !== 0)
                write(bands[i].key, 0)
        }
        if (bass !== 0)
            write(bassKey, 0)
    }

    function clampGain(gain) {
        return Math.max(minGain, Math.min(maxGain, Math.round(gain)))
    }

    // A typographic minus, as the scale's labels have.
    function signedGain(gain) {
        return gain > 0 ? "+" + gain : gain < 0 ? "−" + (-gain) : "0"
    }

    // --- Geometry -----------------------------------------------------------
    readonly property int gutter: 40        // the dB scale, left of the plot
    readonly property int knobSize: 22      // the settings slider's handle
    readonly property int grabReach: 36     // how far from a knob's centre a press still takes it
    readonly property real plotTop: knobSize / 2 + 4
    readonly property real plotBottom: plot.height - knobSize / 2 - 4
    readonly property real columnWidth: count > 0 ? (plot.width - gutter) / count : 0

    function xOf(i) { return gutter + columnWidth * (i + 0.5) }

    // Log frequency fitted to the columns by least squares: the bands are about
    // two octaves apart but the top one less, and the fit puts every band within
    // a tenth of a column of its knob. Null for a schema without the bands' "hz".
    readonly property var hzFit: {
        if (count < 2 || bands[0].hz === undefined)
            return null
        let meanIndex = 0
        let meanLog = 0
        for (let i = 0; i < count; ++i) {
            meanIndex += i / count
            meanLog += Math.log(bands[i].hz) / count
        }
        let covariance = 0
        let variance = 0
        for (let i = 0; i < count; ++i) {
            covariance += (i - meanIndex) * (Math.log(bands[i].hz) - meanLog)
            variance += (i - meanIndex) * (i - meanIndex)
        }
        return { meanIndex: meanIndex, meanLog: meanLog, slope: covariance / variance }
    }
    function xOfHz(hz) {
        return xOf(hzFit.meanIndex + (Math.log(hz) - hzFit.meanLog) / hzFit.slope)
    }
    function yOf(gain) { return plotTop + (maxGain - gain) / (maxGain - minGain) * (plotBottom - plotTop) }
    function gainOf(y) { return maxGain - (y - plotTop) / (plotBottom - plotTop) * (maxGain - minGain) }
    function bandAt(x) {
        if (count === 0 || x < gutter)
            return -1
        return Math.max(0, Math.min(count - 1, Math.floor((x - gutter) / columnWidth)))
    }

    // --- The curve ----------------------------------------------------------
    // Through the knobs as they are DRAWN (animated), so a reset morphs the curve
    // back to flat instead of snapping it. Collected from the knobs themselves.
    property var shownGains: []
    property real shownBass: bass
    Behavior on shownBass {
        NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
    }

    function collectShown() {
        const out = []
        for (let i = 0; i < count; ++i) {
            const knob = knobs.itemAt(i)
            out.push(knob !== null ? knob.shown : (gains[i] ?? 0))
        }
        shownGains = out
    }

    // The knobs, plus a point at each edge of the plot: the right edge carries
    // the top band on flat, and the left edge the bottom band plus the bass
    // shelf, which lifts everything below its corner.
    readonly property var curvePoints: {
        const out = []
        if (count === 0 || shownGains.length !== count || plot.width <= gutter)
            return out
        const low = Math.max(minGain, Math.min(maxGain, shownGains[0] + shownBass))
        out.push({ x: gutter, y: yOf(low) })
        for (let i = 0; i < count; ++i)
            out.push({ x: xOf(i), y: yOf(shownGains[i]) })
        out.push({ x: plot.width, y: yOf(shownGains[count - 1]) })
        return out
    }

    // A monotone cubic (Fritsch–Carlson) through the points, as SVG path data. A
    // plain spline overshoots between two knobs at opposite ends and draws the
    // curve past ±12; the monotone one never leaves the range its two ends span,
    // and levels off at every knob that is a peak or a dip.
    function smoothPath(pts) {
        const n = pts.length
        if (n < 2)
            return ""
        const d = []
        for (let k = 0; k < n - 1; ++k)
            d.push((pts[k + 1].y - pts[k].y) / (pts[k + 1].x - pts[k].x))
        const m = [d[0]]
        for (let k = 1; k < n - 1; ++k)
            m.push(d[k - 1] * d[k] <= 0 ? 0 : (d[k - 1] + d[k]) / 2)
        m.push(d[n - 2])
        for (let k = 0; k < n - 1; ++k) {
            if (d[k] === 0) {
                m[k] = 0
                m[k + 1] = 0
                continue
            }
            const a = m[k] / d[k]
            const b = m[k + 1] / d[k]
            const s = a * a + b * b
            if (s > 9) {
                const t = 3 / Math.sqrt(s)
                m[k] = t * a * d[k]
                m[k + 1] = t * b * d[k]
            }
        }
        let path = "M " + pts[0].x + " " + pts[0].y
        for (let k = 0; k < n - 1; ++k) {
            const h = (pts[k + 1].x - pts[k].x) / 3
            path += " C " + (pts[k].x + h) + " " + (pts[k].y + m[k] * h)
                  + " " + (pts[k + 1].x - h) + " " + (pts[k + 1].y - m[k + 1] * h)
                  + " " + pts[k + 1].x + " " + pts[k + 1].y
        }
        return path
    }

    readonly property string curvePath: smoothPath(curvePoints)
    // The same curve closed down to the floor, for the glow under it.
    readonly property string fillPath: curvePath.length > 0
                                       ? curvePath + " L " + plot.width + " " + plot.height
                                         + " L " + gutter + " " + plot.height + " Z"
                                       : ""

    implicitHeight: content.implicitHeight

    Column {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right

        // --- Status and reset -------------------------------------------------
        // Its height is kept whether or not the button shows, so moving the first
        // band off flat does not push the rows below down under the finger.
        Item {
            width: parent.width
            height: 40

            SettingDetails {
                anchors.left: parent.left
                anchors.right: resetButton.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                topPadding: 0
                level: panel.eqState === "on" ? "ok"
                     : panel.eqState === "unavailable" ? "warn"
                     : panel.eqState === "failed" ? "error" : "unknown"
                statusText: {
                    switch (panel.eqState) {
                    case "on": return qsTr("Käytössä")
                    case "off": return qsTr("Ei käytössä – kaikki säädöt ovat nollassa")
                    case "unavailable": return qsTr("Ei saatavilla: vaatii PipeWire-äänijärjestelmän")
                    case "failed": return qsTr("Ei käynnistynyt – säädä jotain kaistaa yrittääksesi uudelleen")
                    default: return qsTr("Tarkistetaan…")
                    }
                }
            }

            // No arming: like the graphs' Palauta, it only puts a view back.
            DialogButton {
                id: resetButton
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(96, implicitWidth)
                label: qsTr("Nollaa")
                opacity: panel.flat || !panel.available ? 0 : 1
                visible: opacity > 0
                onActivated: panel.reset()

                Behavior on opacity {
                    NumberAnimation { duration: 150 }
                }
            }
        }

        // --- The plot ---------------------------------------------------------
        Item {
            id: plot
            width: parent.width
            height: 200
            enabled: panel.available
            opacity: panel.available ? 1 : Theme.settingIrrelevantOpacity

            // Under the grid, spanning the backend's bands where they fall on the
            // plot's axis. Clipped, because the line closes its fill outside itself.
            MediaSpectrum {
                visible: panel.hzFit !== null
                active: panel.live
                x: visible ? panel.xOfHz(lowHz) : 0
                width: visible ? panel.xOfHz(highHz) - x : 0
                height: plot.height
                clip: true
            }

            // Grid: the range's ends, its halves and 0 dB, which is brighter —
            // the line the curve rests on when nothing is changed.
            Repeater {
                model: [panel.maxGain, panel.maxGain / 2, 0, panel.minGain / 2, panel.minGain]

                Item {
                    required property real modelData

                    Rectangle {
                        x: panel.gutter
                        y: Math.round(panel.yOf(parent.modelData))
                        width: plot.width - panel.gutter
                        height: 1
                        color: parent.modelData === 0 ? "#66ffffff" : "#26ffffff"
                    }

                    Text {
                        x: 0
                        width: panel.gutter - 10
                        y: panel.yOf(parent.modelData) - height / 2
                        horizontalAlignment: Text.AlignRight
                        text: panel.signedGain(parent.modelData)
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        color: Theme.dataLabelTitle
                    }
                }
            }

            // A groove per band, the settings slider's track stood on end.
            Repeater {
                model: panel.count

                Rectangle {
                    required property int index

                    x: panel.xOf(index) - width / 2
                    y: panel.plotTop
                    width: 5
                    height: panel.plotBottom - panel.plotTop
                    radius: 3
                    color: Theme.sliderGroove
                }
            }

            // The glow under the curve and the curve itself — the graphs' look:
            // HistoryGraph's fill stops, its 2px line in the accent.
            Item {
                anchors.fill: parent
                clip: true

                Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer

                    ShapePath {
                        strokeWidth: 0
                        strokeColor: "transparent"
                        fillGradient: LinearGradient {
                            x1: 0
                            y1: panel.plotTop
                            x2: 0
                            y2: plot.height
                            GradientStop { position: 0.0; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.35) }
                            GradientStop { position: 0.55; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.35 * 0.22) }
                            GradientStop { position: 1.0; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.0) }
                        }
                        PathSvg { path: panel.fillPath }
                    }

                    ShapePath {
                        strokeWidth: 2
                        strokeColor: Theme.accent
                        fillColor: "transparent"
                        capStyle: ShapePath.RoundCap
                        joinStyle: ShapePath.RoundJoin
                        PathSvg { path: panel.curvePath }
                    }
                }
            }

            // Takes a press only on (or near) a knob; anything else is the page's.
            MouseArea {
                id: dragArea
                anchors.fill: parent
                // Inside the settings Flickable: without this, a drag with any
                // vertical travel is taken over as a scroll.
                preventStealing: true

                property real grabOffset: 0

                onPressed: (mouse) => {
                    const i = panel.bandAt(mouse.x)
                    if (i < 0 || Math.abs(mouse.y - panel.yOf(panel.gains[i])) > panel.grabReach) {
                        mouse.accepted = false
                        return
                    }
                    panel.finishPreview(true)
                    grabOffset = mouse.y - panel.yOf(panel.gains[i])
                    panel.previewGain = panel.gains[i]
                    panel.previewBand = i
                }
                onPositionChanged: (mouse) => {
                    if (panel.previewBand >= 0)
                        panel.previewGain = panel.clampGain(panel.gainOf(mouse.y - grabOffset))
                }
                onReleased: panel.finishPreview(true)
                onCanceled: panel.finishPreview(false)
            }

            // The wheel steps the band under the pointer, one dB per notch, and
            // writes once it settles — the same contract as SettingNumber's.
            Repeater {
                model: panel.count

                WheelStepArea {
                    required property int index

                    x: panel.xOf(index) - panel.columnWidth / 2
                    width: panel.columnWidth
                    height: plot.height

                    onStepped: (direction) => {
                        if (panel.previewBand !== index) {
                            panel.finishPreview(true)
                            panel.previewGain = panel.gains[index]
                            panel.previewBand = index
                        }
                        panel.previewGain = panel.clampGain(panel.previewGain + direction)
                    }
                    onSettled: {
                        if (panel.previewBand === index && !dragArea.pressed)
                            panel.finishPreview(true)
                    }
                }
            }

            // The knobs: the settings slider's handle. Each animates to a value set
            // from outside (a reset, another display) but follows a finger exactly.
            Repeater {
                id: knobs
                model: panel.count

                onItemAdded: panel.collectShown()

                Rectangle {
                    id: knob

                    required property int index

                    readonly property bool held: panel.previewBand === index
                    property real shown: panel.gains[index] ?? 0

                    Behavior on shown {
                        enabled: !knob.held
                        NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
                    }
                    onShownChanged: panel.collectShown()

                    x: panel.xOf(index) - width / 2
                    y: panel.yOf(shown) - height / 2
                    width: panel.knobSize
                    height: panel.knobSize
                    radius: height / 2
                    color: held ? Theme.accent : Theme.dataLabelValue
                    border.width: 1
                    border.color: Theme.tripCardBorder
                }
            }
        }

        // --- Band labels ------------------------------------------------------
        Item {
            width: parent.width
            height: 44

            Repeater {
                model: panel.count

                Column {
                    required property int index

                    x: panel.xOf(index) - width / 2
                    y: 6
                    width: panel.columnWidth
                    spacing: 2

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: panel.bands[parent.index].label
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        color: Theme.dataLabelTitle
                    }

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: panel.signedGain(panel.gains[parent.index] ?? 0) + " dB"
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                        color: (panel.gains[parent.index] ?? 0) !== 0 ? Theme.accent : Theme.dataLabelTitle
                    }
                }
            }
        }
    }
}

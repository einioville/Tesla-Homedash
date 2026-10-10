import QtQuick
import frontend_v2

// One graph of the Järjestelmän tila section: the app's own HistoryGraph — the
// same axes, clock-time ticks, inspect line and glass readout, live marker, draw-in
// and pinch / drag zoom with *Palauta* as History, Trips and Charging — in the same
// translucent card with the title overlaid at the top left (ChargingGraphCard's
// look). A headline sits at the top right; graphs of several lines add a legend
// under the title, naming each line with its latest value.
//
// Fed like the Charging view's live graphs: the first data reloads the graph,
// every later update advances it (keeping a zoom the user made).
Item {
    id: root

    property string title: ""
    property string unit: ""
    property string summary: ""
    // { label, values (aligned with `times`, NaN = missing), color, dashed } per
    // line; the first is the main line (with the glow and live marker when alone).
    property var lines: []
    // Epoch ms per sample, oldest first.
    property var times: []
    property real windowMs: 600000
    property real fixedMinY: NaN
    property real fixedMaxY: NaN
    property bool zeroBased: false
    property bool live: false
    property bool loading: false
    // Formats a value for the legend and the readout.
    property var formatValue: function (v) { return v.toFixed(1) + " " + root.unit }
    // The widest value the legend will show, so a changing number never pushes
    // the entries after it around.
    property string widestValue: "100 %"
    // Shown instead of the graph when the metric cannot be read on this host
    // (no thermal sensor on WSL2); empty while it can.
    property string unavailableText: ""

    readonly property bool multi: lines.length > 1

    // Primed by the first data: that one reloads (draw-in), later ones advance.
    property bool primed: false

    function toPoints(values) {
        const out = []
        for (let i = 0; i < times.length && i < values.length; ++i) {
            const v = values[i]
            if (v !== undefined && v !== null && !isNaN(v))
                out.push({ "x": times[i], "y": v })
        }
        return out
    }

    function feed() {
        if (unavailableText.length > 0 || times.length < 2 || lines.length === 0)
            return
        const newest = times[times.length - 1]
        const points = lines.map(line => toPoints(line.values !== undefined ? line.values : []))
        graph.dataMinX = newest - windowMs
        graph.dataMaxX = newest
        graph.extraSeries = lines.slice(1).map((line, i) => ({
            "points": points[i + 1], "color": line.color, "label": line.label,
            "dashed": line.dashed === true
        }))
        graph.pointsData = points[0]
        graph.dataCount = points[0].length
        if (!primed) {
            primed = true
            graph.reloadFull()
        } else {
            graph.advanceLive()
        }
    }

    // `lines` and `times` change together; one feed for both.
    onLinesChanged: Qt.callLater(feed)
    onTimesChanged: Qt.callLater(feed)

    function latest(line) {
        const values = line.values !== undefined ? line.values : []
        for (let i = values.length - 1; i >= 0; --i) {
            if (!isNaN(values[i]))
                return root.formatValue(values[i])
        }
        return "—"
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.tripCardRadius
        color: Theme.tripCardBg
        border.width: 1
        border.color: Theme.tripCardBorder
    }

    HistoryGraph {
        id: graph
        anchors.fill: parent
        visible: root.unavailableText.length === 0
        showBackground: false
        // Room for the overlaid title, and the legend under it.
        plotMarginTop: 40 + (root.multi ? legend.height + 14 : 0)
        unit: root.unit
        lineMode: "linear"
        live: root.live && !root.multi
        zeroBased: root.zeroBased
        fixedMinY: root.fixedMinY
        fixedMaxY: root.fixedMaxY
        lineColor: root.lines.length > 0 ? root.lines[0].color : Theme.accent
        seriesLabel: root.lines.length > 0 ? root.lines[0].label : ""
        // A glow under one line of several would single it out.
        glowOpacity: root.multi ? 0 : 0.35
        formatValue: root.formatValue
        // The section scrolls; the wheel is the page's.
        wheelZoom: false
        pointsData: []
        dataMinY: 0
        dataMaxY: 1
        dataCount: 0
        dataLoading: root.loading
    }

    Text {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 16
        text: root.title + (root.unit.length > 0 ? " (" + root.unit + ")" : "")
        color: Theme.dataLabelTitle
        font.family: Theme.fontFamily
        font.pixelSize: 16
    }

    Text {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 16
        text: root.summary
        color: Theme.dataLabelValue
        font.family: Theme.fontFamily
        font.pixelSize: 16
    }

    // --- Legend (several lines only) ---------------------------------------------
    TextMetrics {
        id: valueMetrics
        font.family: Theme.fontFamily
        font.pixelSize: 12
        text: root.widestValue
    }

    Flow {
        id: legend
        visible: root.multi && graph.visible
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 42
        spacing: 14

        Repeater {
            model: root.multi ? root.lines : []

            Row {
                id: legendEntry

                required property var modelData

                spacing: 6

                // The line's own stroke in miniature — dashed too where the line is.
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    Repeater {
                        model: legendEntry.modelData.dashed ? 3 : 1

                        Rectangle {
                            width: legendEntry.modelData.dashed ? 4 : 16
                            height: 2
                            radius: 1
                            color: legendEntry.modelData.color
                        }
                    }
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: legendEntry.modelData.label
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    color: Theme.dataLabelTitle
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: valueMetrics.advanceWidth
                    text: root.latest(legendEntry.modelData)
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    color: Theme.dataLabelValue
                }
            }
        }
    }

    Text {
        anchors.centerIn: parent
        visible: root.unavailableText.length > 0
        text: root.unavailableText
        font.family: Theme.fontFamily
        font.pixelSize: 16
        color: Theme.viewLabel
    }
}

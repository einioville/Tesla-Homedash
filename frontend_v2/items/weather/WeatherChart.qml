import QtQuick
import QtQuick.Shapes
import frontend_v2
import "WeatherUtil.js" as U

// Every forecast hour on one horizontally scrollable chart, `hoursVisible` of
// them across the width: the temperature curve, rain bars with their amount on top, and a
// symbol / temperature / hour every `labelEvery` hours.
//
// A ListView with one delegate per hour, so only the visible hours exist. Each delegate
// draws its own piece of the curve, from the midpoint with the previous hour through its
// own value to the midpoint with the next, which joins into one smooth line. The
// temperature scale fits the hours on screen and eases to the new range when the chart
// comes to rest somewhere else.
Item {
    id: root

    property var hours: []
    property int hoursVisible: 24
    property int labelEvery: 2

    readonly property real colW: width / hoursVisible
    readonly property int firstVisible: Math.max(0, Math.min(hours.length - 1, Math.round(list.contentX / colW)))
    readonly property bool atStart: list.contentX < colW / 2

    // The user dragged or flicked (scrollToHour's animation does not count).
    signal userScrolled

    property real tMin: 0
    property real tMax: 10
    Behavior on tMin { NumberAnimation { duration: 350; easing.type: Easing.OutCubic } }
    Behavior on tMax { NumberAnimation { duration: 350; easing.type: Easing.OutCubic } }

    readonly property real curveTop: 66
    readonly property real barBase: height - 20
    readonly property real barMaxH: 40
    // The curve shares its lower part with the rain bars, which are drawn under it.
    readonly property real curveBottom: barBase - 12

    // Clamped to the chart: an hour outside the fitted range (one scrolling past, or one
    // just off screen) must still draw inside the chart, never over the card around it.
    function yAt(t) {
        return Math.max(2, Math.min(barBase, curveBottom - (t - tMin) / (tMax - tMin) * (curveBottom - curveTop)))
    }
    // Square-root scale, so the common light rain still shows: 0.1 mm ≈ 11 %, 1 mm ≈ 35 %.
    function barH(mm) { return mm > 0 ? Math.max(2, Math.sqrt(Math.min(mm, 8) / 8) * barMaxH) : 0 }

    function updateRange() {
        fitRange(firstVisible)
    }

    // Fits the scale to the hours on screen from `first` (plus a neighbour each side), but
    // never tighter than 5°, so a near-constant day reads as calm rather than as a zig-zag.
    function fitRange(first) {
        if (!hours.length)
            return
        var a = Math.max(0, first - 1)
        var b = Math.min(hours.length, first + hoursVisible + 2)
        var lo = Infinity, hi = -Infinity
        for (var i = a; i < b; i++) {
            lo = Math.min(lo, hours[i].temp)
            hi = Math.max(hi, hours[i].temp)
        }
        var span = Math.max(5, hi - lo + 2)
        var mid = (lo + hi) / 2
        tMin = mid - span / 2
        tMax = mid + span / 2
    }

    // Glide to an hour. The scale is fitted to the destination before the glide starts, so
    // the curve settles into its new shape on the way rather than jumping on arrival.
    function scrollToHour(index) {
        var maxX = Math.max(0, hours.length * colW - list.width)
        scrollAnim.to = Math.max(0, Math.min(maxX, index * colW))
        fitRange(Math.round(scrollAnim.to / colW))
        scrollAnim.restart()
    }

    onHoursChanged: Qt.callLater(updateRange)
    onWidthChanged: Qt.callLater(updateRange)

    ListView {
        id: list
        anchors.fill: parent
        orientation: ListView.Horizontal
        model: root.hours
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        snapMode: ListView.SnapToItem
        // Keep a screen's worth of delegates either side ready, so a flick never shows
        // hours being built.
        cacheBuffer: Math.max(0, root.width)

        onMovementStarted: root.userScrolled()
        onMovementEnded: root.updateRange()

        NumberAnimation on contentX {
            id: scrollAnim
            running: false
            duration: 450
            easing.type: Easing.OutCubic
        }

        delegate: Item {
            id: col
            required property int index
            required property var modelData
            readonly property var prev: index > 0 ? root.hours[index - 1] : modelData
            readonly property var next: index < root.hours.length - 1 ? root.hours[index + 1] : modelData
            // On whole clock steps (00, 02, …) so a day reads the same wherever it scrolls
            // to, plus "now"; the hour after "now" gives way if both would be labelled.
            readonly property bool labelled: index === 0
                || (modelData.hour % root.labelEvery === 0 && !(index === 1 && root.hours[0].hour % root.labelEvery !== 0))
            width: root.colW
            height: root.height

            // Rain, with its amount on top. The outline keeps the figure readable where the
            // temperature curve dips into the bars.
            Rectangle {
                x: 2
                width: parent.width - 4
                y: root.barBase - height
                height: root.barH(col.modelData.precip)
                color: "#4aa8ff"
            }
            Text {
                visible: col.modelData.precip > 0
                anchors.horizontalCenter: parent.horizontalCenter
                y: root.barBase - root.barH(col.modelData.precip) - height
                text: U.num(col.modelData.precip, 1)
                color: "#9dd0ff"
                style: Text.Outline
                styleColor: "#0b0e12"
                font.family: Theme.fontFamily
                font.pixelSize: 11
            }

            // Midnight: a rule and the new day's name.
            Rectangle {
                visible: col.modelData.hour === 0
                y: 30
                width: 1
                height: parent.height - 30
                color: "#29ffffff"
            }
            Text {
                visible: col.modelData.hour === 0
                x: 5; y: 34
                text: col.modelData.wd + " " + col.modelData.date
                color: "#b8c2cc"
                font.family: Theme.fontFamily
                font.pixelSize: 12
            }

            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: U.tempColor(col.modelData.temp)
                    strokeWidth: 3
                    fillColor: "transparent"
                    capStyle: ShapePath.FlatCap
                    startX: col.index === 0 ? root.colW / 2 : 0
                    startY: root.yAt(col.index === 0 ? col.modelData.temp : (col.prev.temp + col.modelData.temp) / 2)
                    PathQuad {
                        controlX: root.colW / 2
                        controlY: root.yAt(col.modelData.temp)
                        x: root.colW
                        y: root.yAt((col.modelData.temp + col.next.temp) / 2)
                    }
                }
            }

            // Now.
            Rectangle {
                visible: col.index === 0
                x: root.colW / 2 - 4
                y: root.yAt(col.modelData.temp) - 4
                width: 8; height: 8; radius: 4
                color: "white"
            }

            Image {
                visible: col.labelled
                anchors.horizontalCenter: parent.horizontalCenter
                y: 0
                width: 30; height: 30
                sourceSize: Qt.size(60, 60)
                source: col.labelled ? U.icon(col.modelData.symbol) : ""
            }
            Text {
                visible: col.labelled
                anchors.horizontalCenter: parent.horizontalCenter
                y: Math.max(32, root.yAt(col.modelData.temp) - 22)
                text: U.temp(col.modelData.temp)
                color: "white"
                font.family: Theme.fontFamily
                font.pixelSize: 14
            }
            Text {
                visible: col.labelled
                anchors.horizontalCenter: parent.horizontalCenter
                y: root.barBase + 3
                text: col.index === 0 ? qsTr("nyt") : U.hour2(col.modelData.hour)
                color: col.index === 0 ? "white" : "#8f9aa6"
                font.family: Theme.fontFamily
                font.pixelSize: 12
            }
        }
    }
}

import QtQuick
import frontend_v2

// An on/off switch whose knob STRETCHES across: on a change its leading edge
// runs to the far end first, so for a moment the knob is a pill spanning the
// track, then its tail follows and it is a circle again.
//
// Driven by a value rather than owning one: `checked` comes in, `toggled()`
// goes out, and the caller writes wherever the value lives (Settings, a model,
// a vehicle command). The animation runs whenever `checked` changes, whoever
// changed it — but never at construction, so a switch built already on does
// not sweep across as its view appears.
//
// Hand-drawn rather than a styled Qt Quick Controls Switch: the Basic style's
// indicator is small for a 10" finger target and its palette fights the dark
// theme. Size it with trackWidth / trackHeight; the touch target can reach past
// the visual with touchMargin.
Item {
    id: toggle

    property bool checked: false
    signal toggled()

    property int trackWidth: 52
    property int trackHeight: 28
    // Gap between the knob and the track's edge.
    property int inset: 3
    // How far the press area reaches beyond the drawn switch, for a small one.
    property int touchMargin: 0

    readonly property real knobSize: trackHeight - 2 * inset
    readonly property real offStart: inset
    readonly property real onStart: trackWidth - inset - knobSize

    // The knob's two edges in track coordinates. At rest they are knobSize
    // apart; mid-change the edge in the direction of travel leads.
    property real leftEdge: 0
    property real rightEdge: 0

    implicitWidth: trackWidth + 4
    implicitHeight: trackHeight + 2

    function snap() {
        travel.stop()
        leftEdge = checked ? onStart : offStart
        rightEdge = leftEdge + knobSize
    }

    // Starts from wherever the edges are, so a second tap mid-change turns the
    // knob around instead of jumping it to a rest position first.
    function animate() {
        travel.stop()
        if (checked) {
            lead.property = "rightEdge"
            lead.to = onStart + knobSize
            tail.property = "leftEdge"
            tail.to = onStart
        } else {
            lead.property = "leftEdge"
            lead.to = offStart
            tail.property = "rightEdge"
            tail.to = offStart + knobSize
        }
        travel.start()
    }

    onCheckedChanged: animate()
    Component.onCompleted: snap()
    // A size change mid-life (a binding settling) re-seats the knob.
    onKnobSizeChanged: snap()
    onTrackWidthChanged: snap()

    SequentialAnimation {
        id: travel

        NumberAnimation {
            id: lead
            target: toggle
            duration: Theme.switchStretchDuration
            easing.type: Easing.OutCubic
        }
        NumberAnimation {
            id: tail
            target: toggle
            duration: Theme.switchSettleDuration
            easing.type: Easing.OutCubic
        }
    }

    Rectangle {
        id: track
        anchors.centerIn: parent
        width: toggle.trackWidth
        height: toggle.trackHeight
        radius: height / 2
        color: toggle.checked ? Theme.accent : Theme.tripComboBg
        border.width: 1
        border.color: toggle.checked ? Theme.accent : Theme.tripCardBorder

        // Timed with the leading edge: the colour has changed by the time the
        // knob reaches the far end.
        Behavior on color {
            ColorAnimation { duration: Theme.switchStretchDuration }
        }
        Behavior on border.color {
            ColorAnimation { duration: Theme.switchStretchDuration }
        }

        Rectangle {
            x: toggle.leftEdge
            width: toggle.rightEdge - toggle.leftEdge
            height: toggle.knobSize
            radius: height / 2
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.dataLabelValue
        }
    }

    MouseArea {
        anchors.fill: parent
        anchors.margins: -toggle.touchMargin
        onClicked: toggle.toggled()
    }
}

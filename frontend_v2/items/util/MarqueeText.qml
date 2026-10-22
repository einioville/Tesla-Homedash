import QtQuick
import QtQuick.Effects
import frontend_v2

// One line of text that, when it is wider than the item, rests at its start with
// the cut end faded out and every marqueeRestDuration scrolls once round — a copy
// follows a gap behind, so the loop ends where it began. Text that fits stands
// still at `horizontalAlignment`. The pause is a Timer and only the scroll an
// animation, so a resting title costs no frames (frontend_v2/CLAUDE.md, *Motion
// that keeps running*).
Item {
    id: root

    property alias text: label.text
    property alias color: label.color
    property alias font: label.font
    property alias horizontalAlignment: label.horizontalAlignment
    // Scrolls only while true (the owning view is current, the music playing); a
    // scroll under way still finishes.
    property bool active: true

    readonly property bool overflowing: label.implicitWidth > width
    // Sized by the line's height, so a large title and a small one read at the
    // same pace.
    readonly property real fadeWidth: label.height
    readonly property real gap: label.height * 2
    readonly property real loopLength: label.implicitWidth + gap

    // How far the line has scrolled, 0 … loopLength.
    property real offset: 0

    implicitHeight: label.implicitHeight

    onTextChanged: {
        scroll.stop()
        offset = 0
        rest.restart()
    }

    Timer {
        id: rest
        interval: Theme.marqueeRestDuration
        running: root.overflowing && root.active && root.visible && !scroll.running
        onTriggered: scroll.start()
    }

    NumberAnimation {
        id: scroll
        target: root
        property: "offset"
        from: 0
        to: root.loopLength
        duration: root.loopLength / (label.height * Theme.marqueeSpeed) * 1000
        onFinished: root.offset = 0
    }

    Item {
        id: strip
        anchors.fill: parent
        clip: true
        layer.enabled: root.overflowing
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: fadeMask
            // smoothstep(0, 1) over the mask's alpha (see RoundedImage).
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
        }

        Row {
            x: -root.offset
            spacing: root.gap

            Text {
                id: label
                width: root.overflowing ? implicitWidth : root.width
            }
            Text {
                visible: root.overflowing
                text: label.text
                color: label.color
                font: label.font
            }
        }
    }

    // The far end is always faded; the near one fades in as the line leaves its
    // start and out again as the copy comes in.
    Item {
        id: fadeMask
        anchors.fill: parent
        visible: false
        layer.enabled: true

        readonly property real edge: Math.min(1, root.fadeWidth / Math.max(1, width))
        readonly property real nearAlpha:
            1 - Math.min(1, Math.min(root.offset, root.loopLength - root.offset) / root.fadeWidth)

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: Qt.rgba(1, 1, 1, fadeMask.nearAlpha) }
                GradientStop { position: fadeMask.edge; color: "white" }
                GradientStop { position: 1 - fadeMask.edge; color: "white" }
                GradientStop { position: 1; color: "transparent" }
            }
        }
    }
}

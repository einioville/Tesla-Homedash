import QtQuick
import frontend_v2

// Scrubbable progress bar + elapsed/remaining time, with the smooth local
// progress logic shared by the dashboard card and the fullscreen view: re-synced
// on every server update, advanced 1 s at a time while playing, frozen while the
// user drags. The whole bar is the hit target (press or drag anywhere seeks).
// Gate the 1 s ticker by binding `active` to the owning view's isCurrent so a
// hidden view doesn't tick.
Item {
    id: root

    property bool active: true
    property int barHeight: 4
    property int handleSize: 12
    property int fontPointSize: 8

    // Smooth local progress, re-synced to the server unless the user is scrubbing.
    property int liveProgress: 0
    property bool scrubbing: false

    implicitHeight: seekBar.height + 2 + timeRow.height

    function msToClock(ms) {
        var total = Math.max(0, Math.floor(ms / 1000))
        var minutes = Math.floor(total / 60)
        var seconds = total % 60
        return minutes + ":" + (seconds < 10 ? "0" : "") + seconds
    }

    Connections {
        target: Media
        // A progress poll landing mid-drag would jump the bar from under the
        // finger, so ignore server syncs while scrubbing.
        function onProgressMsChanged() {
            if (!root.scrubbing)
                root.liveProgress = Media.progressMs
        }
    }

    Timer {
        interval: 1000
        repeat: true
        running: root.active && Media.mediaType === 2 && Media.isPlaying && !root.scrubbing
        onTriggered: root.liveProgress += 1000
    }

    Item {
        id: seekBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Math.max(root.handleSize, root.barHeight) + 6

        readonly property int duration: Math.max(1, Media.durationMs)
        readonly property real fraction: Math.max(0, Math.min(1, root.liveProgress / duration))

        Rectangle {
            id: groove
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            height: root.barHeight
            radius: height / 2
            color: Theme.sliderGroove

            Rectangle {
                width: seekBar.fraction * parent.width
                height: parent.height
                radius: height / 2
                color: Theme.sliderFill
            }
        }

        Rectangle {
            width: root.handleSize
            height: root.handleSize
            radius: width / 2
            color: Theme.sliderFill
            anchors.verticalCenter: parent.verticalCenter
            x: seekBar.fraction * (seekBar.width - width)
        }

        MouseArea {
            anchors.fill: parent
            function msAt(mx) {
                var f = Math.max(0, Math.min(1, mx / width))
                return Math.round(f * seekBar.duration)
            }
            onPressed: (mouse) => {
                root.scrubbing = true
                root.liveProgress = msAt(mouse.x)
            }
            onPositionChanged: (mouse) => {
                if (root.scrubbing)
                    root.liveProgress = msAt(mouse.x)
            }
            onReleased: (mouse) => {
                root.liveProgress = msAt(mouse.x)
                Media.setProgress(root.liveProgress)
                root.scrubbing = false
            }
            onCanceled: root.scrubbing = false
        }
    }

    Item {
        id: timeRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: seekBar.bottom
        anchors.topMargin: 2
        height: elapsed.implicitHeight

        Text {
            id: elapsed
            anchors.left: parent.left
            text: root.msToClock(root.liveProgress)
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pointSize: root.fontPointSize
        }
        Text {
            anchors.right: parent.right
            text: root.msToClock(Media.durationMs)
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pointSize: root.fontPointSize
        }
    }
}

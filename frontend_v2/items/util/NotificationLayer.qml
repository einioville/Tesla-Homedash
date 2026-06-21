import QtQuick
import QtQuick.Effects
import frontend_v2

// Smartphone-style notification overlay — a util feature alongside the dock.
// Listens to the NotificationHandler singleton and slides each notification down
// from the top centre in a frosted "liquid glass" pill (GlassPanel), holds it for
// the grace period, then slides it back up. Several arriving in quick succession
// are queued and shown one at a time. Backend is not involved.
Item {
    id: layer
    anchors.fill: parent

    // The item rendered BEHIND the pill (the dashboard host), captured + blurred
    // for the frosted-glass backdrop. Set from Main.qml; flip frostedBackdrop off
    // if the live capture is too heavy on the target device.
    property Item backdropSource: null
    property bool frostedBackdrop: true

    // Mirror of the dock's bottom inset, applied to the top instead.
    readonly property int topInset: 18
    readonly property int slideMs: 320
    readonly property int graceMs: Notifications.graceMs

    // Pending messages and the one currently on screen.
    property var queue: []
    property string currentMessage: ""
    property bool showing: false

    function __advance() {
        if (layer.queue.length === 0) {
            layer.showing = false
            return
        }
        layer.currentMessage = layer.queue.shift()
        layer.showing = true
        graceTimer.restart()
    }

    Connections {
        target: Notifications
        function onNotify(id, message) {
            layer.queue.push(message)
            // Kick the pipeline only when idle (not mid-show, not mid-gap).
            if (!layer.showing && !gapTimer.running)
                layer.__advance()
        }
    }

    // Hold the current notification, then slide it out.
    Timer {
        id: graceTimer
        interval: layer.graceMs
        onTriggered: {
            layer.showing = false
            gapTimer.restart()
        }
    }

    // Brief gap covering the slide-out before the next notification slides in.
    Timer {
        id: gapTimer
        interval: layer.slideMs + 40
        onTriggered: layer.__advance()
    }

    // Soft drop shadow so the pill floats above the dashboard (tracks the pill).
    RectangularShadow {
        anchors.fill: pill
        radius: Theme.notificationRadius
        blur: 28
        spread: 0
        offset: Qt.vector2d(0, 6)
        color: Theme.notificationShadow
    }

    GlassPanel {
        id: pill
        anchors.horizontalCenter: parent.horizontalCenter
        // Off-screen above when hidden; the dock's bottom padding, mirrored, when shown.
        y: layer.showing ? layer.topInset : -(height + 24)
        implicitWidth: pillLabel.implicitWidth + 2 * Theme.dockPadding
        implicitHeight: pillLabel.implicitHeight + 2 * Theme.dockPadding
        radius: Theme.notificationRadius

        backdropSource: layer.backdropSource
        frostedBackdrop: layer.frostedBackdrop
        // The pill is a direct child of this layer (which fills the window), so
        // its x/y are already the backdrop's coordinates.
        backdropOrigin: Qt.point(pill.x, pill.y)
        active: layer.showing

        Behavior on y {
            NumberAnimation { duration: layer.slideMs; easing.type: Easing.OutCubic }
        }

        Text {
            id: pillLabel
            anchors.centerIn: parent
            text: layer.currentMessage
            color: Theme.notificationText
            font.family: Theme.fontFamily
            font.pointSize: 14
        }
    }
}

import QtQuick
import QtLocation
import QtPositioning

Item {
    id: root
    objectName: "root"

    property real latitude: 61.497063
    property real longitude: 23.750078
    property real rotation: 32

    // True while the user is interacting with the map or within the idle
    // window after they let go. Auto-follow is suspended in this state.
    property bool userControlled: false
    // Idle period (ms) after the last gesture before snapping back to the car.
    property int idleReturnMs: 10000
    // Default zoom restored on auto-return.
    property real defaultZoom: 15

    Behavior on latitude {
        NumberAnimation {
            duration: 999; easing.type: Easing.Linear
        }
    }
    Behavior on longitude {
        NumberAnimation {
            duration: 999; easing.type: Easing.Linear
        }
    }

    Behavior on rotation {
        RotationAnimation {
            duration: 999
            easing.type: Easing.Linear
            direction: RotationAnimation.Shortest
        }
    }

    // Single place that arbitrates gesture transitions for both handlers.
    function handleGestureActive(active) {
        if (active) {
            userControlled = true
            returnTimer.stop()
            returnAnim.stop()
        } else {
            returnTimer.restart()
        }
    }

    Timer {
        id: returnTimer
        interval: root.idleReturnMs
        repeat: false
        onTriggered: returnAnim.start()
    }

    // Explicit animation for the snap-back. Avoided putting a Behavior on
    // map.center because every telemetry tick re-writes center via the
    // Binding below — chained Behaviors would lag the marker.
    ParallelAnimation {
        id: returnAnim
        CoordinateAnimation {
            target: map
            property: "center"
            to: QtPositioning.coordinate(root.latitude, root.longitude)
            duration: 600
            easing.type: Easing.InOutQuad
        }
        NumberAnimation {
            target: map
            property: "zoomLevel"
            to: root.defaultZoom
            duration: 400
            easing.type: Easing.InOutQuad
        }
        onStopped: {
            // Re-engage auto-follow only if no new gesture started during
            // the animation.
            if (!panHandler.active && !pinchHandler.active) {
                root.userControlled = false
            }
        }
    }

    Plugin {
        id: osmPlugin
        name: "osm"

        PluginParameter {
            name: "osm.useragent"
            value: "Tesla-Homedash/1.0"
        }
        PluginParameter {
            name: "osm.mapping.host"
            value: "https://tile.openstreetmap.org/"
        }
    }

    Map {
        id: map
        objectName: "map"

        anchors.fill: parent
        plugin: osmPlugin

        zoomLevel: root.defaultZoom
        bearing: 0
        activeMapType: map.supportedMapTypes[7]

        center: QtPositioning.coordinate(root.latitude, root.longitude)

        // One-finger pan. target: null = handler observes gestures without
        // moving any QML item; we apply the delta to map.center ourselves.
        DragHandler {
            id: panHandler
            target: null
            minimumPointCount: 1
            maximumPointCount: 1

            property point lastCentroid

            onActiveChanged: {
                root.handleGestureActive(active)
                if (active) lastCentroid = centroid.position
            }
            onCentroidChanged: {
                if (!active) return
                map.pan(lastCentroid.x - centroid.position.x,
                        lastCentroid.y - centroid.position.y)
                lastCentroid = centroid.position
            }
        }

        // Mouse / touchpad wheel zoom (PC dev convenience). Each notch is
        // a discrete event, so we run the full activate->deactivate sequence
        // per tick to refresh the idle timer.
        WheelHandler {
            id: wheelHandler
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: function(event) {
                root.handleGestureActive(true)
                map.zoomLevel += event.angleDelta.y / 120 * 0.5
                root.handleGestureActive(false)
            }
        }

        // Two-finger pinch zoom. log2(activeScale) so a 2x pinch = +1 zoom
        // level, matching the standard map zoom semantics.
        PinchHandler {
            id: pinchHandler
            target: null
            minimumPointCount: 2

            property real startZoom: root.defaultZoom

            onActiveChanged: {
                root.handleGestureActive(active)
                if (active) startZoom = map.zoomLevel
            }
            onActiveScaleChanged: {
                if (!active) return
                map.zoomLevel = startZoom + Math.log2(activeScale)
            }
        }

        MapQuickItem {
            id: vehicle
            objectName: "vehicle"

            coordinate: QtPositioning.coordinate(root.latitude, root.longitude)
            rotation: root.rotation

            sourceItem: Image {
                id: vehicleIcon
                source: "qrc:/resources/icons/arrow.svg"
                width: 24
                height: 24
                smooth: true
                antialiasing: true
            }

            anchorPoint.x: vehicleIcon.width / 2
            anchorPoint.y: vehicleIcon.height / 2
        }
    }

    // Steady-state follow: while not under user control, force center to
    // track telemetry. RestoreNone lets the user's last-set center stand
    // when the binding deactivates (gesture begins).
    Binding {
        target: map
        property: "center"
        value: QtPositioning.coordinate(root.latitude, root.longitude)
        when: !root.userControlled
        restoreMode: Binding.RestoreNone
    }
}

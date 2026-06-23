import QtQuick
import QtLocation
import QtPositioning
import frontend_v2

// OSM map that follows the car — the QML port of the Widgets map.qml. Position
// and heading bind to the Tesla singleton (Location map + GpsHeading); pan /
// pinch / wheel gestures suspend auto-follow for a 10 s idle window, then the
// view snaps back to the car. Corners are rounded to match the card radius.
// (Heading is named `heading`, not `rotation`, to avoid shadowing Item.rotation
// and tilting the whole map.)
Item {
    id: root

    property real latitude: (Tesla.location && Tesla.location.latitude !== undefined)
                            ? Tesla.location.latitude : 61.497063
    property real longitude: (Tesla.location && Tesla.location.longitude !== undefined)
                             ? Tesla.location.longitude : 23.750078
    property real heading: Tesla.gpsHeading

    // True while the user interacts (or within the idle window after). Auto-
    // follow is suspended in this state.
    property bool userControlled: false
    property int idleReturnMs: 10000
    property real defaultZoom: 15

    // Frozen while the owning view is hidden. The dashboard keeps this map alive in
    // memory (so returning is instant — no tile reload), but a hidden map must not
    // animate or re-center on every telemetry tick. DashboardView binds this to its
    // isCurrent; the follow animations and the center binding below gate on it.
    // Leaving also cancels any in-flight snap-back and drops back to follow mode so
    // the car is re-centered on return.
    property bool isCurrent: true
    onIsCurrentChanged: if (!isCurrent) {
        returnTimer.stop()
        returnAnim.stop()
        userControlled = false
    }

    Behavior on latitude { enabled: root.isCurrent; NumberAnimation { duration: 999; easing.type: Easing.Linear } }
    Behavior on longitude { enabled: root.isCurrent; NumberAnimation { duration: 999; easing.type: Easing.Linear } }
    Behavior on heading {
        enabled: root.isCurrent
        RotationAnimation { duration: 999; easing.type: Easing.Linear; direction: RotationAnimation.Shortest }
    }

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

    // Explicit snap-back; a Behavior on map.center would lag against the
    // per-tick center binding below.
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
            if (!panHandler.active && !pinchHandler.active) {
                root.userControlled = false
            }
        }
    }

    Plugin {
        id: osmPlugin
        name: "osm"

        PluginParameter { name: "osm.useragent"; value: "Tesla-Homedash/1.0" }

        // We only use the custom tile host below, so skip fetching the remote
        // provider repository (maps-redirect.qt.io) for the built-in map types.
        // That drops a startup network dependency and silences the "Tileserver
        // disabled …/satellite" warning plus the HTTP/2 stream errors from that
        // fetch. The hardcoded built-ins it falls back to are unused; CustomMap is
        // created from osm.mapping.host independently, so it's unaffected.
        PluginParameter { name: "osm.mapping.providersrepository.disabled"; value: true }

        // Custom tile host = our satellite/aerial basemap (the MapType.CustomMap
        // type). The URL + attribution come from AppConfig (the App singleton),
        // which serves MML's 0.5 m orthophoto when a TESLA_HOMEDASH_MAP_API_KEY is
        // configured (env or .env) and the keyless EOX Sentinel-2 fallback
        // otherwise — so the api-key never lives in this committed file. The OSM
        // plugin substitutes %x/%y/%z positionally, so the z/y/x providers use a
        // %z/%y/%x template; tiles are EPSG:3857 Web Mercator.
        PluginParameter { name: "osm.mapping.host"; value: App.mapTilesUrl }
        PluginParameter { name: "osm.mapping.custom.mapcopyright"; value: App.mapAttribution }
    }

    Map {
        id: map
        objectName: "map"

        anchors.fill: parent
        plugin: osmPlugin

        zoomLevel: root.defaultZoom
        bearing: 0

        // Hide the on-map provider attribution for a cleaner dashboard. The text
        // is still configured (osm.mapping.custom.mapcopyright above), so flip
        // this to true to restore the "© Maanmittauslaitos" / Sentinel-2 credit.
        // Note: MML (CC BY 4.0) and EOX/Copernicus licenses request attribution.
        copyrightsVisible: false

        center: QtPositioning.coordinate(root.latitude, root.longitude)

        // Imagery comes in via the custom tile host (osm.mapping.host) as the
        // MapType.CustomMap entry. supportedMapTypes loads asynchronously and its
        // length/order depend on which OSM providers are live (the built-in
        // "satellite" is currently reported disabled), so a fixed index is
        // fragile — select CustomMap by style instead. (The old
        // supportedMapTypes[7] binding went undefined when satellite dropped out,
        // which is what logged "Unable to assign [undefined] to QGeoMapType".)
        function selectCustomMapType() {
            for (var i = 0; i < supportedMapTypes.length; i++) {
                if (supportedMapTypes[i].style === MapType.CustomMap) {
                    activeMapType = supportedMapTypes[i]
                    return
                }
            }
        }

        Component.onCompleted: selectCustomMapType()
        onSupportedMapTypesChanged: selectCustomMapType()

        DragHandler {
            id: panHandler
            target: null
            minimumPointCount: 1
            maximumPointCount: 1
            // No dead-zone: track the finger from the first pixel. The default
            // ~10px threshold made the map sit still at the start of a drag (the
            // finger moves but the map doesn't until the threshold is crossed),
            // which reads as a brief freeze.
            dragThreshold: 0

            property point lastCentroid
            // Becomes true on the first real movement of a press. Because
            // threshold is 0, a bare tap also activates the handler; gating the
            // follow-suspend on actual movement keeps a tap from freezing the
            // car-follow for idleReturnMs.
            property bool panning: false

            onActiveChanged: {
                if (active) {
                    lastCentroid = centroid.position
                    panning = false
                } else if (panning) {
                    panning = false
                    root.handleGestureActive(false)  // re-arm idle auto-return
                }
            }
            // Pan in the map's coordinate space rather than via map.pan(pixels):
            // project the previous and current cursor pixels to geo-coordinates
            // under the current projection and shift center by their difference.
            // This keeps the grabbed point exactly under the cursor at 1:1 on any
            // device-pixel-ratio (map.pan's pixel delta trails the pointer on
            // HiDPI/scaled displays).
            onCentroidChanged: {
                if (!active) return
                if (!panning) {
                    panning = true
                    root.handleGestureActive(true)  // first move: suspend follow
                }
                var from = map.toCoordinate(lastCentroid, false)
                var to = map.toCoordinate(centroid.position, false)
                map.center = QtPositioning.coordinate(
                    map.center.latitude + (from.latitude - to.latitude),
                    map.center.longitude + (from.longitude - to.longitude))
                lastCentroid = centroid.position
            }
        }

        WheelHandler {
            id: wheelHandler
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: function(event) {
                root.handleGestureActive(true)
                map.zoomLevel += event.angleDelta.y / 120 * 0.5
                root.handleGestureActive(false)
            }
        }

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
            rotation: root.heading

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

    // Steady-state follow: force center to track telemetry unless the user is
    // panning. RestoreNone keeps the user's last center when the gesture begins.
    Binding {
        target: map
        property: "center"
        value: QtPositioning.coordinate(root.latitude, root.longitude)
        when: !root.userControlled && root.isCurrent
        restoreMode: Binding.RestoreNone
    }

    // NOTE: the Widgets map applied a 5px rounded-corner mask. Routing the live,
    // interactive Map through a layer/MultiEffect mask to round it risks the
    // gesture handling and adds a per-frame texture copy, and 5px corners on the
    // dark OSM tiles against the #121212 background are imperceptible — so the
    // corners are left square here. Revisit if the rounding is wanted.
}

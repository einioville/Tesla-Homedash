import QtQuick
import QtQuick.Shapes
import QtLocation
import QtPositioning
import frontend_v2

// OSM map that follows the car — the QML port of the Widgets map.qml. Position
// and heading bind to the Tesla singleton (Location map + GpsHeading); pan /
// pinch / wheel gestures suspend auto-follow for an idle window, then the view
// snaps back to the car. Corners are rounded to match the card radius.
// (Heading is named `heading`, not `rotation`, to avoid shadowing Item.rotation
// and tilting the whole map.)
//
// Orientation and follow behaviour are user settings (Theme.map*, from the
// Options view's Datan visualisointi > Kartta card):
//   - orientation "north"   keeps north up and turns the car icon;
//     "heading" turns the MAP so the car always points up the screen.
//   - follow "lock"  pins the car to the exact centre (the Binding at the
//     bottom of this file); "warp" lets it roam inside an invisible centred
//     square and re-centres only when it escapes, parking it BEHIND centre so
//     the road ahead gets the larger share of the map.
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
    property int idleReturnMs: Theme.mapFollowResumeSec * 1000
    property real defaultZoom: Theme.mapDefaultZoom

    // Multiplier on every gesture. At 1.0 a drag is exact 1:1 (the grabbed point
    // stays under the finger); other values trade that away for reach.
    readonly property real sensitivity: Theme.mapSensitivity
    readonly property bool headingUp: Theme.mapOrientation === "heading"
    readonly property bool warpFollow: Theme.mapFollowMode === "warp"

    // Round the map's corners to match the dashboard cards. Disable for a
    // dedicated full-screen map view, where the map fills the surface and the
    // background-coloured corner overlay would have nothing to blend into.
    property bool roundedCorners: true

    // Frozen while the owning view is hidden. The dashboard keeps this map alive in
    // memory (so returning is instant — no tile reload), but a hidden map must not
    // animate or re-center on every telemetry tick. DashboardView binds this to its
    // isCurrent; the follow animations and the center binding below gate on it.
    // Leaving also cancels any in-flight snap-back and drops back to follow mode so
    // the car is re-centered on return.
    property bool isCurrent: true
    onIsCurrentChanged: {
        if (!isCurrent) {
            returnTimer.stop()
            returnAnim.stop()
            warpAnim.stop()
            userControlled = false
        } else {
            claimCenterForWarp()
            warpStep()
        }
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
            warpAnim.stop()
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
    // per-tick center binding below. Returns to the EXACT car position in both
    // follow modes: the zoom is animating back to defaultZoom at the same time,
    // so a lead offset computed at the old zoom would land wrong in geo terms.
    // Warp re-applies its offset by itself once the car next leaves the zone.
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

    // --- Warp follow ------------------------------------------------------
    // The dead-zone half-extent and the lead offset, in pixels. Both are a
    // fraction of the map's SHORTER side, so the free area stays square on any
    // card. The lead is CLAMPED below the dead zone, and that clamp is load-
    // bearing: the settings ranges allow a lead (up to 30 %) larger than a dead
    // zone (down to 5 %), and parking the car outside the very zone whose exit
    // triggers a re-centre would re-trigger on the next frame, forever.
    readonly property real warpDeadzonePx:
        Math.min(map.width, map.height) * Theme.mapWarpDeadzoneFrac
    readonly property real warpLeadPx:
        Math.min(Math.min(map.width, map.height) * Theme.mapWarpLeadFrac,
                 warpDeadzonePx * 0.8)

    CoordinateAnimation {
        id: warpAnim
        target: map
        property: "center"
        duration: 700
        easing.type: Easing.InOutQuad
    }

    // Pixel the car should occupy after a warp re-centre.
    function warpTargetPoint() {
        var cx = map.width / 2
        var cy = map.height / 2
        if (root.warpLeadPx <= 0)
            return Qt.point(cx, cy)
        // Angle of travel on SCREEN, clockwise from straight up. In heading-up
        // mode the map has already turned under the car, so this collapses to 0
        // and the car is simply parked below centre.
        var t = (root.heading - map.bearing) * Math.PI / 180
        // Travel direction on screen is (sin t, -cos t); the car goes the other
        // way by warpLeadPx, leaving the space ahead of it on screen.
        return Qt.point(cx - Math.sin(t) * root.warpLeadPx,
                        cy + Math.cos(t) * root.warpLeadPx)
    }

    // Where map.center must move for the car to land on `point`. The same "grab
    // a point and drag it" math the pan handler uses, so it stays correct under
    // any bearing. Returns null while the map cannot project.
    function warpCenterFor(point) {
        var at = map.toCoordinate(point, false)
        if (!at.isValid)
            return null
        return QtPositioning.coordinate(
            map.center.latitude + (root.latitude - at.latitude),
            map.center.longitude + (root.longitude - at.longitude))
    }

    // Warp mode must OWN map.center, but the Map's own `center:` binding tracks
    // the car exactly — which IS lock behaviour. Without dropping it here, warp
    // would look completely inert until some unrelated assignment (historically
    // the user's first pan) happened to break it. Assigning the current value
    // imperatively is what drops a QML binding.
    function claimCenterForWarp() {
        if (!root.warpFollow || !map.mapReady)
            return
        map.center = QtPositioning.coordinate(map.center.latitude,
                                              map.center.longitude)
    }

    // Re-centre if — and only if — the car has left the dead zone.
    function warpStep() {
        if (!root.warpFollow || !root.isCurrent || root.userControlled)
            return
        // The running-animation guard is what stops a 700 ms ease being
        // restarted on every one of the ~42 frames it spans.
        if (warpAnim.running || returnAnim.running)
            return
        if (!map.mapReady || map.width <= 0 || map.height <= 0)
            return

        var here = map.fromCoordinate(
            QtPositioning.coordinate(root.latitude, root.longitude), false)
        var cx = map.width / 2
        var cy = map.height / 2
        var dx = here.x - cx
        var dy = here.y - cy
        if (Math.abs(dx) <= root.warpDeadzonePx && Math.abs(dy) <= root.warpDeadzonePx)
            return   // inside the square: hold still and let the car glide

        var to = warpCenterFor(warpTargetPoint())
        if (to === null)
            return
        // A first fix, a reconnect or a telemetry jump can be arbitrarily far
        // away, and easing across half of Finland is a 700 ms blur — snap
        // anything beyond one viewport instead.
        if (Math.abs(dx) > map.width || Math.abs(dy) > map.height) {
            map.center = to
            return
        }
        warpAnim.to = to
        warpAnim.restart()
    }

    // Position ticks arrive smoothed by the Behaviors above, so these fire per
    // frame while the car moves; warpStep is a bounds check and an early return
    // in the common case. Heading changes deliberately do NOT trigger a step —
    // a bend would otherwise re-centre continuously — and need not, since a
    // turning car is also a moving one.
    onLatitudeChanged: warpStep()
    onLongitudeChanged: warpStep()
    // Switching mode, or finishing a gesture, needs one evaluation that no
    // position change would otherwise provide.
    // Stopping the animation first matters: leaving warp re-arms the lock
    // Binding below, and an in-flight warp would then fight it for map.center
    // until it happened to finish.
    onWarpFollowChanged: {
        if (!warpFollow)
            warpAnim.stop()
        claimCenterForWarp()
        warpStep()
    }
    onUserControlledChanged: warpStep()

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

        // Turning the map under the car. Verified against the Qt 6.11.1 sources:
        // the OSM geoservice plugin declares setSupportsBearing(true), without
        // which QDeclarativeGeoMap would accept this property and silently
        // ignore it. `heading` is already smoothed by the Behavior above, so the
        // rotation eases for free and needs no Behavior of its own (one here
        // would re-trigger on every frame of that animation and only add lag).
        // Left ungated by isCurrent: a camera update on a map nobody is
        // rendering is cheap, and it means returning to the view finds the
        // bearing already correct rather than spinning into place.
        bearing: root.headingUp ? root.heading : 0

        // Hide the on-map provider attribution for a cleaner dashboard. The text
        // is still configured (osm.mapping.custom.mapcopyright above), so flip
        // this to true to restore the "© Maanmittauslaitos" / Sentinel-2 credit.
        // Note: MML (CC BY 4.0) and EOX/Copernicus licenses request attribution.
        copyrightsVisible: false

        // Lock mode's steady-state follow is the Binding at the bottom of this
        // file; this binding covers startup (and survives until something
        // assigns center imperatively). Warp mode drops it deliberately — see
        // claimCenterForWarp.
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
        // Projection is unavailable until the map is ready, so warp can only
        // take ownership of the centre from here.
        onMapReadyChanged: if (mapReady) { root.claimCenterForWarp(); root.warpStep() }

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
            // HiDPI/scaled displays) — and, because it goes through the
            // projection, stays correct while the map is rotated. Sensitivity
            // scales that delta, so only the default 1.0 is truly 1:1.
            onCentroidChanged: {
                if (!active) return
                if (!panning) {
                    panning = true
                    root.handleGestureActive(true)  // first move: suspend follow
                }
                var from = map.toCoordinate(lastCentroid, false)
                var to = map.toCoordinate(centroid.position, false)
                map.center = QtPositioning.coordinate(
                    map.center.latitude + (from.latitude - to.latitude) * root.sensitivity,
                    map.center.longitude + (from.longitude - to.longitude) * root.sensitivity)
                lastCentroid = centroid.position
            }
        }

        WheelHandler {
            id: wheelHandler
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: function(event) {
                root.handleGestureActive(true)
                map.zoomLevel += event.angleDelta.y / 120 * 0.5 * root.sensitivity
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
                map.zoomLevel = startZoom + Math.log2(activeScale) * root.sensitivity
            }
        }

        MapQuickItem {
            id: vehicle
            objectName: "vehicle"

            coordinate: QtPositioning.coordinate(root.latitude, root.longitude)
            // MapQuickItem renders SCREEN-ALIGNED while its own zoomLevel is
            // unset (updatePolish applies an identity matrix on that branch), so
            // this rotation does not follow the map's bearing. Subtracting the
            // bearing therefore keeps the arrow pointing at the true heading in
            // both modes: it equals `heading` at bearing 0 (north-up, the
            // original behaviour) and ~0 in heading-up, where the map itself has
            // turned. A 360° difference renders identically, so no wrapping is
            // needed around the sanitized [0,360) bearing.
            rotation: root.heading - map.bearing

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

    // Steady-state follow for LOCK mode: force center to track telemetry unless
    // the user is panning. RestoreNone keeps the user's last center when the
    // gesture begins. Warp mode excludes itself here and drives center from
    // warpStep instead — the two must never both own map.center.
    Binding {
        target: map
        property: "center"
        value: QtPositioning.coordinate(root.latitude, root.longitude)
        when: !root.userControlled && root.isCurrent && !root.warpFollow
        restoreMode: Binding.RestoreNone
    }

    // Rounded corners without masking the live map. The Widgets frontend clipped
    // the map with a rounded-rect mask, but routing this constantly-repainting,
    // interactive Map through a layer/MultiEffect mask would force a full-surface
    // FBO texture copy every frame. Instead we paint the surrounding background
    // back over the four corners: an odd-even Shape fills everything EXCEPT a
    // rounded interior, leaving only the corner slivers covered. This works
    // because the map sits on a solid Theme.dashboardBackground, costs nothing
    // per frame, and — having no input handlers — lets pan/pinch/wheel gestures
    // fall straight through to the Map underneath. Gated on roundedCorners so a
    // full-screen map view can drop the overlay entirely.
    Shape {
        anchors.fill: parent
        visible: root.roundedCorners
        preferredRendererType: Shape.CurveRenderer
        z: 10

        ShapePath {
            fillRule: ShapePath.OddEvenFill
            strokeWidth: 0
            strokeColor: "transparent"
            fillColor: Theme.dashboardBackground
            PathRectangle { width: root.width; height: root.height; radius: 0 }
            PathRectangle { width: root.width; height: root.height; radius: Theme.cardRadius }
        }
    }
}

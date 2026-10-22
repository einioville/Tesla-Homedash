import QtQuick
import QtLocation
import QtPositioning
import frontend_v2

// Trips-view map: a free-pan/zoom OSM map (no car-follow) that draws the selected
// trip's GPS path coloured by speed (Trips.route, SpeedRoute — the Kartta view's drive,
// with a dark casing under it), over the OSM place names and under the home and the
// start / end pins. The map fits its viewport to the route when one arrives.
Item {
    id: root

    // Clip so the inspect-arrow overlay (a plain Image projected from a geo-coordinate)
    // can never paint outside the map card and over the neighbouring view items when the
    // inspected fix sits off the current viewport. The Map fills root exactly, so
    // clipping it is a no-op.
    clip: true

    property bool isCurrent: true
    property real defaultZoom: 12

    // Graph-inspect mirror: while the user hovers the speed graph, show a heading arrow
    // at the route position for the inspected time. Bound by TripsView.
    property bool inspecting: false
    property real inspectTime: 0
    // The inspected { lat, lon, bearing } (or null), recomputed as the cursor moves;
    // Trips.hasRoute is what makes it follow a new route (positionAt binds to nothing).
    property var inspectPoint: (inspecting && Trips.hasRoute)
                               ? Trips.route.positionAt(inspectTime) : null

    BasemapPlugin {
        id: osmPlugin
    }

    Map {
        id: map
        anchors.fill: parent
        plugin: osmPlugin
        // QTBUG-62463/67169: hovering a popup/menu over a Map re-batches the scene and
        // mis-batches the tile quads — random tiles draw as solid white. Opacity < 1
        // forces the map subtree through the alpha pass, keeping its batching consistent.
        opacity: 0.99
        copyrightsVisible: false
        zoomLevel: root.defaultZoom
        bearing: 0
        center: QtPositioning.coordinate(61.497063, 23.750078)

        // A route that arrived before the map could project is fitted once it can.
        onMapReadyChanged: if (mapReady) root.fitToRoute()

        // Free pan (1:1 in map coordinates, DPR-correct — see TeslaMap), scaled
        // by the shared map gesture sensitivity so this map and the car map feel
        // the same under a finger. Only the default 1.0 is truly 1:1.
        DragHandler {
            id: panHandler
            target: null
            minimumPointCount: 1
            maximumPointCount: 1
            dragThreshold: 0
            property point lastCentroid
            onActiveChanged: if (active) { lastCentroid = centroid.position; followAnim.stop() }
            onCentroidChanged: {
                if (!active)
                    return
                var from = map.toCoordinate(lastCentroid, false)
                var to = map.toCoordinate(centroid.position, false)
                map.center = QtPositioning.coordinate(
                    map.center.latitude + (from.latitude - to.latitude) * Theme.mapSensitivity,
                    map.center.longitude + (from.longitude - to.longitude) * Theme.mapSensitivity)
                lastCentroid = centroid.position
            }
        }

        WheelHandler {
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: function(event) {
                followAnim.stop()
                map.zoomLevel += event.angleDelta.y / 120 * 0.5 * Theme.mapSensitivity
            }
        }

        PinchHandler {
            target: null
            minimumPointCount: 2
            property real startZoom: root.defaultZoom
            onActiveChanged: if (active) { startZoom = map.zoomLevel; followAnim.stop() }
            onActiveScaleChanged: {
                if (!active)
                    return
                map.zoomLevel = startZoom + Math.log2(activeScale) * Theme.mapSensitivity
            }
        }

        // Under the route and the pins (TripMarker).
        PlaceLabels {
            geoMap: map
            active: root.isCurrent
        }
        HomeMarker {}

        BasemapSwitch {
            geoMap: map
            active: root.isCurrent
        }

        // Over the names (3), under the home (5) and the pins (6).
        SpeedRoute {
            z: 4
            geoMap: map
            route: Trips.route
            lineWidth: Theme.tripRouteWidth
            casingColor: Theme.tripRouteCasing
        }

        // Start / end pins at the route's first + last fix. Map items, so they pan
        // and zoom with the map natively. Shown only when a route is drawn.
        TripMarker {
            label: qsTr("Alku")
            visible: Trips.hasRoute
            coordinate: Trips.routeStart
        }
        TripMarker {
            label: qsTr("Loppu")
            visible: Trips.hasRoute
            coordinate: Trips.routeEnd
        }

    }

    // Graph-inspect marker: a heading arrow (same asset as the dashboard car marker) at
    // the route position for the time the user is inspecting on the speed graph, rotated
    // to the direction of travel. An overlay above the map (z 6), so it sits over the
    // route and the pins. Projected via map.fromCoordinate
    // (which references map.center + zoomLevel so it re-projects on every pan/zoom).
    // The map follows it (dead-zone pan, see followInspect) so it stays on-screen.
    Image {
        id: inspectMarker
        source: "qrc:/resources/icons/arrow.svg"
        width: 28
        height: 28
        smooth: true
        antialiasing: true
        z: 6
        // Shown only while inspecting AND while the inspected fix projects onto the map
        // (within half an icon of an edge, so it can slide in). A fix that's off the
        // current view therefore never paints a stray arrow over the neighbouring cards;
        // the follow logic below keeps the fix on-map so this is normally true. root is
        // clipped as well (belt and braces), trimming any straddling marker at the edge.
        visible: root.inspecting && root.inspectPoint !== null && map.mapReady
                 && projected.x > -width / 2 && projected.x < map.width + width / 2
                 && projected.y > -height / 2 && projected.y < map.height + height / 2
        rotation: root.inspectPoint ? root.inspectPoint.bearing : 0

        // Screen position of the inspected fix. Referencing map.center + map.zoomLevel
        // makes this re-evaluate as the map moves (fromCoordinate alone is not a tracked
        // dependency). Kept independent of `visible` (which reads it back) to avoid a
        // binding loop.
        property point projected: {
            var c = map.center
            var z = map.zoomLevel
            if (!root.inspecting || root.inspectPoint === null || !map.mapReady)
                return Qt.point(-100000, -100000)
            return map.fromCoordinate(
                QtPositioning.coordinate(root.inspectPoint.lat, root.inspectPoint.lon), false)
        }
        x: projected.x - width / 2
        y: projected.y - height / 2
    }

    // Dead-zone follow for the inspect arrow. The arrow roams freely inside a centred
    // box inset 20% from every map edge; the moment the inspected fix would cross that
    // box (the user scrubbed the graph to a spot outside the current view) the map eases
    // so the fix lands 35% in from that edge — a cushion so small subsequent moves don't
    // immediately re-trigger. Only map.center is animated, so the user's chosen zoom is
    // preserved. Driven off inspectPoint/inspecting changes (never off center changes),
    // so the pan it starts can't feed back into itself; manual pan/pinch/wheel stop it.
    CoordinateAnimation {
        id: followAnim
        target: map
        property: "center"
        duration: 350
        easing.type: Easing.OutQuad
    }

    onInspectPointChanged: followInspect()
    onInspectingChanged: {
        if (inspecting)
            followInspect()
        else
            followAnim.stop()
    }

    // Pan the map (if needed) to keep the inspected fix inside the free-move box.
    function followInspect() {
        if (!inspecting || inspectPoint === null || !map.mapReady)
            return
        var w = map.width, h = map.height
        if (w <= 0 || h <= 0)
            return
        var cur = map.fromCoordinate(
            QtPositioning.coordinate(inspectPoint.lat, inspectPoint.lon), false)

        // Free-move box edges at 20%/80%; when crossed, target the 35%/65% cushion.
        // Axes are handled independently — only the crossed one moves.
        var targetX = cur.x
        if (cur.x < w * 0.20)      targetX = w * 0.35
        else if (cur.x > w * 0.80) targetX = w * 0.65
        var targetY = cur.y
        if (cur.y < h * 0.20)      targetY = h * 0.35
        else if (cur.y > h * 0.80) targetY = h * 0.65

        if (targetX === cur.x && targetY === cur.y)
            return   // inside the box on both axes -> hold still, let the arrow glide

        // Move center so the fix goes from its current pixel to the target pixel — the
        // same "grab a point and drag it" math the manual pan handler uses.
        var geoAtTarget = map.toCoordinate(Qt.point(targetX, targetY), false)
        followAnim.to = QtPositioning.coordinate(
            map.center.latitude + (inspectPoint.lat - geoAtTarget.latitude),
            map.center.longitude + (inspectPoint.lon - geoAtTarget.longitude))
        followAnim.restart()
    }

    // A new route (or a cleared one) arrives from the backend.
    Connections {
        target: Trips
        function onRouteChanged() { root.fitToRoute() }
    }

    onIsCurrentChanged: if (!isCurrent) followAnim.stop()

    // Fit the viewport to the route's bounding box, padded a little so the line
    // doesn't touch the edges. Assigning visibleRegion (a plain property) is used
    // rather than fitViewportToGeoShape(shape, margins) — the latter's margins
    // argument type varies across Qt versions and silently no-ops on a mismatch,
    // which would leave the map parked on its default centre with the route off
    // screen. Setting visibleRegion implicitly recentres + rezooms to show the shape.
    function fitToRoute() {
        if (!map.mapReady || !Trips.hasRoute)
            return
        var minLat = Trips.routeMinLat, maxLat = Trips.routeMaxLat
        var minLon = Trips.routeMinLon, maxLon = Trips.routeMaxLon
        if (minLat === maxLat && minLon === maxLon) {
            // Degenerate (single fix): centre + a sensible zoom, since a zero-area
            // shape would zoom to the maximum.
            map.center = QtPositioning.coordinate(minLat, minLon)
            map.zoomLevel = 15
            return
        }
        // ~15% padding on each side (plus a small floor for very short trips).
        var latPad = (maxLat - minLat) * 0.15 + 0.0005
        var lonPad = (maxLon - minLon) * 0.15 + 0.0005
        map.visibleRegion = QtPositioning.rectangle(
            QtPositioning.coordinate(maxLat + latPad, minLon - lonPad),   // top-left
            QtPositioning.coordinate(minLat - latPad, maxLon + lonPad))   // bottom-right
    }
}

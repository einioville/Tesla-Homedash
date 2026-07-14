import QtQuick
import QtLocation
import QtPositioning
import frontend_v2

// Trips-view map: a free-pan/zoom OSM map (no car-follow) that draws the selected
// trip's GPS path as a colour-graded polyline. The route comes from the Trips
// singleton ({ latitude, longitude, speed } per fix); the map fits its viewport to
// the route when one arrives.
//
// The line is drawn on a Canvas overlaid on the map (a sibling on top, like the
// TeslaMap corner overlay — no input handlers, so pan/pinch/wheel fall through to
// the Map). Each segment is coloured by the mean speed of its two endpoints, from
// dark green (slow) to dark red (Theme.tripMaxSpeedKmh, default 150 km/h). No dots
// are drawn on the fixes — just the connecting lines.
//
// Resolution follows the zoom level: the route is decimated so kept fixes sit
// ~4 px apart at the current zoom (rebuilt on zoom / route change). Each repaint
// projects + strokes only the survivors that fall in (or near) the viewport, so
// panning a long trip while zoomed in stays cheap regardless of trip length. Zoomed
// out, distant fixes collapse to a coarse line; zoomed in, full detail is drawn.
Item {
    id: root

    // Clip so the inspect-arrow overlay (a plain Image projected from a geo-coordinate)
    // can never paint outside the map card and over the neighbouring view items when the
    // inspected fix sits off the current viewport. The Map + route Canvas fill root
    // exactly, so clipping them is a no-op.
    clip: true

    property bool isCurrent: true
    property real maxSpeedKmh: Theme.tripMaxSpeedKmh
    property real lineWidth: Theme.tripRouteWidth
    property real defaultZoom: 12

    // Plain-JS snapshot of Trips.route ([{ lat, lon, speed }, ...]), taken once per
    // route change. Decimation reads THIS, not the Trips.route QVariantList, so a
    // pinch-zoom (which re-decimates on every zoom delta) never re-marshals each
    // QVariantMap out of the singleton.
    property var rawRoute: []

    // The decimated survivor list [{ lat, lon, speed }, ...], rebuilt on zoom / route
    // change; the paint step then projects only the on-screen survivors.
    property var decimated: []

    // Graph-inspect mirror: while the user hovers the speed graph, show a heading arrow
    // at the route position for the inspected time. Bound by TripsView.
    property bool inspecting: false
    property real inspectTime: 0
    // The inspected { lat, lon, bearing } (or null), recomputed as the cursor moves.
    property var inspectPoint: (inspecting && rawRoute.length > 0)
                               ? positionAtTime(inspectTime) : null

    Plugin {
        id: osmPlugin
        name: "osm"
        PluginParameter { name: "osm.useragent"; value: "Tesla-Homedash/1.0" }
        PluginParameter { name: "osm.mapping.providersrepository.disabled"; value: true }
        // Same custom tile host as the dashboard/full-screen map (AppConfig serves
        // the MML orthophoto or the keyless Sentinel-2 fallback).
        PluginParameter { name: "osm.mapping.host"; value: App.mapTilesUrl }
        PluginParameter { name: "osm.mapping.custom.mapcopyright"; value: App.mapAttribution }
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

        // Select the custom (imagery) map type by style, not a fixed index — the
        // supported list loads async and its order is provider-dependent.
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

        // Repaint the route as the view moves; a zoom change also re-decimates
        // (resolution follows zoom). fromCoordinate only works once mapReady, so a
        // route that arrived earlier is fitted + drawn when the map becomes ready.
        onCenterChanged: routeCanvas.requestPaint()
        onZoomLevelChanged: { root.rebuildDecimation(); routeCanvas.requestPaint() }
        onMapReadyChanged: if (mapReady) {
            root.fitToRoute()
            root.rebuildDecimation()
            routeCanvas.requestPaint()
        }

        // Free pan (1:1 in map coordinates, DPR-correct — see TeslaMap).
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
                    map.center.latitude + (from.latitude - to.latitude),
                    map.center.longitude + (from.longitude - to.longitude))
                lastCentroid = centroid.position
            }
        }

        WheelHandler {
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: function(event) {
                followAnim.stop()
                map.zoomLevel += event.angleDelta.y / 120 * 0.5
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
                map.zoomLevel = startZoom + Math.log2(activeScale)
            }
        }

        // Start / end pins at the route's first + last fix. Map items, so they pan
        // and zoom with the map natively. Shown only when a route is drawn.
        TripMarker {
            label: qsTr("Alku")
            visible: Trips.hasRoute && Trips.routeStart.latitude !== undefined
            coordinate: (Trips.routeStart.latitude !== undefined)
                        ? QtPositioning.coordinate(Trips.routeStart.latitude, Trips.routeStart.longitude)
                        : QtPositioning.coordinate(0, 0)
        }
        TripMarker {
            label: qsTr("Loppu")
            visible: Trips.hasRoute && Trips.routeEnd.latitude !== undefined
            coordinate: (Trips.routeEnd.latitude !== undefined)
                        ? QtPositioning.coordinate(Trips.routeEnd.latitude, Trips.routeEnd.longitude)
                        : QtPositioning.coordinate(0, 0)
        }

    }

    // Route overlay. Sibling on top of the map (no input handlers -> gestures fall
    // through). Fills the same rect as the map, so map.fromCoordinate (relative to
    // the map item) maps 1:1 into canvas coordinates.
    Canvas {
        id: routeCanvas
        anchors.fill: parent
        z: 5
        onPaint: root.paintRoute()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    // Graph-inspect marker: a heading arrow (same asset as the dashboard car marker) at
    // the route position for the time the user is inspecting on the speed graph, rotated
    // to the direction of travel. Rendered as an overlay ABOVE the route Canvas (z 6 >
    // the Canvas's z 5) so it sits ON TOP of the drawn path — a MapQuickItem would draw
    // as part of the map, under the Canvas overlay. Projected via map.fromCoordinate
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
        // dependency), matching how the route Canvas repaints on view changes. Kept
        // independent of `visible` (which reads it back) to avoid a binding loop.
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
        function onRouteChanged() {
            root.snapshotRoute()
            root.rebuildDecimation()
            root.fitToRoute()
            routeCanvas.requestPaint()
        }
    }

    // Copy Trips.route (a QVariantList of QVariantMaps) into a plain-JS array once,
    // so the per-zoom decimation and per-frame paint never touch the singleton list.
    function snapshotRoute() {
        var r = Trips.route
        var out = []
        if (r) {
            for (var i = 0; i < r.length; ++i)
                out.push({ lat: r[i].latitude, lon: r[i].longitude,
                           speed: r[i].speed, ts: r[i].ts })
        }
        root.rawRoute = out
    }

    // Redraw when returning to the view (in case GL state was released while hidden).
    onIsCurrentChanged: {
        if (isCurrent)
            routeCanvas.requestPaint()
        else
            followAnim.stop()
    }

    // Dark green (0 km/h) -> red / dark red (maxSpeedKmh). Hue sweeps 120deg->0deg;
    // the value dips toward the top so the fast end reads as a darker red. Speeds
    // above the max clamp to the top colour.
    function colorForSpeed(kmh) {
        var t = Math.max(0, Math.min(1, kmh / root.maxSpeedKmh))
        var hue = 0.333 * (1 - t)      // 120deg green -> 0deg red (Qt.hsva hue is 0..1)
        var val = 0.72 - 0.18 * t      // dark-ish green -> dark red
        return Qt.hsva(hue, 1.0, val, 1.0)
    }

    // Rebuild the decimated survivor list for the current zoom. Spacing target is
    // ~4 px, converted to metres via the Web-Mercator metres-per-pixel at the current
    // zoom/latitude, and applied as an equirectangular distance in geo space — so no
    // projection is needed here (cheap), and the paint step reprojects the survivors.
    function rebuildDecimation() {
        var r = root.rawRoute
        if (!r || r.length === 0) {
            root.decimated = []
            return
        }
        var lat0 = map.center.latitude
        var mpp = 156543.03392 * Math.cos(lat0 * Math.PI / 180) / Math.pow(2, map.zoomLevel)
        var threshold = mpp * 4  // metres between kept fixes at this zoom
        var earth = 6378137.0
        var out = [r[0]]
        var last = r[0]
        for (var i = 1; i < r.length - 1; ++i) {
            var dLat = (r[i].lat - last.lat) * Math.PI / 180
            var dLon = (r[i].lon - last.lon) * Math.PI / 180
            var cLat = Math.cos(last.lat * Math.PI / 180)
            var metres = earth * Math.sqrt(dLat * dLat + cLat * cLat * dLon * dLon)
            if (metres >= threshold) {
                last = r[i]
                out.push(last)
            }
        }
        if (r.length > 1) {
            // Always keep the final fix so the line reaches the trip's end.
            out.push(r[r.length - 1])
        }
        root.decimated = out
    }

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

    // Nearest route fix to an inspected time, with a travel-direction bearing. rawRoute
    // is ascending by ts, so a binary search finds the surrounding pair and picks the
    // closer one. Returns { lat, lon, bearing } or null when there's no route.
    function positionAtTime(t) {
        var r = root.rawRoute
        var n = r.length
        if (n === 0)
            return null
        if (t <= r[0].ts)
            return pointWithBearing(0)
        if (t >= r[n - 1].ts)
            return pointWithBearing(n - 1)
        var lo = 0
        var hi = n - 1
        while (lo < hi) {
            var mid = (lo + hi) >> 1
            if (r[mid].ts < t)
                lo = mid + 1
            else
                hi = mid
        }
        // lo is the first fix at/after t; pick whichever of (lo-1, lo) is nearer in time.
        var idx = (Math.abs(r[lo - 1].ts - t) <= Math.abs(r[lo].ts - t)) ? (lo - 1) : lo
        return pointWithBearing(idx)
    }

    // Build the { lat, lon, bearing } for a fix. Bearing is taken toward the next fix
    // (or from the previous one at the very end), so the arrow points along the route.
    function pointWithBearing(idx) {
        var r = root.rawRoute
        var n = r.length
        var a = r[idx]
        var bearing = 0
        if (idx + 1 < n)
            bearing = bearingDeg(a.lat, a.lon, r[idx + 1].lat, r[idx + 1].lon)
        else if (idx - 1 >= 0)
            bearing = bearingDeg(r[idx - 1].lat, r[idx - 1].lon, a.lat, a.lon)
        return { lat: a.lat, lon: a.lon, bearing: bearing }
    }

    // Initial compass bearing (degrees clockwise from north) from point 1 to point 2 —
    // matches the arrow.svg convention the dashboard car marker uses (rotation = heading,
    // 0 = up = north).
    function bearingDeg(lat1, lon1, lat2, lon2) {
        var rad = Math.PI / 180
        var y = Math.sin((lon2 - lon1) * rad) * Math.cos(lat2 * rad)
        var x = Math.cos(lat1 * rad) * Math.sin(lat2 * rad)
                - Math.sin(lat1 * rad) * Math.cos(lat2 * rad) * Math.cos((lon2 - lon1) * rad)
        return (Math.atan2(y, x) / rad + 360) % 360
    }

    function paintRoute() {
        var ctx = routeCanvas.getContext("2d")
        ctx.clearRect(0, 0, routeCanvas.width, routeCanvas.height)
        var d = root.decimated
        if (!d || d.length < 2 || !map.mapReady)
            return

        var w = routeCanvas.width, h = routeCanvas.height

        // Viewport geo-box (from the map corners) inflated by 30% each side, so we
        // only project + stroke the on-screen part of the route. The survivor list
        // spans the whole trip; at high zoom most of it is off-screen, and skipping it
        // here keeps a pan cheap regardless of trip length.
        var tl = map.toCoordinate(Qt.point(0, 0), false)
        var br = map.toCoordinate(Qt.point(w, h), false)
        var latMin = Math.min(tl.latitude, br.latitude)
        var latMax = Math.max(tl.latitude, br.latitude)
        var lonMin = Math.min(tl.longitude, br.longitude)
        var lonMax = Math.max(tl.longitude, br.longitude)
        var latPad = (latMax - latMin) * 0.3 + 1e-4
        var lonPad = (lonMax - lonMin) * 0.3 + 1e-4
        latMin -= latPad; latMax += latPad; lonMin -= lonPad; lonMax += lonPad

        function inBox(pt) {
            return pt.lat >= latMin && pt.lat <= latMax && pt.lon >= lonMin && pt.lon <= lonMax
        }
        function project(pt) {
            var p = map.fromCoordinate(QtPositioning.coordinate(pt.lat, pt.lon), false)
            return { x: p.x, y: p.y, speed: pt.speed }
        }

        ctx.lineCap = "round"
        ctx.lineJoin = "round"

        // Walk the survivors, drawing each contiguous run of segments that touch the
        // viewport (either endpoint in the box). A run's points are projected once;
        // its dark casing is one continuous stroke, then the coloured segments go on
        // top. Breaking into runs keeps the casing from bridging an off-screen gap
        // (e.g. a trip that loops out of view and back).
        var n = d.length
        var i = 0
        while (i < n - 1) {
            if (!(inBox(d[i]) || inBox(d[i + 1]))) {
                ++i
                continue
            }
            var run = [project(d[i])]
            while (i < n - 1 && (inBox(d[i]) || inBox(d[i + 1]))) {
                run.push(project(d[i + 1]))
                ++i
            }
            if (run.length < 2)
                continue

            // Casing (continuous).
            ctx.strokeStyle = Theme.tripRouteCasing
            ctx.lineWidth = root.lineWidth + 3
            ctx.beginPath()
            ctx.moveTo(run[0].x, run[0].y)
            for (var k = 1; k < run.length; ++k)
                ctx.lineTo(run[k].x, run[k].y)
            ctx.stroke()

            // Coloured, one stroke per segment (mean speed of its two endpoints).
            ctx.lineWidth = root.lineWidth
            for (k = 1; k < run.length; ++k) {
                ctx.strokeStyle = root.colorForSpeed((run[k - 1].speed + run[k].speed) * 0.5)
                ctx.beginPath()
                ctx.moveTo(run[k - 1].x, run[k - 1].y)
                ctx.lineTo(run[k].x, run[k].y)
                ctx.stroke()
            }
        }
    }
}

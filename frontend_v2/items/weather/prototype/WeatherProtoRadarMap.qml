import QtQuick
import QtCore as QC
import QtLocation
import QtPositioning
import frontend_v2

// FMI's live radar composite looping over a basemap that can be panned and zoomed.
//
// The radar is a WMS layer in EPSG:3857, the projection the tiles use, so each frame is one
// transparent PNG requested for exactly the visible area at the map's pixel size and laid
// straight over it. While the map moves, the frames already loaded move and scale with it
// (each is placed from the coordinate of its own top-left corner and the zoom it was
// fetched at); once the map rests, every frame is fetched again for the new view, and each
// keeps its old picture in place until its new one has loaded. The lightning layer works
// the same way.
//
// Gestures are TripMap's: one-finger pan, pinch and wheel zoom, scaled by the shared map
// sensitivity. The zoom stays between minimumZoom and maximumZoom, and the centre within
// the radar's coverage, so the map cannot be lost somewhere the radar does not reach. Like the
// home map, it glides back to the place on its own once left alone for the *Keskitysviive*
// (Theme.mapFollowResumeSec), and is back there whenever the view is opened again.
//
// The basemap here is EOX Sentinel-2, not the app's MML orthophoto: MML covers Finland only
// and answers everywhere else (sea, Sweden, Estonia) with a blank white tile, which a
// regional radar view runs into near any coast. At radar zoom, Sentinel-2's 10 m is plenty.
// It needs a tile cache of its own: the OSM plugin names cached tiles by plugin, map type
// and tile number but not by host, so sharing TeslaMap's would hand each map the other's
// imagery.
//
// Lightning comes from FMI's WFS (`fmi::observations::lightning::multipointcoverage`), not the
// WMS, which has no lightning layer: every detected strike over the composite since the
// first frame, fetched with the frames. Each frame draws its own 5-minute slot's strikes bright,
// and the earlier ones of the loop fading with age, so a storm leaves its track; the newest
// frame also takes the strikes since it, which arrive a few minutes before the radar does.
Item {
    id: root

    property real latitude: 61.499
    property real longitude: 23.787
    property real zoom: 7.6
    // The zoom gestures can reach: 5 fits the whole composite (all of Finland) in the card,
    // 10 a town and its surroundings, about where the radar's own resolution runs out.
    property real minimumZoom: 5
    property real maximumZoom: 10
    // Where the place sits, in pixels from the map's centre (so a variant can keep it
    // clear of its own panels).
    property point placeOffset: Qt.point(0, 0)
    property bool active: true
    property int frameCount: 13          // one hour at FMI's 5-minute cadence
    readonly property int frameStepMin: 5
    property string radarLayer: "Radar:suomi_dbz_eureffin"
    property real dim: 0.25
    property string tilesUrl: "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/"
                              + "GoogleMapsCompatible/%z/%y/%x.jpg"
    readonly property string tileCacheDir: {
        var base = QC.StandardPaths.writableLocation(QC.StandardPaths.GenericCacheLocation).toString()
        base = decodeURIComponent(base.replace(/^file:\/\//, ""))
        if (Qt.platform.os === "windows")
            base = base.replace(/^\//, "")
        return base + "/Tesla-Homedash/tiles-weather-radar"
    }
    // The radars' reach, about: the map's centre stays inside it, so a pan cannot leave the
    // radar behind. The lightning is fetched for the composite's whole extent (its EPSG:3067
    // box from the WMS capabilities, rounded out), which any view at any zoom stays inside.
    readonly property var coverage: ({ south: 59.5, north: 69.5, west: 20, east: 31 })
    readonly property var extent: ({ south: 57, north: 71, west: 15, east: 35 })

    property int frame: frameCount - 1
    property bool playing: true
    property var frameTimes: []
    // The view the frames were last fetched for: the visible area's top-left coordinate, the
    // zoom, the pixel size, and the box in EPSG:3857 metres. Taken whenever the map comes to rest.
    property var view: null
    // Strikes over the whole coverage as { mx, my, t }: EPSG:3857 metres and epoch
    // milliseconds; and those in the view, which are the ones drawn and counted.
    property var allStrikes: []
    readonly property var strikes: view ? allStrikes.filter(s => s.mx >= view.x0 && s.mx <= view.x1
                                                                 && s.my >= view.y0 && s.my <= view.y1)
                                        : []
    // A made-up storm crossing the map instead of FMI's strikes, to see them on a calm day.
    property bool demoLightning: false
    // What strikeLayer draws for the shown frame.
    readonly property int strikesShown: {
        if (!frameTimes.length)
            return 0
        var end = frame === frameCount - 1 ? Infinity : frameTime.getTime()
        var start = frameTimes[0].getTime() - frameStepMin * 60000
        var n = 0
        for (var i = 0; i < strikes.length; i++)
            if (strikes[i].t <= end && strikes[i].t > start)
                n++
        return n
    }
    readonly property date frameTime: frameTimes.length > frame ? frameTimes[frame] : new Date()
    // The place on screen now, following the map.
    readonly property point placePt: {
        map.center; map.zoomLevel; map.width; map.height
        return map.mapReady ? map.fromCoordinate(QtPositioning.coordinate(latitude, longitude), false)
                            : Qt.point(-100, -100)
    }
    // Off the place or its zoom, so the way back is offered.
    readonly property bool moved: map.mapReady
                                  && (Math.abs(map.zoomLevel - zoom) > 0.01
                                      || Math.abs(placePt.x - (width / 2 + placeOffset.x)) > 2
                                      || Math.abs(placePt.y - (height / 2 + placeOffset.y)) > 2)

    clip: true

    function refreshFrames() {
        // The newest composite lags real time by a few minutes; stay one step behind it.
        var step = frameStepMin * 60000
        var t = Math.floor((Date.now() - step) / step) * step
        var list = []
        for (var i = frameCount - 1; i >= 0; i--)
            list.push(new Date(t - i * step))
        frameTimes = list
        fetchLightning()
    }

    property var strikeXhr: null

    function fetchLightning() {
        if (!frameTimes.length)
            return
        if (demoLightning) {
            allStrikes = demoStrikes()
            return
        }
        // Cleared before the abort, whose DONE callback must not count as this fetch's.
        if (strikeXhr) {
            var old = strikeXhr
            strikeXhr = null
            old.abort()
        }
        var iso = d => d.toISOString().replace(/\.\d{3}Z$/, "Z")
        var start = new Date(frameTimes[0].getTime() - frameStepMin * 60000)
        var url = "https://opendata.fmi.fi/wfs?service=WFS&version=2.0.0&request=getFeature"
                + "&storedquery_id=fmi::observations::lightning::multipointcoverage"
                + "&bbox=" + [extent.west, extent.south, extent.east, extent.north].join(",")
                + "&starttime=" + iso(start) + "&endtime=" + iso(new Date())
        var xhr = new XMLHttpRequest()
        strikeXhr = xhr
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE || xhr !== root.strikeXhr)
                return
            root.strikeXhr = null
            if (xhr.status !== 200) {
                console.warn("Lightning fetch failed: HTTP", xhr.status)
                return
            }
            root.allStrikes = root.parseStrikes(xhr.responseText)
        }
        xhr.open("GET", url)
        xhr.send()
    }

    // gmlcov:positions holds one "lat lon epoch-seconds" triple per strike; a response with no
    // strikes has no positions element at all.
    function parseStrikes(xml) {
        var m = /<gmlcov:positions>([\s\S]*?)<\/gmlcov:positions>/.exec(xml)
        if (!m)
            return []
        var v = m[1].trim().split(/\s+/)
        var list = []
        for (var i = 0; i + 2 < v.length; i += 3) {
            var p = merc({ latitude: Number(v[i]), longitude: Number(v[i + 1]) })
            list.push({ mx: p.x, my: p.y, t: Number(v[i + 2]) * 1000 })
        }
        return list
    }

    // Into a view's pixels, the radar frames' own, so a strike lands on its echo exactly.
    function toPixel(s, v) {
        return Qt.point((s.mx - v.x0) / (v.x1 - v.x0) * v.w, (v.y1 - s.my) / (v.y1 - v.y0) * v.h)
    }

    // A cell drifting from the south-west past home over the loop, a few strikes a minute.
    function demoStrikes() {
        if (!view)
            return []
        var t0 = frameTimes[0].getTime() - frameStepMin * 60000
        var t1 = Date.now()
        var home = merc({ latitude: latitude, longitude: longitude })
        var mpp = (view.x1 - view.x0) / view.w
        var spread = () => Math.random() + Math.random() + Math.random() - 1.5
        var list = []
        for (var t = t0; t < t1; t += 60000) {
            var f = (t - t0) / (t1 - t0)
            var cx = -260 + 380 * f
            var cy = 150 - 210 * f
            for (var k = Math.floor(Math.random() * 4); k > 0; k--)
                list.push({ mx: home.x + (cx + spread() * 50) * mpp, my: home.y - (cy + spread() * 40) * mpp,
                            t: t + Math.random() * 60000 })
        }
        return list
    }

    onDemoLightningChanged: fetchLightning()
    onFrameChanged: strikeLayer.requestPaint()
    onStrikesChanged: strikeLayer.requestPaint()
    onViewChanged: strikeLayer.requestPaint()
    onLatitudeChanged: Qt.callLater(goHome)
    onLongitudeChanged: Qt.callLater(goHome)
    onActiveChanged: {
        if (!active) {
            returnTimer.stop()
            if (moved)
                goHome()
        }
    }

    // A gesture holds the map where it is; letting go starts the wait to go back.
    function gestureActive(isActive) {
        if (isActive) {
            homeAnim.stop()
            returnTimer.stop()
        } else if (moved) {
            returnTimer.restart()
        }
    }

    function merc(c) {
        var R = 6378137
        return { x: R * c.longitude * Math.PI / 180,
                 y: R * Math.log(Math.tan(Math.PI / 4 + c.latitude * Math.PI / 360)) }
    }

    function unmerc(x, y) {
        var R = 6378137
        return QtPositioning.coordinate((2 * Math.atan(Math.exp(y / R)) - Math.PI / 2) * 180 / Math.PI,
                                        x / R * 180 / Math.PI)
    }

    // The centre that puts the place at placeOffset at the given zoom.
    function homeCenter(z) {
        var mpp = 156543.03392 / Math.pow(2, z)
        var home = merc({ latitude: latitude, longitude: longitude })
        return unmerc(home.x - placeOffset.x * mpp, home.y + placeOffset.y * mpp)
    }

    // The Map's own minimumZoomLevel and maximumZoomLevel do not hold it there (the OSM plugin
    // takes any zoom it is given), so the gestures clamp it themselves.
    function zoomTo(z) {
        map.zoomLevel = Math.max(minimumZoom, Math.min(maximumZoom, z))
    }

    function clampCenter(c) {
        return QtPositioning.coordinate(Math.max(coverage.south, Math.min(coverage.north, c.latitude)),
                                        Math.max(coverage.west, Math.min(coverage.east, c.longitude)))
    }

    // Straight to the place at its zoom: on start and when the place changes.
    function goHome() {
        if (!map.mapReady || map.width <= 0 || map.height <= 0)
            return
        homeAnim.stop()
        map.zoomLevel = zoom
        map.center = homeCenter(zoom)
        captureView()
    }

    // Glides back, for the button.
    function returnHome() {
        homeAnim.stop()
        homeCenterAnim.to = homeCenter(zoom)
        homeZoomAnim.to = zoom
        homeAnim.start()
    }

    function captureView() {
        if (!map.mapReady || map.width <= 0 || map.height <= 0)
            return
        var tlc = map.toCoordinate(Qt.point(0, 0), false)
        var brc = map.toCoordinate(Qt.point(map.width, map.height), false)
        var tl = merc(tlc)
        var br = merc(brc)
        view = { coord: tlc, zoom: map.zoomLevel, w: Math.round(map.width), h: Math.round(map.height),
                 x0: tl.x, y0: br.y, x1: br.x, y1: tl.y }
    }

    // Where a view's top-left sits on screen now, and how far the map has zoomed since.
    // Bindings that call this name map.center, zoomLevel and size, its real inputs.
    function placement(v) {
        var p = map.fromCoordinate(v.coord, false)
        return { x: p.x, y: p.y, s: Math.pow(2, map.zoomLevel - v.zoom) }
    }

    function frameUrl(d, v) {
        if (!d || !v)
            return ""
        return "https://openwms.fmi.fi/geoserver/Radar/wms?service=WMS&version=1.3.0&request=GetMap"
               + "&layers=" + radarLayer + "&styles=&crs=EPSG:3857"
               + "&bbox=" + v.x0 + "," + v.y0 + "," + v.x1 + "," + v.y1
               + "&width=" + v.w + "&height=" + v.h
               + "&format=image/png&transparent=true&time=" + d.toISOString().replace(".000Z", "Z")
    }

    Plugin {
        id: osmPlugin
        name: "osm"
        PluginParameter { name: "osm.useragent"; value: "Tesla-Homedash/1.0" }
        PluginParameter { name: "osm.mapping.providersrepository.disabled"; value: true }
        PluginParameter { name: "osm.mapping.host"; value: root.tilesUrl }
        PluginParameter { name: "osm.mapping.custom.mapcopyright"; value: "Sentinel-2 cloudless (s2maps.eu) by EOX" }
        PluginParameter { name: "osm.mapping.cache.directory"; value: root.tileCacheDir }
    }

    Map {
        id: map
        anchors.fill: parent
        plugin: osmPlugin
        zoomLevel: root.zoom
        // Not 0: at a whole zoom and bearing 0 the tiles are filtered Nearest and step in whole
        // pixels under the radar, which moves smoothly (items/tesla/CLAUDE.md).
        bearing: 0.001
        copyrightsVisible: false
        center: QtPositioning.coordinate(root.latitude, root.longitude)

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
        onMapReadyChanged: Qt.callLater(root.goHome)
        // Any move or resize: fetch for the new view once the map rests.
        onCenterChanged: settle.restart()
        onZoomLevelChanged: settle.restart()
        onWidthChanged: settle.restart()
        onHeightChanged: settle.restart()

        DragHandler {
            target: null
            minimumPointCount: 1
            maximumPointCount: 1
            dragThreshold: 0
            property point lastCentroid
            onActiveChanged: {
                if (active)
                    lastCentroid = centroid.position
                root.gestureActive(active)
            }
            onCentroidChanged: {
                if (!active)
                    return
                var from = map.toCoordinate(lastCentroid, false)
                var to = map.toCoordinate(centroid.position, false)
                map.center = root.clampCenter(QtPositioning.coordinate(
                    map.center.latitude + (from.latitude - to.latitude) * Theme.mapSensitivity,
                    map.center.longitude + (from.longitude - to.longitude) * Theme.mapSensitivity))
                lastCentroid = centroid.position
            }
        }

        WheelHandler {
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: function(event) {
                root.gestureActive(true)
                root.zoomTo(map.zoomLevel + event.angleDelta.y / 120 * 0.5 * Theme.mapSensitivity)
                root.gestureActive(false)
            }
        }

        PinchHandler {
            target: null
            minimumPointCount: 2
            property real startZoom: root.zoom
            onActiveChanged: {
                if (active)
                    startZoom = map.zoomLevel
                root.gestureActive(active)
            }
            onActiveScaleChanged: {
                if (!active)
                    return
                root.zoomTo(startZoom + Math.log2(activeScale) * Theme.mapSensitivity)
            }
        }
    }

    Timer {
        id: returnTimer
        interval: Theme.mapFollowResumeSec * 1000
        onTriggered: root.returnHome()
    }

    Timer {
        id: settle
        interval: 400
        onTriggered: root.captureView()
    }

    ParallelAnimation {
        id: homeAnim
        CoordinateAnimation {
            id: homeCenterAnim
            target: map
            property: "center"
            duration: 500
            easing.type: Easing.OutCubic
        }
        NumberAnimation {
            id: homeZoomAnim
            target: map
            property: "zoomLevel"
            duration: 500
            easing.type: Easing.OutCubic
        }
    }

    // Darken the imagery so the radar colours carry the picture.
    Rectangle {
        anchors.fill: parent
        color: "black"
        opacity: root.dim
    }

    Repeater {
        model: root.frameCount

        Image {
            id: frameImage
            required property int index
            // The view this image's picture belongs to. A new view's picture replaces it only
            // once loaded, and until then the old one stays where it belongs on the map.
            property var shown: null
            readonly property var place: {
                map.center; map.zoomLevel; map.width; map.height
                return shown ? root.placement(shown) : null
            }
            x: place ? place.x : 0
            y: place ? place.y : 0
            width: shown ? shown.w : 0
            height: shown ? shown.h : 0
            scale: place ? place.s : 1
            transformOrigin: Item.TopLeft
            source: root.frameUrl(root.frameTimes[index], root.view)
            retainWhileLoading: true
            visible: index === root.frame && shown !== null
            asynchronous: true
            cache: true
            onStatusChanged: if (status === Image.Ready) shown = root.view
            // A picture already in the cache arrives without a status change.
            onSourceChanged: Qt.callLater(() => { if (status === Image.Ready) shown = root.view })
        }
    }

    Canvas {
        id: strikeLayer
        // The view the strikes were last painted for, which places the canvas like a frame.
        property var painted: null
        readonly property var place: {
            map.center; map.zoomLevel; map.width; map.height
            return painted ? root.placement(painted) : null
        }
        x: place ? place.x : 0
        y: place ? place.y : 0
        width: root.view ? root.view.w : 0
        height: root.view ? root.view.h : 0
        scale: place ? place.s : 1
        transformOrigin: Item.TopLeft

        function cross(ctx, x, y, r) {
            ctx.beginPath()
            ctx.moveTo(x - r, y - r)
            ctx.lineTo(x + r, y + r)
            ctx.moveTo(x + r, y - r)
            ctx.lineTo(x - r, y + r)
            ctx.stroke()
        }

        // Yellow crosses outlined in black, so one shows on the radar's own yellow and red too.
        // All of a group's outlines go down before its crosses, or each cross in a cluster
        // would cut the one under it.
        function crosses(ctx, list, r, width) {
            ctx.lineCap = "round"
            ctx.strokeStyle = "black"
            ctx.lineWidth = width + 3
            for (var i = 0; i < list.length; i++) {
                ctx.globalAlpha = list[i].a
                cross(ctx, list[i].x, list[i].y, r)
            }
            ctx.strokeStyle = "#ffd21f"
            ctx.lineWidth = width
            for (var j = 0; j < list.length; j++) {
                ctx.globalAlpha = list[j].a
                cross(ctx, list[j].x, list[j].y, r)
            }
            ctx.globalAlpha = 1
        }

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var v = root.view
            painted = v
            if (!v || !root.frameTimes.length)
                return
            var step = root.frameStepMin * 60000
            var f = root.frameTime.getTime()
            var end = root.frame === root.frameCount - 1 ? Infinity : f
            var trail = root.frameCount * step
            // A failed refresh leaves the last list in place; drop what has left the loop.
            var loopStart = root.frameTimes[0].getTime() - step

            // This frame's strikes full size, the loop's earlier ones smaller and fading with
            // age, drawn first so this frame's land on top of them.
            var earlier = []
            var fresh = []
            for (var i = 0; i < root.strikes.length; i++) {
                var s = root.strikes[i]
                if (s.t > end || s.t <= loopStart)
                    continue
                var p = root.toPixel(s, v)
                if (s.t > f - step)
                    fresh.push({ x: p.x, y: p.y, a: 1 })
                else
                    earlier.push({ x: p.x, y: p.y, a: Math.max(0.3, 0.9 - 0.6 * (f - s.t) / trail) })
            }
            crosses(ctx, earlier, 3.5, 2)
            crosses(ctx, fresh, 5, 2.5)
        }
    }

    // Home marker, above the radar.
    Rectangle {
        x: root.placePt.x - width / 2
        y: root.placePt.y - height / 2
        width: 16
        height: 16
        radius: 8
        color: Theme.accent
        border.color: "white"
        border.width: 2
    }

    // Back to the place and its zoom, offered once the map has been moved.
    Rectangle {
        id: homeButton
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 10
        width: 36
        height: 36
        radius: 18
        color: homeTap.pressed ? "#cc2a3038" : "#99161a20"
        border.color: "#40ffffff"
        border.width: 1
        opacity: root.moved ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Theme.dockDuration } }

        Image {
            anchors.centerIn: parent
            width: 20
            height: 20
            source: "qrc:/resources/icons/location.svg"
            sourceSize: Qt.size(40, 40)
        }
        MouseArea {
            id: homeTap
            anchors.fill: parent
            anchors.margins: -6
            onClicked: {
                returnTimer.stop()
                root.returnHome()
            }
        }
    }

    Timer {
        interval: root.frame === root.frameCount - 1 ? 2500 : 600
        running: root.active && root.playing && root.frameTimes.length > 0
        repeat: true
        onTriggered: root.frame = (root.frame + 1) % root.frameCount
    }

    Timer {
        interval: 5 * 60000
        running: root.active
        repeat: true
        onTriggered: root.refreshFrames()
    }

    Component.onCompleted: refreshFrames()
}

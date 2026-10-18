import QtQuick
import QtPositioning
import frontend_v2

// FMI's live radar composite and lightning, looping over a QtLocation Map: the Weather
// view's radar card (WeatherRadarMap) and the Kartta view's radar layer. Fill the map with
// it; it only reads the map's camera.
//
// The radar is a WMS layer in EPSG:3857, the projection the tiles use, so each frame is one
// transparent PNG requested for a box round the visible area and laid straight over it.
// While the map moves, the frames already loaded move, scale and turn with it (each is placed
// from the coordinate of its own top-left corner and the scale it was fetched at); a new box
// is fetched only once the view leaves the old one or its zoom has drifted, checked when the
// map rests and every 1.5 s while it keeps moving, and each frame keeps its old picture in
// place until its new one has loaded. A map that keeps moving on its own (one following the
// car) asks for a margin round the view, so it stays inside one box for a while.
//
// Lightning comes from FMI's WFS (`fmi::observations::lightning::multipointcoverage`), not the
// WMS, which has no lightning layer: every detected strike over the composite since the
// first frame, fetched with the frames. Each frame draws its own 5-minute slot's strikes bright,
// and the earlier ones of the loop fading with age, so a storm leaves its track; the newest
// frame also takes the strikes since it, which arrive a few minutes before the radar does.
// They are drawn at screen resolution, so they stay crisp over a frame fetched coarser.
Item {
    id: root

    // The Map it lies over. Not `map`: a binding `map: map` would read this property itself.
    property Item geoMap: null
    property bool active: true
    // Extra area fetched round the view, as a share of its size on each side.
    property real margin: 0
    // The finest a frame is fetched at, in projected metres per pixel. The composite's cells
    // are about 500 m, so a map zoomed in to the streets gains nothing from finer frames.
    property real minMetresPerPixel: 0
    // The largest frame fetched, in pixels a side; a larger box is fetched coarser. Every
    // frame of the loop is held decoded, so this is what bounds the memory.
    property int maxImageSize: 2048
    // A gesture in progress: the frames follow it, and fetching waits until it ends.
    property bool holdFetch: false
    // How much the imagery is darkened so the radar colours carry the picture.
    property real dim: 0.25

    property int frameCount: 13          // one hour at FMI's 5-minute cadence
    readonly property int frameStepMin: 5
    property string radarLayer: "Radar:suomi_dbz_eureffin"
    // The lightning is fetched for the composite's whole extent (its EPSG:3067 box from the
    // WMS capabilities, rounded out), which any view at any zoom stays inside.
    readonly property var extent: ({ south: 57, north: 71, west: 15, east: 35 })

    property int frame: frameCount - 1
    property bool playing: true
    property var frameTimes: []
    // The box the frames were last fetched for: its top-left coordinate, its EPSG:3857 metres,
    // its pixel size and resolution, the map's zoom and metres per pixel when it was taken, and
    // `seen`, the part of it that was on screen.
    property var view: null
    // Strikes over the whole coverage as { mx, my, t }: EPSG:3857 metres and epoch
    // milliseconds; and those in the view, which are the ones counted.
    property var allStrikes: []
    readonly property var strikes: view ? allStrikes.filter(s => s.mx >= view.seen.x0 && s.mx <= view.seen.x1
                                                                 && s.my >= view.seen.y0 && s.my <= view.seen.y1)
                                        : []
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

    function ready() {
        return geoMap !== null && geoMap.mapReady && geoMap.width > 0 && geoMap.height > 0
    }

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

    function screenMerc(x, y) {
        return merc(geoMap.toCoordinate(Qt.point(x, y), false))
    }

    // The box a fetch now would take. The visible area's bounding box in EPSG:3857 — all four
    // corners, so a map turned heading-up is covered too — grown by the margin.
    function plan() {
        var w = geoMap.width
        var h = geoMap.height
        var c = [screenMerc(0, 0), screenMerc(w, 0), screenMerc(w, h), screenMerc(0, h)]
        var mpp = Math.hypot(c[1].x - c[0].x, c[1].y - c[0].y) / w
        var xs = c.map(p => p.x)
        var ys = c.map(p => p.y)
        var seen = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) }
        var mx = (seen.x1 - seen.x0) * margin
        var my = (seen.y1 - seen.y0) * margin
        var x0 = seen.x0 - mx, x1 = seen.x1 + mx, y0 = seen.y0 - my, y1 = seen.y1 + my
        var res = Math.max(mpp, minMetresPerPixel, (x1 - x0) / maxImageSize, (y1 - y0) / maxImageSize)
        return { coord: unmerc(x0, y1), x0: x0, y0: y0, x1: x1, y1: y1,
                 w: Math.round((x1 - x0) / res), h: Math.round((y1 - y0) / res), res: res,
                 zoom: geoMap.zoomLevel, mpp: mpp, seen: seen }
    }

    // Whether the fetched box still serves `p`: it covers the visible area, and the frames'
    // resolution is within a fifth of what a fetch now would take.
    function serves(p) {
        if (!view)
            return false
        var s = p.seen
        return s.x0 >= view.x0 && s.x1 <= view.x1 && s.y0 >= view.y0 && s.y1 <= view.y1
               && Math.abs(Math.log(p.res / view.res)) < Math.log(1.2)
    }

    // Fetches anew if the view has left what is fetched.
    function check() {
        if (!active || holdFetch || !ready())
            return
        var p = plan()
        if (!serves(p))
            view = p
        strikeLayer.repaint()
    }

    // Where a box's top-left sits on screen now, and how it is scaled and turned since.
    // Bindings that call this name the camera properties, its real inputs.
    function placement(v) {
        var p = geoMap.fromCoordinate(v.coord, false)
        var mppNow = v.mpp * Math.pow(2, v.zoom - geoMap.zoomLevel)
        return { x: p.x, y: p.y, s: v.res / mppNow, r: -geoMap.bearing }
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

    onFrameChanged: strikeLayer.repaint()
    onStrikesChanged: strikeLayer.repaint()
    onHoldFetchChanged: if (!holdFetch) settle.restart()
    // Coming live refreshes the frame list: it is as old as the last refresh, and a view is
    // built in the background long before it is first opened.
    onActiveChanged: if (active) { refreshFrames(); check() }

    Connections {
        target: root.geoMap
        function onCenterChanged() { root.cameraMoved() }
        function onZoomLevelChanged() { root.cameraMoved() }
        function onBearingChanged() { root.cameraMoved() }
        function onWidthChanged() { root.cameraMoved() }
        function onHeightChanged() { root.cameraMoved() }
        function onMapReadyChanged() { root.check() }
    }

    function cameraMoved() {
        settle.restart()
        if (!pace.running)
            pace.start()
    }

    Timer {
        id: settle
        interval: 400
        onTriggered: root.check()
    }

    Timer {
        id: pace
        interval: 1500
        onTriggered: root.check()
    }

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
            // The box this image's picture belongs to. A new box's picture replaces it only
            // once loaded, and until then the old one stays where it belongs on the map.
            property var shown: null
            readonly property var place: {
                if (!root.geoMap || index !== root.frame || !shown)
                    return null
                root.geoMap.center; root.geoMap.zoomLevel; root.geoMap.bearing; root.geoMap.width; root.geoMap.height
                return root.placement(shown)
            }
            x: place ? place.x : 0
            y: place ? place.y : 0
            width: shown ? shown.w : 0
            height: shown ? shown.h : 0
            scale: place ? place.s : 1
            rotation: place ? place.r : 0
            transformOrigin: Item.TopLeft
            source: root.frameUrl(root.frameTimes[index], root.view)
            retainWhileLoading: true
            visible: place !== null
            asynchronous: true
            cache: true
            onStatusChanged: if (status === Image.Ready) shown = root.view
            // A picture already in the cache arrives without a status change.
            onSourceChanged: Qt.callLater(() => { if (status === Image.Ready) shown = root.view })
        }
    }

    // Painted in screen pixels for the camera of the moment, then carried with the map like
    // a frame until the next paint: at each check, and when the frame or the strikes change.
    Canvas {
        id: strikeLayer
        width: root.width
        height: root.height
        visible: root.strikes.length > 0
        // The camera at the last paint: the coordinate under the top-left corner, the zoom
        // and the bearing.
        property var painted: null
        readonly property var place: {
            if (!root.geoMap || !painted)
                return null
            root.geoMap.center; root.geoMap.zoomLevel; root.geoMap.bearing; root.geoMap.width; root.geoMap.height
            var p = root.geoMap.fromCoordinate(painted.coord, false)
            return { x: p.x, y: p.y, s: Math.pow(2, root.geoMap.zoomLevel - painted.zoom),
                     r: painted.bearing - root.geoMap.bearing }
        }
        x: place ? place.x : 0
        y: place ? place.y : 0
        scale: place ? place.s : 1
        rotation: place ? place.r : 0
        transformOrigin: Item.TopLeft

        function repaint() {
            if (root.strikes.length > 0)
                requestPaint()
        }

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
            if (!root.ready() || !root.frameTimes.length) {
                painted = null
                return
            }
            var w = root.geoMap.width
            // EPSG:3857 to screen is a similarity: the screen's x axis runs along a→b, its
            // y axis (down) a quarter turn clockwise from that, k pixels to the metre.
            var a = root.screenMerc(0, 0)
            var b = root.screenMerc(w, 0)
            var len = Math.hypot(b.x - a.x, b.y - a.y)
            var ux = (b.x - a.x) / len
            var uy = (b.y - a.y) / len
            var k = w / len
            painted = { coord: root.geoMap.toCoordinate(Qt.point(0, 0), false),
                        zoom: root.geoMap.zoomLevel, bearing: root.geoMap.bearing }

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
                var dx = s.mx - a.x
                var dy = s.my - a.y
                var x = k * (dx * ux + dy * uy)
                var y = k * (dx * uy - dy * ux)
                if (s.t > f - step)
                    fresh.push({ x: x, y: y, a: 1 })
                else
                    earlier.push({ x: x, y: y, a: Math.max(0.3, 0.9 - 0.6 * (f - s.t) / trail) })
            }
            crosses(ctx, earlier, 3.5, 2)
            crosses(ctx, fresh, 5, 2.5)
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

    Component.onCompleted: {
        refreshFrames()
        Qt.callLater(check)
    }
}

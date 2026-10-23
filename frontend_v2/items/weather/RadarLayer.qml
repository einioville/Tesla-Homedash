import QtQuick
import QtPositioning
import frontend_v2

// FMI's live radar composite and lightning, looping over a QtLocation Map: the Weather
// view's radar card (WeatherRadarMap), and on the dashboard's and the Kartta view's maps both
// the minimap (RadarInset) and the overlay. Fill the map with it; it only reads the map's
// camera.
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
// They are drawn at screen resolution on the GPU (LightningLayer, core/weather/lightninglayer.hh),
// so they stay crisp over a frame fetched coarser and a loop step redraws nothing on the CPU.
//
// Both are fetched by the display, not the backend (root CLAUDE.md §5.4): the frames are for its
// own view, and the lightning, though the same for every display, is wanted only while a radar
// is on screen. A request that stalls ends after the QML engine's timeout (QmlNetworkFactory).
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
    // The frames' opacity, below 1 where the radar lies over a map that shows other things.
    // The lightning stays opaque.
    property real frameOpacity: 1

    property int frameCount: 13          // one hour at FMI's 5-minute cadence
    // How long each frame of the loop shows, and the newest, which holds longer.
    property int frameMs: 600
    property int newestFrameMs: 2500
    readonly property int frameStepMin: 5
    property string radarLayer: "Radar:suomi_dbz_eureffin"
    // The lightning is fetched for the composite's whole extent (its EPSG:3067 box from the
    // WMS capabilities, rounded out), which any view at any zoom stays inside.
    readonly property var extent: ({ south: 57, north: 71, west: 15, east: 35 })

    property int frame: frameCount - 1
    property bool playing: true
    // How long a step of the loop fades into the next, in ms; 0 cuts. The fade steps on a
    // Timer, 20 times a second, not an Animation, which would redraw the window on every vsync
    // for as long as the loop plays (frontend_v2/CLAUDE.md, *Motion that keeps running*).
    property int fadeMs: 400
    // The fade under way: the frame fading out (-1, none) and how far the shown one is in, 0–1.
    property int fadeFrom: -1
    property real fade: 1
    property real fadeStart: 0
    // Only the newest frame: no loop, and the older frames are not fetched at all.
    property bool latestOnly: false
    property var frameTimes: []
    // Another RadarLayer to play in step with, the overlay under a map's minimap: its frame
    // list, the frame it shows and its fade, so the two never show different times. Its own
    // loop and refresh then stand still.
    property Item follow: null
    // The box the frames were last fetched for: its top-left coordinate, its EPSG:3857 metres,
    // its pixel size and resolution, the map's zoom and metres per pixel when it was taken, and
    // `seen`, the part of it that was on screen.
    property var view: null
    // Strikes in the view, which are the ones drawn and counted; and those the shown frame draws.
    readonly property int strikeCount: strikeLayer.inArea
    readonly property int strikesShown: strikeLayer.shown
    readonly property date frameTime: frameTimes.length > frame ? frameTimes[frame] : new Date()

    function ready() {
        return geoMap !== null && geoMap.mapReady && geoMap.width > 0 && geoMap.height > 0
    }

    function refreshFrames() {
        if (follow)
            return
        // The newest composite lags real time by a few minutes; stay one step behind it.
        var step = frameStepMin * 60000
        var t = Math.floor((Date.now() - step) / step) * step
        var list = []
        for (var i = frameCount - 1; i >= 0; i--)
            list.push(new Date(t - i * step))
        frameTimes = list
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
            strikeLayer.load(xhr.responseText)
            root.placeStrikes()
        }
        xhr.open("GET", url)
        xhr.send()
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
        placeStrikes()
    }

    // Puts the strikes in the camera of the moment; until the next call they are carried with
    // the map like a frame.
    function placeStrikes() {
        if (!ready() || !frameTimes.length) {
            strikeLayer.placed = null
            return
        }
        var w = geoMap.width
        var a = screenMerc(0, 0)
        var b = screenMerc(w, 0)
        strikeLayer.project(a.x, a.y, b.x, b.y, w)
        strikeLayer.placed = { coord: geoMap.toCoordinate(Qt.point(0, 0), false),
                                zoom: geoMap.zoomLevel, bearing: geoMap.bearing }
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

    // The loop's own step forward fades; the wrap back to the oldest frame stays a cut, so the
    // restart shows, and so does every other change of frame: a seek pauses first.
    function step() {
        var next = (frame + 1) % frameCount
        if (next === 0 || fadeMs <= 0) {
            stopFade()
            frame = next
            return
        }
        fadeFrom = frame
        fade = 0
        fadeStart = Date.now()
        frame = next
        fadeTimer.restart()
    }

    function stopFade() {
        fadeTimer.stop()
        fadeFrom = -1
        fade = 1
    }

    onPlayingChanged: if (!playing) stopFade()
    onLatestOnlyChanged: {
        stopFade()
        if (latestOnly)
            frame = frameCount - 1
    }
    onFrameCountChanged: {
        stopFade()
        frame = frameCount - 1
        refreshFrames()
    }
    onFrameTimesChanged: fetchLightning()
    // Left alone again, it makes a list of its own at once: its refresh stood still meanwhile.
    onFollowChanged: if (!follow) refreshFrames()
    onHoldFetchChanged: if (!holdFetch) watch.moved()
    // Coming live refreshes the frame list: it is as old as the last refresh, and a view is
    // built in the background long before it is first opened.
    onActiveChanged: if (active) { refreshFrames(); check() }

    Binding {
        target: root
        property: "frameTimes"
        value: root.follow ? root.follow.frameTimes : []
        when: root.follow !== null
        restoreMode: Binding.RestoreNone
    }
    Binding {
        target: root
        property: "frame"
        value: root.follow ? root.follow.frame : 0
        when: root.follow !== null
        restoreMode: Binding.RestoreNone
    }
    Binding {
        target: root
        property: "fadeFrom"
        value: root.follow ? root.follow.fadeFrom : -1
        when: root.follow !== null
        restoreMode: Binding.RestoreNone
    }
    Binding {
        target: root
        property: "fade"
        value: root.follow ? root.follow.fade : 1
        when: root.follow !== null
        restoreMode: Binding.RestoreNone
    }

    MapCameraWatch {
        id: watch
        geoMap: root.geoMap
        onChanged: root.check()
    }

    Rectangle {
        anchors.fill: parent
        color: "black"
        opacity: root.dim
    }

    // The loop's pictures, one per frame, drawn by shownFrame below. Hidden, an Image still
    // hands its newest picture to a shader (QQuickImage keeps its texture provider current).
    Repeater {
        id: frames
        // The pictures made so far, for bindings on itemAt(). In a view built asynchronously
        // (ViewController) the Repeater makes them after `count` has changed, so `count` alone
        // left the shown frame null until the loop stepped, and for good with latestOnly.
        property int made: 0
        model: root.frameCount
        onItemAdded: made++
        onItemRemoved: made--

        Image {
            required property int index
            // The box this image's picture belongs to. A new box's picture replaces it only
            // once loaded, and until then the old one stays where it belongs on the map.
            property var shown: null
            source: root.latestOnly && index !== root.frameCount - 1
                    ? "" : root.frameUrl(root.frameTimes[index], root.view)
            retainWhileLoading: true
            visible: false
            asynchronous: true
            cache: true
            onStatusChanged: if (status === Image.Ready) shown = root.view
            // A picture already in the cache arrives without a status change.
            onSourceChanged: Qt.callLater(() => { if (status === Image.Ready) shown = root.view })
        }
    }

    // The frame on screen, with the one before blended in while a step fades
    // (resources/shaders/radarfade.frag): one draw, so a pixel both frames share keeps its
    // colour and the frames' opacity applies once. A fade needs both pictures to be of one box;
    // across a new box the step is a cut.
    ShaderEffect {
        id: shownFrame
        readonly property Item shownImage: {
            frames.made
            return frames.itemAt(root.frame)
        }
        readonly property Item fadingImage: {
            frames.made
            var image = root.fadeFrom >= 0 ? frames.itemAt(root.fadeFrom) : null
            return image && shownImage && image.shown === shownImage.shown ? image : null
        }
        readonly property var place: {
            if (!root.geoMap || !shownImage || !shownImage.shown)
                return null
            root.geoMap.center; root.geoMap.zoomLevel; root.geoMap.bearing; root.geoMap.width; root.geoMap.height
            return root.placement(shownImage.shown)
        }
        property variant previous: fadingImage || shownImage
        property variant current: shownImage
        property real progress: fadingImage ? root.fade : 1
        x: place ? place.x : 0
        y: place ? place.y : 0
        width: place ? shownImage.shown.w : 0
        height: place ? shownImage.shown.h : 0
        scale: place ? place.s : 1
        rotation: place ? place.r : 0
        transformOrigin: Item.TopLeft
        visible: place !== null
        opacity: root.frameOpacity
        fragmentShader: "qrc:/resources/shaders/radarfade.frag.qsb"
    }

    // Built in screen pixels for the camera of the moment (placeStrikes), then carried with the
    // map like a frame until the next.
    LightningLayer {
        id: strikeLayer
        width: root.width
        height: root.height
        visible: inArea > 0 && placed !== null
        area: root.view ? Qt.rect(root.view.seen.x0, root.view.seen.y0, root.view.seen.x1 - root.view.seen.x0,
                                  root.view.seen.y1 - root.view.seen.y0)
                        : Qt.rect(0, 0, 0, 0)
        firstFrameMs: root.frameTimes.length ? root.frameTimes[0].getTime() : 0
        stepMs: root.frameStepMin * 60000
        frameCount: root.frameTimes.length
        frame: root.frame
        // The camera at the last placing: the coordinate under the top-left corner, the zoom
        // and the bearing.
        property var placed: null
        readonly property var place: {
            if (!root.geoMap || !placed)
                return null
            root.geoMap.center; root.geoMap.zoomLevel; root.geoMap.bearing; root.geoMap.width; root.geoMap.height
            var p = root.geoMap.fromCoordinate(placed.coord, false)
            return { x: p.x, y: p.y, s: Math.pow(2, root.geoMap.zoomLevel - placed.zoom),
                     r: placed.bearing - root.geoMap.bearing }
        }
        x: place ? place.x : 0
        y: place ? place.y : 0
        scale: place ? place.s : 1
        rotation: place ? place.r : 0
        transformOrigin: Item.TopLeft
    }

    Timer {
        interval: root.frame === root.frameCount - 1 ? root.newestFrameMs : root.frameMs
        running: root.active && root.playing && !root.latestOnly && !root.follow && root.frameTimes.length > 0
        repeat: true
        onTriggered: root.step()
    }

    Timer {
        id: fadeTimer
        interval: 50
        repeat: true
        onTriggered: {
            var p = Math.min(1, (Date.now() - root.fadeStart) / root.fadeMs)
            root.fade = p * p * (3 - 2 * p)
            if (p >= 1)
                root.stopFade()
        }
    }

    Timer {
        interval: 5 * 60000
        running: root.active && !root.follow
        repeat: true
        onTriggered: root.refreshFrames()
    }

    Component.onCompleted: {
        refreshFrames()
        Qt.callLater(check)
    }
}

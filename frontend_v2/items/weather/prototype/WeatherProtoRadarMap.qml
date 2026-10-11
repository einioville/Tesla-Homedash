import QtQuick
import QtCore as QC
import QtLocation
import QtPositioning
import frontend_v2

// PROTOTYPE — FMI's live radar composite looping over the app's own basemap.
//
// The radar is a WMS layer in EPSG:3857, the projection our tiles already use, so each
// frame is one transparent PNG requested for exactly the map's pixel size and bounding
// box and laid straight over it. The map is static (no gestures): the bbox is computed
// once the map is ready, from its corner coordinates.
//
// The basemap here is EOX Sentinel-2, not the app's MML orthophoto: MML covers Finland only
// and answers everywhere else (sea, Sweden, Estonia) with a blank white tile, which a
// regional radar view runs into near any coast. At radar zoom, Sentinel-2's 10 m is plenty.
// It needs a tile cache of its own: the OSM plugin names cached tiles by plugin, map type
// and tile number but not by host, so sharing TeslaMap's would hand each map the other's
// imagery.
//
// Lightning comes from FMI's WFS (`fmi::observations::lightning::multipointcoverage`), not the
// WMS, which has no lightning layer: every detected strike since the first frame, fetched with
// the frames. Each frame draws its own 5-minute slot's strikes bright, and the earlier ones of
// the loop fading with age, so a storm leaves its track; the newest frame also takes the
// strikes since it, which arrive a few minutes before the radar does.
Item {
    id: root

    property real latitude: 61.499
    property real longitude: 23.787
    property real zoom: 7.6
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

    property int frame: frameCount - 1
    property bool playing: true
    property var frameTimes: []
    property string bbox: ""
    // The same bbox in EPSG:3857 metres and in degrees (the WFS wants lon,lat,lon,lat).
    property var bboxM: null
    property string bboxDeg: ""
    // Strikes as { x, y, t }: map pixels and epoch milliseconds.
    property var strikes: []
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
    property point placePt: Qt.point(-100, -100)
    readonly property date frameTime: frameTimes.length > frame ? frameTimes[frame] : new Date()

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
        if (!bboxM || !frameTimes.length)
            return
        if (demoLightning) {
            strikes = demoStrikes()
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
                + "&bbox=" + bboxDeg + "&starttime=" + iso(start) + "&endtime=" + iso(new Date())
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
            root.strikes = root.parseStrikes(xhr.responseText)
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
            var p = toPixel(Number(v[i]), Number(v[i + 1]))
            list.push({ x: p.x, y: p.y, t: Number(v[i + 2]) * 1000 })
        }
        return list
    }

    // Straight onto the radar's own bbox, so a strike lands on its echo exactly.
    function toPixel(lat, lon) {
        var m = merc({ latitude: lat, longitude: lon })
        return Qt.point((m.x - bboxM.x0) / (bboxM.x1 - bboxM.x0) * map.width,
                        (bboxM.y1 - m.y) / (bboxM.y1 - bboxM.y0) * map.height)
    }

    // A cell drifting from the south-west past home over the loop, a few strikes a minute.
    function demoStrikes() {
        var t0 = frameTimes[0].getTime() - frameStepMin * 60000
        var t1 = Date.now()
        var spread = () => Math.random() + Math.random() + Math.random() - 1.5
        var list = []
        for (var t = t0; t < t1; t += 60000) {
            var f = (t - t0) / (t1 - t0)
            var cx = placePt.x - 260 + 380 * f
            var cy = placePt.y + 150 - 210 * f
            for (var k = Math.floor(Math.random() * 4); k > 0; k--)
                list.push({ x: cx + spread() * 50, y: cy + spread() * 40, t: t + Math.random() * 60000 })
        }
        return list
    }

    onDemoLightningChanged: fetchLightning()
    onFrameChanged: strikeLayer.requestPaint()
    onStrikesChanged: strikeLayer.requestPaint()

    function merc(c) {
        var R = 6378137
        return { x: R * c.longitude * Math.PI / 180,
                 y: R * Math.log(Math.tan(Math.PI / 4 + c.latitude * Math.PI / 360)) }
    }

    function placeMap() {
        if (!map.mapReady || map.width <= 0 || map.height <= 0)
            return
        map.center = QtPositioning.coordinate(root.latitude, root.longitude)
        map.pan(-root.placeOffset.x, -root.placeOffset.y)
        var tlc = map.toCoordinate(Qt.point(0, 0), false)
        var brc = map.toCoordinate(Qt.point(map.width, map.height), false)
        var tl = merc(tlc)
        var br = merc(brc)
        bbox = tl.x + "," + br.y + "," + br.x + "," + tl.y
        bboxM = { x0: tl.x, y0: br.y, x1: br.x, y1: tl.y }
        bboxDeg = tlc.longitude + "," + brc.latitude + "," + brc.longitude + "," + tlc.latitude
        placePt = map.fromCoordinate(QtPositioning.coordinate(root.latitude, root.longitude), false)
        fetchLightning()
    }

    function frameUrl(d) {
        if (bbox === "")
            return ""
        return "https://openwms.fmi.fi/geoserver/Radar/wms?service=WMS&version=1.3.0&request=GetMap"
               + "&layers=" + radarLayer + "&styles=&crs=EPSG:3857&bbox=" + bbox
               + "&width=" + Math.round(map.width) + "&height=" + Math.round(map.height)
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
        onMapReadyChanged: Qt.callLater(root.placeMap)
        onWidthChanged: Qt.callLater(root.placeMap)
        onHeightChanged: Qt.callLater(root.placeMap)
    }

    // Darken the imagery so the radar colours carry the picture.
    Rectangle {
        anchors.fill: parent
        color: "black"
        opacity: root.dim
    }

    Repeater {
        model: root.frameTimes

        Image {
            required property int index
            required property var modelData
            anchors.fill: parent
            source: root.frameUrl(modelData)
            visible: index === root.frame
            asynchronous: true
            cache: true
        }
    }

    Canvas {
        id: strikeLayer
        anchors.fill: parent

        function bolt(ctx, x, y, s) {
            var pts = [[1.5, -8], [-4.5, 1], [-0.5, 1], [-2, 8], [4.5, -1.5], [0.5, -1.5]]
            ctx.beginPath()
            ctx.moveTo(x + pts[0][0] * s, y + pts[0][1] * s)
            for (var i = 1; i < pts.length; i++)
                ctx.lineTo(x + pts[i][0] * s, y + pts[i][1] * s)
            ctx.closePath()
            ctx.fill()
            ctx.stroke()
        }

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            if (!root.frameTimes.length)
                return
            var step = root.frameStepMin * 60000
            var f = root.frameTime.getTime()
            var end = root.frame === root.frameCount - 1 ? Infinity : f
            var trail = root.frameCount * step
            // A failed refresh leaves the last list in place; drop what has left the loop.
            var loopStart = root.frameTimes[0].getTime() - step
            ctx.lineJoin = "round"
            ctx.lineWidth = 1
            ctx.strokeStyle = "rgba(0, 0, 0, 0.7)"

            // Earlier strikes of the loop first, so this frame's draw on top of them.
            var fresh = []
            ctx.fillStyle = "#ffbf3d"
            for (var i = 0; i < root.strikes.length; i++) {
                var s = root.strikes[i]
                if (s.t > end || s.t <= loopStart)
                    continue
                if (s.t > f - step) {
                    fresh.push(s)
                    continue
                }
                ctx.globalAlpha = Math.max(0.2, 0.85 - 0.65 * (f - s.t) / trail)
                bolt(ctx, s.x, s.y, 0.75)
            }
            ctx.globalAlpha = 1
            for (var j = 0; j < fresh.length; j++) {
                var glow = ctx.createRadialGradient(fresh[j].x, fresh[j].y, 0, fresh[j].x, fresh[j].y, 14)
                glow.addColorStop(0, "rgba(255, 240, 150, 0.45)")
                glow.addColorStop(1, "rgba(255, 240, 150, 0)")
                ctx.fillStyle = glow
                ctx.beginPath()
                ctx.arc(fresh[j].x, fresh[j].y, 14, 0, 2 * Math.PI)
                ctx.fill()
                ctx.fillStyle = "#fff6b0"
                bolt(ctx, fresh[j].x, fresh[j].y, 1.15)
            }
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

        Rectangle {
            anchors.centerIn: parent
            width: 40
            height: 40
            radius: 20
            color: "transparent"
            border.color: "#80ffffff"
            border.width: 1
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

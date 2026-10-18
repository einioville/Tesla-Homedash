import QtQuick
import QtLocation
import QtPositioning
import frontend_v2

// OSM place names over a map's imagery, from the PlaceNames store (core/map/placenames.hh).
// Declare it inside the Map. The store answers by zoom (a hamlet only close up); here the
// names are placed most important first, and one whose box would overlap a name already
// placed is left out. Each is a MapQuickItem with no zoomLevel of its own, so it stays
// upright and screen-sized when the map turns heading-up — the fact the car arrow relies on
// (items/tesla/CLAUDE.md).
//
// The choice is made again when the map rests after moving, every 2 s while it keeps moving,
// and when a tile of names arrives; in between, the names ride with the map.
MapItemView {
    id: root

    // The Map it is declared in. Not `map`: a binding `map: map` can read this property itself.
    property Map geoMap: null
    property bool active: true
    property var labels: []
    // Font sizes by rank, a city first.
    readonly property var sizes: [20, 17, 15, 14, 13, 12, 12]
    // At most this many names at once; each is an item the map moves every frame.
    readonly property int maxLabels: 40

    model: active ? labels : []

    delegate: MapQuickItem {
        required property var modelData
        // Over the route and the radar, under the car.
        z: 3
        coordinate: QtPositioning.coordinate(modelData.lat, modelData.lon)
        anchorPoint.x: label.width / 2
        anchorPoint.y: label.height / 2
        sourceItem: Text {
            id: label
            text: modelData.name
            font.family: Theme.fontFamily
            font.pixelSize: root.sizeFor(modelData.rank)
            color: "white"
            style: Text.Outline
            styleColor: "#d0000000"
        }
    }

    function sizeFor(rank) {
        return sizes[Math.min(rank, sizes.length - 1)]
    }

    function sameLabels(a, b) {
        if (a.length !== b.length)
            return false
        for (var i = 0; i < a.length; i++)
            if (a[i].name !== b[i].name || a[i].lat !== b[i].lat || a[i].lon !== b[i].lon)
                return false
        return true
    }

    function relayout() {
        if (!active || !geoMap || !geoMap.mapReady || geoMap.width <= 0) {
            labels = []
            return
        }
        // A little past the screen on every side, so a name near an edge is there as the map
        // moves on; all four corners, so a turned map is covered.
        var w = geoMap.width
        var h = geoMap.height
        var pad = 0.15
        var x0 = -pad * w, x1 = (1 + pad) * w, y0 = -pad * h, y1 = (1 + pad) * h
        var corners = [Qt.point(x0, y0), Qt.point(x1, y0), Qt.point(x1, y1), Qt.point(x0, y1)]
                .map(p => geoMap.toCoordinate(p, false))
        var lats = corners.map(c => c.latitude)
        var lons = corners.map(c => c.longitude)
        var found = PlaceNames.query(Math.min(...lats), Math.min(...lons),
                                     Math.max(...lats), Math.max(...lons), geoMap.zoomLevel)
        found.sort((a, b) => a.rank - b.rank)

        var kept = []
        var boxes = []
        for (var i = 0; i < found.length && kept.length < maxLabels; i++) {
            var place = found[i]
            var p = geoMap.fromCoordinate(QtPositioning.coordinate(place.lat, place.lon), false)
            if (!isFinite(p.x) || p.x < x0 || p.x > x1 || p.y < y0 || p.y > y1)
                continue
            var size = sizeFor(place.rank)
            // The metrics are at 100 px; a few pixels' gap keeps neighbours apart.
            var bw = metrics.advanceWidth(place.name) * size / 100 + 12
            var bh = size * 1.3 + 6
            var box = { x0: p.x - bw / 2, x1: p.x + bw / 2, y0: p.y - bh / 2, y1: p.y + bh / 2 }
            if (boxes.some(o => box.x0 < o.x1 && box.x1 > o.x0 && box.y0 < o.y1 && box.y1 > o.y0))
                continue
            boxes.push(box)
            kept.push(place)
        }
        if (!sameLabels(kept, labels))
            labels = kept
    }

    onActiveChanged: relayout()

    property FontMetrics metrics: FontMetrics {
        font.family: Theme.fontFamily
        font.pixelSize: 100
    }

    property Connections camera: Connections {
        target: root.geoMap
        function onCenterChanged() { root.cameraMoved() }
        function onZoomLevelChanged() { root.cameraMoved() }
        function onBearingChanged() { root.cameraMoved() }
        function onWidthChanged() { root.cameraMoved() }
        function onHeightChanged() { root.cameraMoved() }
        function onMapReadyChanged() { root.relayout() }
    }

    property Connections store: Connections {
        target: PlaceNames
        function onRevisionChanged() { root.relayout() }
    }

    function cameraMoved() {
        if (!active)
            return
        settle.restart()
        if (!pace.running)
            pace.start()
    }

    property Timer settle: Timer {
        id: settle
        interval: 500
        onTriggered: root.relayout()
    }

    property Timer pace: Timer {
        id: pace
        interval: 2000
        onTriggered: root.relayout()
    }
}

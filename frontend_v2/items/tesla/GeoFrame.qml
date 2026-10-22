import QtQuick
import QtPositioning

// An item whose coordinates are EPSG:3857 metres east and south of `originCoordinate`, carried
// with a QtLocation Map: moved, scaled and turned with its camera. Declare it inside the Map and
// draw in it in metres (`local()`); a Shape in it is triangulated once and then only
// transformed, where a MapPolyline is rebuilt on every camera change — every frame on a map
// that follows the car. A stroke stays a fixed width on screen as a `cosmeticStroke`, which
// is never processed again (SpeedRoute), or by taking `px / pixelsPerMetre`, which has it
// processed again on every zoom change (WarningAreas).
Item {
    id: root

    // Not `map`: a binding `map: map` can read this property itself.
    property Item geoMap: null
    property var originCoordinate: null
    readonly property var origin: originCoordinate ? merc(originCoordinate.latitude, originCoordinate.longitude)
                                                   : null
    // Pixels per EPSG:3857 metre at zoom 0, measured off the map once it projects; the
    // projection's scale doubles with each zoom level.
    property real pixelsPerMetreAtZoom0: 0
    readonly property real pixelsPerMetre: geoMap ? pixelsPerMetreAtZoom0 * Math.pow(2, geoMap.zoomLevel) : 0

    readonly property var place: {
        if (!geoMap || !originCoordinate || pixelsPerMetre <= 0)
            return null
        geoMap.center; geoMap.zoomLevel; geoMap.bearing; geoMap.width; geoMap.height
        return geoMap.fromCoordinate(originCoordinate, false)
    }
    visible: place !== null
    x: place ? place.x : 0
    y: place ? place.y : 0
    scale: pixelsPerMetre
    rotation: geoMap ? -geoMap.bearing : 0
    transformOrigin: Item.TopLeft

    function merc(lat, lon) {
        var R = 6378137
        return { x: R * lon * Math.PI / 180,
                 y: R * Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) }
    }

    function unmerc(x, y) {
        var R = 6378137
        return QtPositioning.coordinate((2 * Math.atan(Math.exp(y / R)) - Math.PI / 2) * 180 / Math.PI,
                                        x / R * 180 / Math.PI)
    }

    // A place in this item's coordinates: metres east and south of the origin.
    function local(lat, lon) {
        var m = merc(lat, lon)
        return Qt.point(m.x - origin.x, origin.y - m.y)
    }

    function measure() {
        if (pixelsPerMetreAtZoom0 > 0 || !geoMap || !geoMap.mapReady || geoMap.width <= 0)
            return
        var c = geoMap.toCoordinate(Qt.point(geoMap.width / 2, geoMap.height / 2), false)
        var m = merc(c.latitude, c.longitude)
        var a = geoMap.fromCoordinate(c, false)
        var b = geoMap.fromCoordinate(unmerc(m.x + 1000, m.y), false)
        pixelsPerMetreAtZoom0 = Math.hypot(b.x - a.x, b.y - a.y) / 1000 / Math.pow(2, geoMap.zoomLevel)
    }

    Connections {
        target: root.geoMap
        function onMapReadyChanged() { root.measure() }
    }

    Component.onCompleted: measure()
}

import QtQuick
import QtLocation
import QtPositioning
import frontend_v2

// Fintraffic's road weather cameras (RoadCameraStations) as markers on a TeslaMap: those in
// view from zoom 9, at most 60 and none on top of another, each a MapQuickItem with no zoomLevel
// so it stays upright. A tap asks for the camera whole (`opened(stationId)`, RoadCameraPopup).
// Declare it inside the Map. Which show is decided again when the map rests and every 2 s while
// it moves (MapCameraWatch).
MapItemView {
    id: root

    // Not `map`: a binding `map: map` can read this property itself.
    property Map geoMap: null
    property bool active: true
    // The cameras on the map, out of the whole list.
    property var shown: []
    readonly property real minimumZoom: 9
    readonly property int maxMarkers: 60
    readonly property real spacing: 30

    signal opened(string stationId)

    model: active ? shown : []

    delegate: MapQuickItem {
        id: marker
        required property var modelData
        // Over the names, under the car.
        z: 4
        coordinate: QtPositioning.coordinate(modelData.lat, modelData.lon)
        anchorPoint.x: 17
        anchorPoint.y: 17
        sourceItem: Rectangle {
            width: 34
            height: 34
            radius: 17
            color: tap.pressed ? "#e62a3038" : "#cc161a20"
            border.color: "#99ffffff"
            border.width: 1

            TintedIcon {
                anchors.centerIn: parent
                iconSize: 18
                source: "qrc:/resources/icons/camera.svg"
            }
            MouseArea {
                id: tap
                anchors.fill: parent
                anchors.margins: -6
                onClicked: root.opened(marker.modelData.id)
            }
        }
    }

    function relayout() {
        if (!active || !geoMap || !geoMap.mapReady || geoMap.zoomLevel < minimumZoom) {
            if (shown.length)
                shown = []
            return
        }
        // A little past the screen, all four corners, so a turned map is covered.
        var w = geoMap.width
        var h = geoMap.height
        var corners = [Qt.point(-0.1 * w, -0.1 * h), Qt.point(1.1 * w, -0.1 * h),
                       Qt.point(1.1 * w, 1.1 * h), Qt.point(-0.1 * w, 1.1 * h)]
                .map(p => geoMap.toCoordinate(p, false))
        var lats = corners.map(c => c.latitude)
        var lons = corners.map(c => c.longitude)
        var south = Math.min(...lats), north = Math.max(...lats)
        var west = Math.min(...lons), east = Math.max(...lons)
        // A marker within `spacing` of one already placed would hide it: in a town, several
        // cameras sit at one junction.
        var inView = []
        var placed = []
        for (var s of list.stations) {
            if (inView.length >= maxMarkers)
                break
            if (s.lat < south || s.lat > north || s.lon < west || s.lon > east)
                continue
            var p = geoMap.fromCoordinate(QtPositioning.coordinate(s.lat, s.lon), false)
            if (placed.some(q => Math.hypot(q.x - p.x, q.y - p.y) < spacing))
                continue
            placed.push(p)
            inView.push(s)
        }
        if (inView.length !== shown.length || inView.some((s, i) => s.id !== shown[i].id))
            shown = inView
    }

    onActiveChanged: if (active) relayout()

    property RoadCameraStations list: RoadCameraStations {
        active: root.active
        onStationsChanged: root.relayout()
    }

    property MapCameraWatch watch: MapCameraWatch {
        geoMap: root.geoMap
        active: root.active
        restMs: 500
        paceMs: 2000
        onChanged: root.relayout()
    }
}

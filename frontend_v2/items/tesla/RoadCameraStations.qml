import QtQuick

// Fintraffic's road weather cameras that are taking pictures (Digitraffic, CC BY 4.0), as
// { id, lat, lon }: the whole list (~800 cameras, 37 kB gzipped) fetched when `active` comes on
// and every six hours while it stays on — cameras are added and moved rarely. RoadCameras draws
// them on a map; the Weather view steps through the nearest ones (`nearest`).
QtObject {
    id: root

    property bool active: true
    property var stations: []

    function fetch() {
        var xhr = new XMLHttpRequest()
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE)
                return
            if (xhr.status !== 200) {
                console.warn("Road camera list fetch failed: HTTP", xhr.status)
                return
            }
            root.stations = JSON.parse(xhr.responseText).features
                .filter(f => f.properties.collectionStatus === "GATHERING")
                .map(f => ({ id: f.id, lat: f.geometry.coordinates[1], lon: f.geometry.coordinates[0] }))
        }
        xhr.open("GET", "https://tie.digitraffic.fi/api/weathercam/v1/stations")
        xhr.setRequestHeader("Digitraffic-User", "Tesla-Homedash")
        xhr.send()
    }

    // The `count` cameras nearest to a place, nearest first, as { id, km }.
    function nearest(lat, lon, count) {
        var rad = Math.PI / 180
        return stations.map(s => {
            // Haversine, on a 6371 km sphere.
            var a = Math.pow(Math.sin((s.lat - lat) * rad / 2), 2)
                  + Math.cos(lat * rad) * Math.cos(s.lat * rad) * Math.pow(Math.sin((s.lon - lon) * rad / 2), 2)
            return { id: s.id, km: 2 * 6371 * Math.asin(Math.sqrt(a)) }
        }).sort((a, b) => a.km - b.km).slice(0, count)
    }

    onActiveChanged: if (active && !stations.length) fetch()
    Component.onCompleted: if (active) fetch()

    property Timer refresh: Timer {
        interval: 6 * 60 * 60 * 1000
        running: root.active
        repeat: true
        onTriggered: root.fetch()
    }
}

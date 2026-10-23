pragma Singleton
import QtQuick

// Fintraffic's road weather cameras that are taking pictures (Digitraffic, CC BY 4.0), as
// { id, lat, lon }: the whole list (~800 cameras, 37 kB gzipped), one per display for every map
// and view that shows them. `ensure()` fetches it when a user comes live and it is missing or
// six hours old — cameras are added and moved rarely. RoadCameras draws them on a map; the
// Weather view steps through the nearest ones (`nearest`).
//
// Fetched here, not by the backend: only a display showing cameras wants the list, and the
// pictures and readings a tap opens come straight from Digitraffic too (root CLAUDE.md §5.4).
QtObject {
    id: root

    property var stations: []
    property real fetchedMs: 0
    property var xhr: null
    readonly property real maxAgeMs: 6 * 60 * 60 * 1000

    function ensure() {
        if (xhr || (stations.length && Date.now() - fetchedMs < maxAgeMs))
            return
        var request = new XMLHttpRequest()
        xhr = request
        request.onreadystatechange = function () {
            if (request.readyState !== XMLHttpRequest.DONE)
                return
            root.xhr = null
            if (request.status !== 200) {
                console.warn("Road camera list fetch failed: HTTP", request.status)
                return
            }
            try {
                root.stations = JSON.parse(request.responseText).features
                    .filter(f => f.properties.collectionStatus === "GATHERING")
                    .map(f => ({ id: f.id, lat: f.geometry.coordinates[1], lon: f.geometry.coordinates[0] }))
                root.fetchedMs = Date.now()
            } catch (e) {
                console.warn("Road camera list unreadable:", e)
            }
        }
        request.open("GET", "https://tie.digitraffic.fi/api/weathercam/v1/stations")
        request.setRequestHeader("Digitraffic-User", "Tesla-Homedash")
        request.send()
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
}

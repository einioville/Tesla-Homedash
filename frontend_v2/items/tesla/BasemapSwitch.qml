import QtQuick
import QtLocation
import frontend_v2
import "MapCoverage.js" as Coverage

// Shows MML's orthophoto on `geoMap` while all of the view lies inside its coverage
// (MapCoverage.js) and EOX's imagery everywhere else (#59): outside Finland MML answers with
// blank white tiles, which no map underneath could show through. A grid of points over the view
// is tested, so a corner of open sea between two inside corners still counts. Decided when the
// map rests, since a new type reloads every tile on screen, and every 2 s while it keeps moving.
// Without an MML key (BasemapPlugin), or with `allowMml` off, it is EOX everywhere.
Item {
    id: root

    // Not `map`: a binding `map: map` can read this property itself.
    property Map geoMap: null
    property bool active: true
    // Off for the Weather view's radar map: the backdrop to a radar reaching past Finland.
    property bool allowMml: true
    readonly property bool hasMml: allowMml && App.mapTilesUrl !== ""
    // Points per side of the grid tested over the view.
    readonly property int samples: 6

    // Before the map can project, MML is assumed: the car is in Finland nearly always, and
    // starting on the other type would fetch a screenful of tiles only to replace them.
    function covered() {
        if (!geoMap.mapReady || geoMap.width <= 0 || geoMap.height <= 0)
            return true
        for (var i = 0; i < samples; i++) {
            for (var j = 0; j < samples; j++) {
                var c = geoMap.toCoordinate(Qt.point(geoMap.width * i / (samples - 1),
                                                     geoMap.height * j / (samples - 1)), false)
                if (!c.isValid || !Coverage.covers(c.latitude, c.longitude))
                    return false
            }
        }
        return true
    }

    function choose() {
        if (!geoMap)
            return
        var style = hasMml && covered() ? MapType.CustomMap : MapType.SatelliteMapDay
        if (geoMap.activeMapType.style === style)
            return
        var types = geoMap.supportedMapTypes
        for (var i = 0; i < types.length; i++) {
            if (types[i].style === style) {
                geoMap.activeMapType = types[i]
                return
            }
        }
    }

    Component.onCompleted: choose()

    Connections {
        target: root.geoMap
        function onSupportedMapTypesChanged() { root.choose() }
    }

    MapCameraWatch {
        geoMap: root.geoMap
        active: root.active
        restMs: 500
        paceMs: 2000
        onChanged: root.choose()
    }
}

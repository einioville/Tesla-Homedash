import QtQuick

// The cue to redo work that depends on a map's view — fetching for it, choosing what shows in
// it — without redoing it every frame of a map that follows the car: `changed()` fires once
// the camera of `geoMap` has rested `restMs`, and every `paceMs` while it keeps moving.
// RadarLayer, PlaceLabels and RoadCameras watch their map with one.
Item {
    id: root

    // Not `map`: a binding `map: map` can read this property itself.
    property Item geoMap: null
    property bool active: true
    property int restMs: 400
    property int paceMs: 1500

    signal changed()

    function moved() {
        if (!active)
            return
        rest.restart()
        if (!pace.running)
            pace.start()
    }

    Connections {
        target: root.geoMap
        function onCenterChanged() { root.moved() }
        function onZoomLevelChanged() { root.moved() }
        function onBearingChanged() { root.moved() }
        function onWidthChanged() { root.moved() }
        function onHeightChanged() { root.moved() }
        function onMapReadyChanged() { root.changed() }
    }

    Timer {
        id: rest
        interval: root.restMs
        onTriggered: root.changed()
    }

    Timer {
        id: pace
        interval: root.paceMs
        onTriggered: root.changed()
    }
}

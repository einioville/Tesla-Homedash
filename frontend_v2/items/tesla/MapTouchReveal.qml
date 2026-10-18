import QtQuick

// When a map's own controls show over a map that should mostly be left to itself — the
// dashboard's card: `shown` rises when the map is touched or a control is used (poke()), and
// falls `hideAfterMs` after the last touch unless `hold` (a menu left open).
Item {
    id: root

    property Item teslaMap: null
    property int hideAfterMs: 4000
    property bool hold: false
    property bool shown: false

    function poke() {
        shown = true
        hideTimer.restart()
    }

    onHoldChanged: if (!hold) hideTimer.restart()

    Connections {
        target: root.teslaMap
        function onTouched() { root.poke() }
    }

    Timer {
        id: hideTimer
        interval: root.hideAfterMs
        onTriggered: if (!root.hold) root.shown = false
    }
}

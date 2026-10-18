import QtQuick
import frontend_v2

// Zoom in and out on a TeslaMap: + over − on one glass pill. A step is a whole zoom level and
// becomes the default zoom (TeslaMap.stepZoom), so the map stays there after a gesture's
// snap-back, and the other map follows.
//
// `autoHide` keeps it out of sight until the map is touched and fades it away again
// `hideAfterMs` after the last touch — the dashboard's card, where it would cover the map for
// nothing most of the time. Hidden, it takes no input, so the map under it pans as usual.
GlassPanel {
    id: root

    // Not `map`: a binding `map: map` would read this property itself.
    property Item teslaMap: null
    property bool autoHide: false
    property int hideAfterMs: 4000
    property bool shown: !autoHide

    width: 56
    height: 112
    radius: 28
    rimWidth: 0.75
    highlight: false
    backdropSource: teslaMap
    backdropOrigin: Qt.point(x - (teslaMap ? teslaMap.x : 0), y - (teslaMap ? teslaMap.y : 0))
    active: visible
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }

    function poke() {
        if (!autoHide)
            return
        shown = true
        hideTimer.restart()
    }

    Timer {
        id: hideTimer
        interval: root.hideAfterMs
        onTriggered: root.shown = false
    }

    Connections {
        target: root.teslaMap
        function onTouched() { root.poke() }
    }

    component Step: Item {
        id: step
        property url icon
        property int direction
        width: root.width
        height: root.height / 2

        Rectangle {
            anchors.centerIn: parent
            width: 44
            height: 44
            radius: 22
            color: "#26ffffff"
            visible: tap.pressed
        }
        TintedIcon {
            anchors.centerIn: parent
            iconSize: 24
            source: step.icon
        }
        MouseArea {
            id: tap
            anchors.fill: parent
            onClicked: {
                root.teslaMap.stepZoom(step.direction)
                root.poke()
            }
        }
    }

    Column {
        Step { icon: "qrc:/resources/icons/plus.svg"; direction: 1 }
        Step { icon: "qrc:/resources/icons/minus.svg"; direction: -1 }
    }

    Rectangle {
        anchors.centerIn: parent
        width: 24
        height: 1
        color: "#40ffffff"
    }
}

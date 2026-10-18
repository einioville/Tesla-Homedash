import QtQuick
import frontend_v2

// Zoom in and out on a TeslaMap: + over − on one glass pill. A step is a whole zoom level and
// becomes the default zoom (TeslaMap.stepZoom), so the map stays there after a gesture's
// snap-back, and the other map follows.
//
// `shown` fades it in and out (the dashboard's card shows it on a touch, MapTouchReveal);
// hidden, it takes no input, so the map under it pans as usual. `used()` on every step.
GlassPanel {
    id: root

    // Not `map`: a binding `map: map` would read this property itself.
    property Item teslaMap: null
    property bool shown: true

    signal used()

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
                root.used()
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

import QtQuick
import QtQuick.Effects

// Image with rounded corners (the Widgets cover-art clip-to-rounded-rect).
// The image is masked by a rounded Rectangle through MultiEffect — the
// canonical Qt 6 rounded-image recipe (no Qt5Compat dependency).
Item {
    id: root

    property alias source: img.source
    property int radius: 5
    property int fillMode: Image.PreserveAspectFit

    Image {
        id: img
        anchors.fill: parent
        fillMode: root.fillMode
        sourceSize.width: width
        sourceSize.height: height
        smooth: true
        asynchronous: true
        visible: false
    }

    Rectangle {
        id: mask
        anchors.fill: parent
        radius: root.radius
        visible: false
        layer.enabled: true
    }

    MultiEffect {
        anchors.fill: img
        source: img
        maskEnabled: true
        maskSource: mask
    }
}

import QtQuick
import frontend_v2

Rectangle {
    id: icon

    property bool selected: false
    property string label: ""
    // White (Theme.iconTint) icon shown on the dock tile; empty = no icon.
    property url source
    signal clicked()

    implicitWidth: Theme.iconSize
    implicitHeight: Theme.iconSize
    radius: Theme.iconRadius
    // Transparent tile: the dock's frosted glass is the background, so the button
    // is just the white glyph (Theme.iconPlaceholder was a stand-in for the icon).
    color: "transparent"

    border.width: selected ? 3 : 0
    border.color: Theme.accent

    Accessible.role: Accessible.Button
    Accessible.name: label
    Accessible.onPressAction: icon.clicked()

    scale: tap.pressed ? 0.92 : 1.0
    Behavior on scale {
        ScaleAnimator { duration: Theme.pressDuration; easing.type: Easing.OutQuad }
    }

    TintedIcon {
        anchors.centerIn: parent
        iconSize: Math.round(icon.width * 0.56)
        source: icon.source
        tint: Theme.iconTint
        visible: icon.source.toString() !== ""
    }

    MouseArea {
        id: tap
        anchors.fill: parent
        onClicked: icon.clicked()
    }
}

import QtQuick
import frontend_v2

// PROTOTYPE — the Weather view's card: a translucent panel with a small caps title on the
// left and a note on the right. Children are laid over it.
Rectangle {
    property string title
    property string note

    color: "#12ffffff"
    border.color: "#24ffffff"
    border.width: 1
    radius: 14

    Text {
        x: 14
        y: 10
        text: parent.title
        color: "#8f9aa6"
        font.family: Theme.fontFamily
        font.pixelSize: 12
        font.letterSpacing: 1.2
        z: 2
    }
    Text {
        anchors.right: parent.right
        anchors.rightMargin: 14
        y: 10
        text: parent.note
        color: "#6f7a86"
        font.family: Theme.fontFamily
        font.pixelSize: 12
        z: 2
    }
}

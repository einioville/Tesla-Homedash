import QtQuick
import frontend_v2

// The card every dashboard panel and the Weather view are built from: a faint
// translucent panel with a hairline rim, a small caps title on the left and a note
// on the right (either may be left empty). Children are laid over it.
Rectangle {
    property string title
    property string note

    color: Theme.cardFill
    border.color: Theme.cardBorder
    border.width: 1
    radius: Theme.cardRadius

    Text {
        x: 14
        y: 10
        text: parent.title
        color: Theme.cardTitle
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
        color: Theme.cardNote
        font.family: Theme.fontFamily
        font.pixelSize: 12
        z: 2
    }
}

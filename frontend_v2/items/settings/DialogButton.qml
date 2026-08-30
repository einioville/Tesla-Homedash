import QtQuick
import frontend_v2

// One pill button for SpotifyAuthPopup. Matches the Options view's combo styling
// (TripComboBox's field colours) so the dialog reads as part of the same screen.
Rectangle {
    id: control

    property alias label: text.text
    signal activated

    implicitWidth: text.implicitWidth + 30
    implicitHeight: 34
    radius: 8
    color: area.pressed ? Theme.tripComboPressed : Theme.tripComboBg
    border.width: 1
    border.color: Theme.tripCardBorder

    Text {
        id: text
        anchors.centerIn: parent
        font.family: Theme.fontFamily
        font.pixelSize: 13
        color: Theme.dataLabelValue
    }

    MouseArea {
        id: area
        anchors.fill: parent
        onClicked: control.activated()
    }
}

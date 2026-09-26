import QtQuick
import frontend_v2

// One pill button for the Options view's dialogs (SpotifyAuthPopup,
// UsbImportPopup). Matches the view's combo styling (TripComboBox's field
// colours) so a dialog reads as part of the same screen; `primary` tints the one
// action a dialog exists for in the accent.
Rectangle {
    id: control

    property alias label: text.text
    property bool primary: false
    signal activated

    implicitWidth: text.implicitWidth + 30
    implicitHeight: 34
    radius: 8
    color: control.primary ? (area.pressed ? "#994aa8ff" : "#664aa8ff")
                           : (area.pressed ? Theme.tripComboPressed : Theme.tripComboBg)
    border.width: 1
    border.color: control.primary ? Theme.accent : Theme.tripCardBorder

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

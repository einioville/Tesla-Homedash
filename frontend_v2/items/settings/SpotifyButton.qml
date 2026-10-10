import QtQuick
import frontend_v2

// One pill button in Spotify's own button language, for the device-identification
// dialog: a solid green `primary` carrying dark text, or an outlined secondary
// carrying white. Both are full pills and both dip on press — Spotify's controls
// scale rather than only changing colour, and on a touch panel the dip is the
// clearer of the two signals because a fingertip covers the colour.
//
// Deliberately NOT a restyle of DialogButton.qml. That one belongs to the
// re-authorization dialog, which sits over the dashboard rather than over this
// Spotify-branded card, and quietly restyling a screen nobody asked about is how
// two dialogs end up drifting for reasons no one can reconstruct later.
Rectangle {
    id: control

    property alias label: buttonLabel.text
    // The one action the dialog is steering towards. At most one per row.
    property bool primary: false
    signal activated

    implicitWidth: buttonLabel.implicitWidth + 44
    implicitHeight: 40
    // A full pill, which is the shape Spotify uses for every control of this size.
    radius: height / 2

    color: !control.primary
           ? "transparent"
           : (area.pressed ? Qt.darker(Theme.spotifyGreen, 1.2) : Theme.spotifyGreen)
    // The secondary is an outline; the primary needs no rim over its own fill.
    border.width: control.primary ? 0 : 1
    border.color: area.pressed ? Theme.dataLabelValue : Theme.spotifyOutline

    scale: area.pressed ? 0.96 : 1.0
    Behavior on scale { NumberAnimation { duration: Theme.pressDuration } }
    Behavior on color { ColorAnimation { duration: Theme.pressDuration } }
    Behavior on border.color { ColorAnimation { duration: Theme.pressDuration } }

    Text {
        id: buttonLabel
        anchors.centerIn: parent
        font.family: Theme.fontFamily
        font.pixelSize: 14
        // The bundled font ships a single weight, so this is Qt's synthesized
        // embolden — enough to carry the weight Spotify's buttons have.
        font.bold: true
        // Dark text on the green fill: that pairing is the whole point of the
        // brand green, and white on it fails contrast badly.
        color: control.primary ? Theme.spotifyBase : Theme.dataLabelValue
    }

    MouseArea {
        id: area
        anchors.fill: parent
        // `enabled` propagates down the item tree, so a disabled button also
        // stops reporting `pressed` and therefore stops dipping.
        onClicked: control.activated()
    }
}

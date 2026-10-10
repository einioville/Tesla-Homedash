import QtQuick
import frontend_v2

// The frame every dialog shares: a scrim that takes every press and wheel turn
// that misses the card, so nothing underneath can be operated while it is open,
// and an opaque card that holds the content. A MouseArea with no wheel handler
// lets the wheel through, which scrolled the view behind an open dialog; a list
// inside the card still scrolls, since it sits above the scrim.
//
// Children go into the card. A dialog sets `cardHeight`, and `cardTopMargin` to
// hang the card under the header instead of centring it: a dialog inside a view
// cannot cover the dock (y 684–780 on the target), so a tall one is top-anchored.
Item {
    id: dialog

    default property alias content: card.data
    property alias card: card
    property real cardWidth: 600
    property real cardHeight: 0
    // From the top of the dialog; negative centres the card.
    property real cardTopMargin: -1
    // Lighter than a blackout: SettingsView blurs its content behind a dialog,
    // and at a near-opaque tint the blur would be invisible.
    property color scrimColor: Theme.dialogScrim
    // Opaque: a card the blurred view shows through smears that backdrop into
    // its own content.
    property color cardColor: Theme.spotifySurface
    property color cardBorderColor: Theme.spotifyRim

    // A press on the scrim, beside the card.
    signal scrimClicked()

    anchors.fill: parent
    z: 100

    MouseArea {
        anchors.fill: parent
        onWheel: (wheel) => wheel.accepted = true
        preventStealing: true
        onClicked: dialog.scrimClicked()
    }

    Rectangle {
        anchors.fill: parent
        color: dialog.scrimColor
    }

    Rectangle {
        id: card
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: dialog.cardTopMargin < 0 ? parent.verticalCenter : undefined
        anchors.top: dialog.cardTopMargin < 0 ? undefined : parent.top
        anchors.topMargin: Math.max(0, dialog.cardTopMargin)
        width: Math.min(parent.width - 2 * Theme.gridMargin, dialog.cardWidth)
        height: dialog.cardHeight
        radius: Theme.tripCardRadius
        color: dialog.cardColor
        border.width: 1
        border.color: dialog.cardBorderColor

        // A press on the card is not a press on the scrim.
        MouseArea {
            anchors.fill: parent
        }
    }
}

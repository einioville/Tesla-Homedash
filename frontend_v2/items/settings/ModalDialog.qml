import QtQuick
import frontend_v2

// The frame every dialog shares: a scrim that takes every press and wheel turn
// that misses the card, so nothing underneath can be operated while it is open,
// and an opaque card that holds the content. The scrim takes the wheel
// explicitly: a MouseArea with no wheel handler lets it through to the view
// behind. A list inside the card still scrolls, since it sits above the scrim.
//
// Children go into the card. A dialog sets `cardHeight`, and `cardTopMargin` to
// hang the card under the header instead of centring it: a tall one is
// top-anchored, clear of the menu's swipe-up strip along the bottom edge
// (Main.qml), where an upward drag in a list would open the menu instead.
//
// Over a map nothing blurs the view behind, so a dialog there gives a `backdrop` and its card is
// frosted glass over it (GlassPanel) instead of opaque; `frost` is the backdrop's shared
// FrostLayer. The backdrop is a sibling of the dialog, never its parent.
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
    property Item backdrop: null
    property Item frost: null

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

    GlassPanel {
        visible: dialog.backdrop !== null
        x: card.x
        y: card.y
        width: card.width
        height: card.height
        radius: card.radius
        backdropSource: dialog.backdrop
        backdropOrigin: dialog.backdrop ? Qt.point(dialog.x + card.x - dialog.backdrop.x,
                                                   dialog.y + card.y - dialog.backdrop.y)
                                        : Qt.point(0, 0)
        frost: dialog.frost
        active: dialog.visible
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
        color: dialog.backdrop ? "transparent" : dialog.cardColor
        border.width: dialog.backdrop ? 0 : 1
        border.color: dialog.cardBorderColor

        // A press on the card is not a press on the scrim.
        MouseArea {
            anchors.fill: parent
        }
    }
}

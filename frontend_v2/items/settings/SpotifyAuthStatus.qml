import QtQuick
import frontend_v2

// Grant state for the Spotify card (SettingsPane renders it from the subsection's
// `status: "spotifyAuth"` key).
//
// Worth its own line rather than being folded into the action row's help text:
// "authorized" is a fact about the token cache on the backend, which changes
// without anyone touching this screen — the grant expires, or someone runs the
// CLI helper on the box.
Item {
    id: status

    implicitHeight: line.implicitHeight + 6

    Row {
        id: line
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 8
            height: 8
            radius: 4
            color: SpotifyAuth.authorized ? "#4ade80" : "#ffb020"
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, line.width - 20)
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: 11
            color: SpotifyAuth.authorized ? Theme.dataLabelTitle : "#ffd48a"
            text: SpotifyAuth.authorized
                  ? qsTr("Tunnistautunut") + (SpotifyAuth.reason.length > 0
                                              ? " · " + SpotifyAuth.reason : "")
                  : (SpotifyAuth.reason.length > 0 ? SpotifyAuth.reason
                                                   : qsTr("Ei tunnistautumista"))
        }
    }
}

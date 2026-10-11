import QtQuick
import frontend_v2

// "Your Spotify authorization has stopped working" — raised over whatever view is
// on screen, not just the Options view.
//
// It exists because the failure is SCHEDULED, not exceptional: Spotify's
// refresh tokens last 6 months and refreshing does not extend them, so every
// deployment loses its grant about twice a year. Without this the dashboard just
// goes quiet — the media card stops updating and nothing says why.
//
// The backend raises it (`needsReauth` on SPOTIFY_AUTH_STATUS) the moment the
// player is actually refused, so this is never a guess made from a cache file.
ModalDialog {
    id: alert

    visible: SpotifyAuth.alertVisible

    // Lighter than the dialogs' scrim: the dashboard stays legible behind it, since
    // this reports a problem rather than demanding a decision.
    scrimColor: "#aa000000"
    cardWidth: 480
    cardHeight: column.implicitHeight + 48
    cardColor: Theme.tripCardBg
    cardBorderColor: Theme.tripCardBorder

    // Ignore. Deliberately a plain glyph in the corner rather than a second
    // pill button, so it never competes with the action below it.
    Item {
        id: closeButton
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 8
        width: 34
        height: 34
        z: 1

        Text {
            anchors.centerIn: parent
            text: "✕"
            font.family: Theme.fontFamily
            font.pixelSize: 15
            color: closeArea.pressed ? Theme.dataLabelValue : Theme.dataLabelTitle
        }

        MouseArea {
            id: closeArea
            anchors.fill: parent
            onClicked: SpotifyAuth.dismissAlert()
        }
    }

    Column {
        id: column
        anchors.centerIn: parent
        width: parent.width - 52
        spacing: 14

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: qsTr("Spotify-valtuutus vanhentunut")
            font.family: Theme.fontFamily
            font.pixelSize: 19
            color: Theme.dataLabelValue
        }

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: 13
            color: "#ffd48a"
            // The backend's own reason when it has one — it distinguishes an
            // expired grant from a revoked one from a missing one — with a
            // generic line only as a fallback.
            text: SpotifyAuth.reason.length > 0
                  ? SpotifyAuth.reason
                  : qsTr("Spotify-valtuutus ei ole enää voimassa.")
        }

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: 13
            color: Theme.dataLabelTitle
            text: qsTr("Spotifyn ohjaus ei toimi ennen kuin luot uuden valtuutuksen. " +
                       "Kirjautumissivu avautuu selaimeen tälle näytölle.")
        }

        DialogButton {
            anchors.horizontalCenter: parent.horizontalCenter
            label: qsTr("Luo uusi valtuutus")
            // Exactly what the Options view's button does — same flow, same
            // progress dialog, which is app-global for this reason.
            onActivated: SpotifyAuth.begin()
        }
    }
}

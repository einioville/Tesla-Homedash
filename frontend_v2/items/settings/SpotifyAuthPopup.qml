import QtQuick
import frontend_v2

// Spotify re-authorization, as a small modal dialog over the dashboard.
//
// This used to host the project's only WebEngineView, rendering Spotify's consent
// page inline. It no longer renders anything: the BACKEND opens the page in the
// host's real browser and catches the redirect on its own loopback listener
// (RFC 8252 §7.3), so all this screen has to do is report progress and get out of
// the way. Two reasons that is not a downgrade:
//
//  - RFC 8252 §8.12 says a native app MUST NOT use an embedded user-agent for
//    authorization — it can read the user's password keystrokes and lift session
//    cookies — and Spotify enforces that with a reCAPTCHA gate the embedded view
//    could never pass, even once WebGL and compositing were both working.
//  - It takes Qt WebEngine (an entire Chromium, ~200 MB) out of the build.
//
// No code, access token or refresh token ever reaches this side; the dialog only
// ever learns "started" and "finished".
Item {
    id: popup

    anchors.fill: parent
    visible: SpotifyAuth.phase !== "idle"
    z: 400

    readonly property bool busy: SpotifyAuth.phase === "requesting" ||
                                 SpotifyAuth.phase === "consent"
    readonly property bool succeeded: SpotifyAuth.phase === "done"
    readonly property bool failed: SpotifyAuth.phase === "error"

    // Swallows every tap that misses the card, so the dashboard underneath cannot
    // be operated while a flow is running.
    MouseArea {
        anchors.fill: parent
        preventStealing: true
        onClicked: {}
    }

    Rectangle {
        anchors.fill: parent
        color: "#cc000000"
    }

    Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(parent.width - 2 * Theme.gridMargin, 460)
        height: column.implicitHeight + 44
        radius: Theme.tripCardRadius
        color: Theme.tripCardBg
        border.width: 1
        border.color: Theme.tripCardBorder

        Column {
            id: column
            anchors.centerIn: parent
            width: parent.width - 44
            spacing: 14

            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("Spotify-tunnistautuminen")
                font.family: Theme.fontFamily
                font.pixelSize: 19
                color: Theme.dataLabelValue
            }

            // State glyph. The pulse is the only motion on the card, so "still
            // working" reads at a glance from across the room.
            Text {
                id: glyph
                anchors.horizontalCenter: parent.horizontalCenter
                font.family: Theme.fontFamily
                font.pixelSize: 40
                text: popup.succeeded ? "✓" : popup.failed ? "!" : "…"
                color: popup.succeeded ? "#4ade80"
                     : popup.failed ? "#f87171" : Theme.dataLabelTitle

                SequentialAnimation on opacity {
                    running: popup.busy
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutQuad }
                    NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutQuad }
                }
                // The animation leaves opacity wherever it stopped, so it has to be
                // put back explicitly once the flow settles.
                onOpacityChanged: if (!popup.busy && opacity !== 1.0) opacity = 1.0
            }

            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily
                font.pixelSize: 13
                color: popup.failed ? "#ffd48a" : Theme.dataLabelTitle
                text: {
                    switch (SpotifyAuth.phase) {
                    case "requesting":
                        return qsTr("Tunnistautuminen käynnissä…")
                    case "consent":
                        return qsTr("Tunnistautuminen käynnissä — viimeistele kirjautuminen " +
                                    "selaimessa, joka avautui näytölle.")
                    case "done":
                        return qsTr("Tunnistautuminen onnistui.")
                    case "error":
                        return SpotifyAuth.message.length > 0
                             ? SpotifyAuth.message
                             : qsTr("Tunnistautuminen epäonnistui.")
                    default:
                        return ""
                    }
                }
            }

            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 10

                // Starting over is the only recovery: an authorization code is
                // single-use, so a failed flow can never be retried with the same one.
                DialogButton {
                    visible: popup.failed
                    label: qsTr("Yritä uudelleen")
                    onActivated: SpotifyAuth.begin()
                }

                // "Peruuta" while a flow is running is not cosmetic — without it a
                // browser that never comes back would strand the dialog on screen.
                DialogButton {
                    label: popup.busy ? qsTr("Peruuta") : qsTr("Sulje")
                    onActivated: SpotifyAuth.cancel()
                }
            }
        }
    }
}

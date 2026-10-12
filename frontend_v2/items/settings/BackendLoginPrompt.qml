import QtQuick
import QtQuick.Controls
import frontend_v2

// The login to the backend (issue #64). App-level, like SpotifyAuthAlert: until
// this display has logged in it gets no data at all, whichever view is on screen.
//
// ServerClient raises it when the backend wants the password — the first
// connect, a revoked or expired login, a certificate that is not the one pinned
// at login — and while the backend has no password set, which it explains
// instead of asking. The ✕ puts it away (the dock and the Options view stay
// usable, e.g. to fix the backend address); Ylläpito › Yhteydet's Kirjaudu row
// and the issues list bring it back. A successful login is remembered, so this
// is typed once per display.
//
// Hung in the top half of the screen: the on-screen keyboard takes the bottom.
ModalDialog {
    id: prompt

    readonly property bool noPassword: Server.authState === "noPassword"

    visible: Server.loginPromptVisible
    // Dark, and the card ModalDialog's opaque default: the dashboard behind has
    // nothing to show until the login is done, and the translucent card family
    // let it read straight through the field and the buttons.
    scrimColor: "#d9000000"
    cardWidth: 520
    cardTopMargin: 64
    cardHeight: column.implicitHeight + 48

    // Nothing typed survives a closed prompt or a finished attempt.
    onVisibleChanged: field.text = ""

    function submit() {
        if (Server.loginBusy)
            return
        const password = field.text
        field.text = ""
        field.focus = false
        Qt.inputMethod.hide()
        Server.login(password)
    }

    Item {
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
            onClicked: {
                Qt.inputMethod.hide()
                Server.dismissLoginPrompt()
            }
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
            text: qsTr("Kirjaudu palvelimelle")
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
            color: prompt.noPassword ? "#ffd48a" : Theme.dataLabelTitle
            text: prompt.noPassword
                  ? Server.authMessage
                  : qsTr("Palvelin %1 vaatii salasanan. Kirjautuminen muistetaan, joten "
                         + "salasana kysytään tällä näytöllä vain kerran.").arg(Server.endpoint)
        }

        Rectangle {
            visible: !prompt.noPassword
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(parent.width, 320)
            height: 40
            radius: 8
            opacity: Server.loginBusy ? 0.5 : 1.0
            color: field.activeFocus ? Theme.tripComboPressed : Theme.tripComboBg
            border.width: 1
            border.color: field.activeFocus ? Theme.accent : Theme.tripCardBorder

            TextField {
                id: field
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                enabled: !Server.loginBusy
                echoMode: TextInput.Password
                placeholderText: qsTr("Salasana")
                placeholderTextColor: Theme.dataLabelTitle
                font.family: Theme.fontFamily
                font.pixelSize: 15
                color: Theme.dataLabelValue
                verticalAlignment: TextInput.AlignVCenter
                background: null
                inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoAutoUppercase
                                  | Qt.ImhNoPredictiveText | Qt.ImhHiddenText
                onAccepted: prompt.submit()
            }
        }

        // Why the last attempt failed, or that one is under way: deriving the key
        // takes seconds on a Raspberry Pi.
        Text {
            width: parent.width
            visible: text.length > 0 && !prompt.noPassword
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: 13
            color: Server.loginBusy ? Theme.dataLabelTitle : "#f87171"
            text: Server.loginBusy ? qsTr("Kirjaudutaan…") : Server.authMessage
        }

        DialogButton {
            visible: !prompt.noPassword
            anchors.horizontalCenter: parent.horizontalCenter
            primary: true
            opacity: Server.loginBusy ? 0.5 : 1.0
            label: qsTr("Kirjaudu")
            onActivated: prompt.submit()
        }
    }
}

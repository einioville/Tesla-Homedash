import QtQuick
import frontend_v2

// What *Tyhjennä lokit* opens: clear everything, or everything but the warnings
// and errors — the records a later look at a problem needs, and what the
// Järjestelmän tila cards count and list. Both halves' files either way
// (Logs, core/CLAUDE.md); the outcome comes back on the row, not here, so the
// dialog closes the moment a choice is made.
//
// A child of SettingsView like the other dialogs, drawn the same way.
Item {
    id: popup

    property bool shown: false

    function open() { popup.shown = true }
    function close() { popup.shown = false }

    function choose(keepWarnings) {
        Logs.clear(keepWarnings)
        popup.close()
    }

    anchors.fill: parent
    visible: shown
    z: 100

    MouseArea {
        anchors.fill: parent
        // A MouseArea with no wheel handler lets the wheel through, which
        // scrolled the view behind the dialog. Swallow it; a list inside the
        // card still scrolls, since it sits above this.
        onWheel: (wheel) => wheel.accepted = true
        onClicked: popup.close()
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.dialogScrim
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: Theme.gridMargin + 96
        width: Math.min(parent.width - 2 * Theme.gridMargin, 600)
        height: column.implicitHeight + 40
        radius: Theme.tripCardRadius
        color: Theme.spotifySurface
        border.width: 1
        border.color: Theme.spotifyRim

        MouseArea {
            anchors.fill: parent
        }

        Column {
            id: column
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 20
            spacing: 16

            Text {
                width: parent.width
                text: qsTr("Tyhjennä lokit")
                font.family: Theme.fontFamily
                font.pixelSize: 19
                font.bold: true
                color: Theme.dataLabelValue
            }

            Text {
                width: parent.width
                text: qsTr("Sovelluksen lokitiedostot tyhjennetään palvelimelta ja tältä näytöltä. "
                           + "Varoitukset ja virheet kannattaa yleensä säilyttää: niistä selviää "
                           + "myöhemmin, mikä meni vikaan. Kaiken tyhjentäminen nollaa myös "
                           + "palveluiden virhelaskurit.")
                font.family: Theme.fontFamily
                font.pixelSize: 14
                color: Theme.dataLabelTitle
                wrapMode: Text.WordWrap
            }

            Row {
                anchors.right: parent.right
                spacing: 10

                DialogButton {
                    label: qsTr("Peruuta")
                    onActivated: popup.close()
                }

                DialogButton {
                    label: qsTr("Tyhjennä kaikki")
                    onActivated: popup.choose(false)
                }

                DialogButton {
                    primary: true
                    label: qsTr("Säilytä varoitukset ja virheet")
                    onActivated: popup.choose(true)
                }
            }
        }
    }
}

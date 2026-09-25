import QtQuick
import frontend_v2

// Why screen-off is not working, rendered inside the Näytönsäästäjä card
// (SettingsPane picks it up from the subsection's `status` key). Collapses to
// nothing while there is nothing to say.
//
// Screen-off fails SILENTLY otherwise: a refused wlopm call leaves a toggle
// that looks armed while the panel simply never blanks (#46), and on labwc 0.20
// a long blank can lose the output altogether (#43). The backend detects both
// and reports them in DISPLAY_POWER_STATE's fault byte; this names them.
Item {
    id: status

    readonly property string message: {
        if (!Server.connected)
            return ""
        if (!Display.available)
            return Settings.values.screenOffEnabled
                   ? qsTr("Näytön sammutus ei ole käytettävissä: wlopm puuttuu palvelimelta.")
                   : ""
        switch (Display.fault) {
        case 2:
            return qsTr("Näyttö ei palannut päälle sammutuksen jälkeen: näyttölähtö katosi "
                        + "(tunnettu vika labwc 0.20 / wlroots 0.20 -versioissa). Sammutus on "
                        + "keskeytetty palvelimen seuraavaan uudelleenkäynnistykseen asti. "
                        + "Pidä se pois käytöstä, kunnes näyttöpino on korjattu.")
        case 1:
            return qsTr("Näytön virtaa ei voitu vaihtaa: wlopm kieltäytyi. Tavallisin syy "
                        + "on käynnissä oleva VNC-palvelin (wayvnc), joka estää sammutuksen.")
        default:
            return ""
        }
    }

    implicitHeight: message.length > 0 ? line.implicitHeight + 8 : 0
    visible: message.length > 0

    Row {
        id: line
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8

        Rectangle {
            y: 5
            width: 8
            height: 8
            radius: 4
            color: Display.fault === 2 ? "#f87171" : "#ffb020"
        }

        Text {
            width: line.width - 16
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: 11
            color: "#ffd48a"
            text: status.message
        }
    }
}

import QtQuick
import frontend_v2

// The Koti row's details: the home's address, its coordinates and the timezone the backend
// takes from it — and, when that is not the zone the running backend was started in, that it
// changes on the next restart (`setting.runtime`, from ConfigService: the schedulers are built
// once). Styled as the help line it stands in for.
Column {
    id: details

    required property var setting

    readonly property var home: setting.value ? setting.value : null
    readonly property var runtime: setting.runtime !== undefined ? setting.runtime : ({})
    readonly property bool zoneChanges: runtime.zoneNext !== undefined
                                        && runtime.zoneNext !== runtime.zoneInEffect

    spacing: 2

    Text {
        width: parent.width
        wrapMode: Text.WordWrap
        font.family: Theme.fontFamily
        font.pixelSize: 12
        color: Theme.dataLabelTitle
        text: details.home ? details.home.address
                           : qsTr("Ei asetettu: sää haetaan asetustiedoston paikkakunnalle")
    }

    Text {
        width: parent.width
        visible: details.home !== null
        wrapMode: Text.WordWrap
        font.family: Theme.fontFamily
        font.pixelSize: 12
        color: Theme.dataLabelTitle
        text: details.home ? details.home.lat.toFixed(5) + ", " + details.home.lon.toFixed(5)
                             + (details.runtime.zoneNext ? "  ·  " + details.runtime.zoneNext : "")
                           : ""
    }

    Text {
        width: parent.width
        visible: details.zoneChanges
        wrapMode: Text.WordWrap
        font.family: Theme.fontFamily
        font.pixelSize: 12
        color: "#ffd48a"
        text: qsTr("Aikavyöhyke vaihtuu, kun palvelin käynnistetään uudelleen (nyt %1)")
              .arg(details.runtime.zoneInEffect || "")
    }
}

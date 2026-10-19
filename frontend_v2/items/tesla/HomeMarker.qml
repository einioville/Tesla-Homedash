import QtQuick
import QtLocation
import QtPositioning
import frontend_v2

// The home location (Yleinen › Sijainti › Koti) on a map: the home icon in a dark disc, with
// "Koti" under it in the place names' style. Declare it inside the Map; hidden while no home
// is set. Like the names it has no zoomLevel of its own, so it stays upright and screen-sized
// when the map turns heading-up.
MapQuickItem {
    id: root

    readonly property var home: {
        // valueOf is an invokable, which captures no dependency; valuesRevision does.
        const revision = Settings.valuesRevision
        return Settings.valueOf("home")
    }

    visible: !!home && home.lat !== undefined && home.lon !== undefined
    // Over the names and the cameras, under the car.
    z: 5
    coordinate: visible ? QtPositioning.coordinate(home.lat, home.lon) : QtPositioning.coordinate()
    anchorPoint.x: marker.width / 2
    anchorPoint.y: disc.height / 2
    sourceItem: Item {
        id: marker
        width: Math.max(disc.width, label.implicitWidth)
        height: disc.height + 2 + label.implicitHeight

        Rectangle {
            id: disc
            anchors.horizontalCenter: parent.horizontalCenter
            width: 28
            height: 28
            radius: 14
            color: "#d9101016"
            border.width: 1.5
            border.color: "white"
            TintedIcon {
                anchors.centerIn: parent
                iconSize: 16
                source: "qrc:/resources/icons/home.svg"
            }
        }
        Text {
            id: label
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: disc.bottom
            anchors.topMargin: 2
            text: qsTr("Koti")
            font.family: Theme.fontFamily
            font.pixelSize: 13
            color: "white"
            style: Text.Outline
            styleColor: "#d0000000"
        }
    }
}

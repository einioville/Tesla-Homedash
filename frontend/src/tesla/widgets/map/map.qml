import QtQuick
import QtLocation
import QtPositioning

Item {
    id: root
    objectName: "root"

    property real latitude: 61.497063
    property real longitude: 23.750078
    property real rotation: 32

    Behavior on latitude {
        NumberAnimation {
            duration: 999; easing.type: Easing.Linear
        }
    }
    Behavior on longitude {
        NumberAnimation {
            duration: 999; easing.type: Easing.Linear
        }
    }

    Behavior on rotation {
        NumberAnimation {
            duration: 999; easing.type: Easing.Linear
        }
    }

    Plugin {
        id: osmPlugin
        name: "osm"

        PluginParameter {
            name: "osm.useragent"
            value: "FuckVitut"
        }
        PluginParameter {
            name: "osm.mapping.host"
            value: "https://tile.openstreetmap.org/"
        }
    }

    Map {
        id: map
        objectName: "map"

        anchors.fill: parent
        plugin: osmPlugin

        zoomLevel: 15
        bearing: 0
        activeMapType: map.supportedMapTypes[7]

        center: QtPositioning.coordinate(root.latitude, root.longitude)

        MapQuickItem {
            id: vehicle
            objectName: "vehicle"

            coordinate: QtPositioning.coordinate(root.latitude, root.longitude)
            rotation: root.rotation

            sourceItem: Image {
                id: vehicleIcon
                source: "qrc:/resources/icons/arrow.svg"
                width: 24
                height: 24
                smooth: true
                antialiasing: true
            }

            anchorPoint.x: vehicleIcon.width / 2
            anchorPoint.y: vehicleIcon.height / 2
        }
    }
}

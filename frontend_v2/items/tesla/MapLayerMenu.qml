import QtQuick
import frontend_v2

// The Kartta view's layer switch: a round button in the bottom-right corner, and over it,
// once tapped, a menu of the map's layers with a switch each. Fill the view with it — while
// the menu is open a press anywhere outside it closes it (and goes no further, so it does
// not also move the map); closed, nothing here but the button takes input.
//
// The layers are hidden local settings (mapLayer*, the Kartta card), so a choice outlasts a
// restart without a row in the Options view.
Item {
    id: root

    // What the glass frosts: the map, a sibling filling the view.
    property Item backdrop: null
    property bool open: false
    property int margin: 20
    // The round button, for placing other controls beside it.
    readonly property Item toggleButton: button

    readonly property var layers: [
        { key: "mapLayerStats", label: qsTr("Ajotiedot") },
        { key: "mapLayerRoute", label: qsTr("Ajettu reitti") },
        { key: "mapLayerPlaces", label: qsTr("Paikannimet") },
        { key: "mapLayerRadar", label: qsTr("Sadetutka") }
    ]

    MouseArea {
        anchors.fill: parent
        enabled: root.open
        onPressed: root.open = false
    }

    GlassPanel {
        id: menu
        anchors.right: button.right
        anchors.bottom: button.top
        anchors.bottomMargin: 12
        width: 280
        height: column.implicitHeight + 28
        radius: 18
        rimWidth: 0.75
        highlight: false
        backdropSource: root.backdrop
        backdropOrigin: Qt.point(x, y)
        active: visible
        opacity: root.open ? 1 : 0
        scale: root.open ? 1 : 0.9
        transformOrigin: Item.BottomRight
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }

        // Swallows presses on the panel between its rows, which would otherwise close it.
        MouseArea {
            anchors.fill: parent
        }

        Column {
            id: column
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 14

            Text {
                leftPadding: 6
                bottomPadding: 6
                text: qsTr("KARTTATASOT")
                color: Theme.cardTitle
                font.family: Theme.fontFamily
                font.pixelSize: 12
                font.letterSpacing: 1.2
            }

            Repeater {
                model: root.layers

                Item {
                    id: row
                    required property var modelData
                    readonly property bool checked: Settings.values[modelData.key] === true
                    width: column.width
                    height: 52

                    function flip() {
                        Settings.setValue(row.modelData.key, !row.checked)
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: row.flip()
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        text: row.modelData.label
                        color: "white"
                        font.family: Theme.fontFamily
                        font.pixelSize: 17
                    }
                    ToggleSwitch {
                        anchors.right: parent.right
                        anchors.rightMargin: 4
                        anchors.verticalCenter: parent.verticalCenter
                        checked: row.checked
                        onToggled: row.flip()
                    }
                }
            }
        }
    }

    GlassPanel {
        id: button
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: root.margin
        width: 56
        height: 56
        radius: 28
        rimWidth: 0.75
        highlight: false
        tintTop: root.open ? "#4d4aa8ff" : Theme.notificationGlassTop
        tintBottom: root.open ? "#334aa8ff" : Theme.notificationGlassBottom
        backdropSource: root.backdrop
        backdropOrigin: Qt.point(x, y)

        Image {
            anchors.centerIn: parent
            width: 26
            height: 26
            source: "qrc:/resources/icons/layers.svg"
            sourceSize: Qt.size(52, 52)
        }
        MouseArea {
            anchors.fill: parent
            anchors.margins: -8
            onClicked: root.open = !root.open
        }
    }
}

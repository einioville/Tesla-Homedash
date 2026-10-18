import QtQuick
import frontend_v2

// A map's layer switch: a round button in the map's bottom-right corner, and over it, once
// tapped, a menu of the map's layers with a switch each — the Kartta view's and the dashboard
// card's. Fill the view with it — while the menu is open a press anywhere outside it closes it
// (and goes no further, so it does not also move the map); closed, nothing here but the button
// takes input.
//
// Each view names its layers (`layers`: { key, label }), hidden local settings in the Kartta
// card, so a choice outlasts a restart without a row in the Options view. `shown` fades the
// button in and out (the dashboard's card shows it on a touch); `used()` on every tap.
Item {
    id: root

    // The map: the button sits in its corner and the glass frosts it. A sibling of this item.
    property Item backdrop: null
    property var layers: []
    property bool open: false
    property bool shown: true
    property int margin: 20
    // The round button, for placing other controls beside it.
    readonly property Item toggleButton: button

    signal used()

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
        backdropOrigin: Qt.point(x - (root.backdrop ? root.backdrop.x : 0), y - (root.backdrop ? root.backdrop.y : 0))
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
                        root.used()
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
        x: root.backdrop ? root.backdrop.x + root.backdrop.width - width - root.margin : 0
        y: root.backdrop ? root.backdrop.y + root.backdrop.height - height - root.margin : 0
        width: 56
        height: 56
        radius: 28
        rimWidth: 0.75
        highlight: false
        tintTop: root.open ? "#4d4aa8ff" : Theme.notificationGlassTop
        tintBottom: root.open ? "#334aa8ff" : Theme.notificationGlassBottom
        backdropSource: root.backdrop
        backdropOrigin: Qt.point(x - (root.backdrop ? root.backdrop.x : 0), y - (root.backdrop ? root.backdrop.y : 0))
        active: visible
        opacity: root.shown ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }

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
            onClicked: {
                root.open = !root.open
                root.used()
            }
        }
    }
}

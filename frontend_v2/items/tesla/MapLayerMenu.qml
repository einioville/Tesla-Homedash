import QtQuick
import frontend_v2

// A map's layer switch: a round button in the map's bottom-right corner, and over it, once
// tapped, a menu of the map's layers with a switch each — the Kartta view's and the dashboard
// card's. Fill the view with it — while the menu is open a press anywhere outside it closes it
// (and goes no further, so it does not also move the map); closed, nothing here but the button
// takes input.
//
// Each view names its layers (`layers`: { key, label }), hidden local settings in the Kartta
// card, so a choice outlasts a restart without a row in the Options view. A layer may also
// carry the ways it shows (`modes`: [{ key, label }], switches) and one `choice` ({ key,
// label, options: [{ value, label }] }), nested under its row while it is on (the radar's
// minimap and overlay, and its history). The layer is on only with one of its modes on:
// switched on with all of them off it shows the first, and switching the last one off
// switches the layer off. `shown` fades the button in and out (the dashboard's card shows it
// on a touch); `used()` on every tap.
Item {
    id: root

    // The map: the button sits in its corner and the glass frosts it. A sibling of this item.
    property Item backdrop: null
    // The backdrop's shared frost (FrostLayer), for the menu's and the button's glass.
    property Item frost: null
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
        width: 320
        height: column.implicitHeight + 28
        radius: 18
        rimWidth: 0.75
        highlight: false
        backdropSource: root.backdrop
        backdropOrigin: Qt.point(x - (root.backdrop ? root.backdrop.x : 0), y - (root.backdrop ? root.backdrop.y : 0))
        frost: root.frost
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

                Column {
                    id: entry
                    required property var modelData
                    readonly property bool checked: Settings.values[modelData.key] === true
                    readonly property var modes: modelData.modes || []
                    readonly property var choice: modelData.choice || null
                    readonly property bool hasOptions: modes.length > 0 || choice !== null
                    width: column.width

                    function isOn(key) {
                        return Settings.values[key] === true
                    }

                    function flip() {
                        if (!checked && modes.length > 0 && !modes.some(m => isOn(m.key)))
                            Settings.setValue(modes[0].key, true)
                        Settings.setValue(modelData.key, !checked)
                        root.used()
                    }

                    function flipMode(key) {
                        var on = isOn(key)
                        Settings.setValue(key, !on)
                        if (on && !modes.some(m => m.key !== key && isOn(m.key)))
                            Settings.setValue(modelData.key, false)
                        root.used()
                    }

                    onCheckedChanged: checked ? options.show(0) : options.hide(0)
                    Component.onCompleted: options.snap(checked)

                    Item {
                        width: entry.width
                        height: 52

                        MouseArea {
                            anchors.fill: parent
                            onClicked: entry.flip()
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 6
                            anchors.verticalCenter: parent.verticalCenter
                            text: entry.modelData.label
                            color: "white"
                            font.family: Theme.fontFamily
                            font.pixelSize: 17
                        }
                        ToggleSwitch {
                            anchors.right: parent.right
                            anchors.rightMargin: 4
                            anchors.verticalCenter: parent.verticalCenter
                            checked: entry.checked
                            onToggled: entry.flip()
                        }
                    }

                    Reveal {
                        id: options
                        width: entry.width
                        fullHeight: entry.hasOptions ? optionColumn.implicitHeight : 0

                        // The rule that ties the options to the row above.
                        Rectangle {
                            x: 10
                            y: 4
                            width: 2
                            height: optionColumn.implicitHeight - 14
                            radius: 1
                            color: "#33ffffff"
                        }

                        Column {
                            id: optionColumn
                            width: parent.width
                            bottomPadding: 6

                            Repeater {
                                model: entry.modes

                                Item {
                                    id: modeRow
                                    required property var modelData
                                    width: optionColumn.width
                                    height: 40

                                    MouseArea {
                                        anchors.fill: parent
                                        onClicked: entry.flipMode(modeRow.modelData.key)
                                    }
                                    Text {
                                        x: 24
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: modeRow.modelData.label
                                        color: "#d9ffffff"
                                        font.family: Theme.fontFamily
                                        font.pixelSize: 15
                                    }
                                    ToggleSwitch {
                                        anchors.right: parent.right
                                        anchors.rightMargin: 4
                                        anchors.verticalCenter: parent.verticalCenter
                                        trackWidth: 44
                                        trackHeight: 24
                                        checked: entry.isOn(modeRow.modelData.key)
                                        onToggled: entry.flipMode(modeRow.modelData.key)
                                    }
                                }
                            }

                            Item {
                                visible: entry.choice !== null
                                width: optionColumn.width
                                height: 40

                                Text {
                                    x: 24
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: entry.choice ? entry.choice.label : ""
                                    color: "#d9ffffff"
                                    font.family: Theme.fontFamily
                                    font.pixelSize: 15
                                }
                                Row {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 4
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 3

                                    Repeater {
                                        model: entry.choice ? entry.choice.options : []

                                        Rectangle {
                                            id: option
                                            required property var modelData
                                            readonly property bool selected:
                                                Settings.values[entry.choice.key] === modelData.value
                                            width: optionLabel.implicitWidth + 12
                                            height: 28
                                            radius: 8
                                            color: selected ? "#4d4aa8ff" : "#1affffff"
                                            border.color: selected ? Theme.accent : "transparent"
                                            border.width: 1

                                            Text {
                                                id: optionLabel
                                                anchors.centerIn: parent
                                                text: option.modelData.label
                                                color: "white"
                                                font.family: Theme.fontFamily
                                                font.pixelSize: 12
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                anchors.topMargin: -6
                                                anchors.bottomMargin: -6
                                                onClicked: {
                                                    Settings.setValue(entry.choice.key, option.modelData.value)
                                                    root.used()
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
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
        frost: root.frost
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

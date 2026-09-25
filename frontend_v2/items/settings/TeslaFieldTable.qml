import QtQuick
import frontend_v2

// The Telemetriakentät card (issue #29): per telemetry field, whether it is saved
// to history and how the History graph draws it. Rendered from the subsection's
// `status: "teslaProperties"` key; the subsection has no settings of its own,
// because a 47-row table is a different delegate family from a settings row.
//
// Only `log`, `line_mode` and `zero_based` are editable. The rest of each field's
// definition is mirrored by this binary's generated registry, so it is shown in
// the subtitle and never offered for editing. Every value shown is the backend's:
// a tap sends a change and the row updates when the re-broadcast table arrives.
Item {
    id: table

    implicitHeight: content.implicitHeight

    Component.onCompleted: TeslaFields.refresh()

    // Fields grouped under their category (alphabetical), in config order within
    // a group; a group starts with a {header} entry.
    readonly property var rows: {
        const groups = {}
        const order = []
        for (const field of TeslaFields.fields) {
            const category = field.category.length > 0 ? field.category : qsTr("Muut")
            if (!(category in groups)) {
                groups[category] = []
                order.push(category)
            }
            groups[category].push(field)
        }
        order.sort()
        const out = []
        for (const category of order) {
            out.push({ header: category })
            for (const field of groups[category])
                out.push(field)
        }
        return out
    }

    // Numeric fields whose graph would mislead rather than inform. Shown as a
    // hint, never enforced: switching logging back on is still the user's call.
    readonly property var hints: ({
        "GpsHeading": qsTr("kiertyy 0°↔360°, ei hyödyllinen graafina")
    })

    readonly property int switchColumn: 76
    readonly property int modeColumn: 150

    // A compact version of SettingSwitch, driven by a value rather than a setting.
    component MiniSwitch: Item {
        id: miniSwitch

        property bool checked: false
        signal toggled()

        implicitWidth: 46
        implicitHeight: 26
        opacity: enabled ? 1.0 : 0.35

        Rectangle {
            id: track
            anchors.centerIn: parent
            width: 44
            height: 24
            radius: height / 2
            color: miniSwitch.checked ? Theme.accent : Theme.tripComboBg
            border.width: 1
            border.color: miniSwitch.checked ? Theme.accent : Theme.tripCardBorder

            Rectangle {
                width: 18
                height: 18
                radius: height / 2
                color: Theme.dataLabelValue
                anchors.verticalCenter: parent.verticalCenter
                x: miniSwitch.checked ? track.width - width - 3 : 3

                Behavior on x {
                    NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
                }
            }
        }

        MouseArea {
            // A finger-sized target around the small visual.
            anchors.fill: parent
            anchors.margins: -8
            onClicked: miniSwitch.toggled()
        }
    }

    // One half of the step | linear toggle.
    component ModeButton: Rectangle {
        id: modeButton

        property string label
        property bool selected: false
        signal picked()

        width: 70
        height: 26
        radius: 6
        color: selected ? Theme.accent : (modeArea.pressed ? Theme.tripComboPressed : Theme.tripComboBg)
        border.width: 1
        border.color: selected ? Theme.accent : Theme.tripCardBorder

        Text {
            anchors.centerIn: parent
            text: modeButton.label
            font.family: Theme.fontFamily
            font.pixelSize: 12
            color: Theme.dataLabelValue
        }

        MouseArea {
            id: modeArea
            anchors.fill: parent
            onClicked: if (!modeButton.selected) modeButton.picked()
        }
    }

    Column {
        id: content
        width: table.width
        spacing: 0

        Text {
            width: parent.width
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: 11
            color: Theme.dataLabelTitle
            text: qsTr("Tallennuksen käynnistäminen ei tuo mennyttä historiaa: graafi alkaa "
                       + "siitä hetkestä. Matkat- ja Lataus-näkymien tarvitsemien kenttien "
                       + "tallennusta ei voi poistaa.")
        }

        // The backend's reason for the last refused change.
        Text {
            width: parent.width
            topPadding: 6
            visible: TeslaFields.lastError.length > 0
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: 12
            color: "#ffd48a"
            text: TeslaFields.lastError
        }

        Text {
            topPadding: 10
            visible: !TeslaFields.loaded
            font.family: Theme.fontFamily
            font.pixelSize: 12
            color: Theme.dataLabelTitle
            text: Server.connected ? qsTr("Ladataan…") : qsTr("Ei yhteyttä palvelimeen")
        }

        // Column titles.
        Item {
            width: parent.width
            height: 30
            visible: TeslaFields.loaded

            Row {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 4

                Repeater {
                    model: [
                        { text: qsTr("Tallenna"), width: table.switchColumn },
                        { text: qsTr("Piirtotapa"), width: table.modeColumn },
                        { text: qsTr("0-pohja"), width: table.switchColumn }
                    ]

                    Text {
                        required property var modelData
                        width: modelData.width
                        horizontalAlignment: Text.AlignHCenter
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        color: Theme.dataLabelTitle
                        text: modelData.text
                    }
                }
            }
        }

        Repeater {
            model: table.rows

            Item {
                id: entry

                required property var modelData

                readonly property bool isHeader: modelData.header !== undefined
                // Graph flags only mean something for a field that is saved AND
                // numeric (numeric is null until the field has streamed once).
                readonly property bool graphable: !isHeader && modelData.log
                                                  && modelData.numeric !== false
                readonly property bool locked: !isHeader && modelData.log
                                               && modelData.requiredBy.length > 0

                width: content.width
                height: isHeader ? 34 : 46

                Text {
                    visible: entry.isHeader
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 6
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    font.bold: true
                    color: Theme.dataLabelValue
                    text: entry.isHeader ? entry.modelData.header : ""
                }

                Rectangle {
                    visible: !entry.isHeader
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 1
                    color: "#1affffff"
                }

                Column {
                    visible: !entry.isHeader
                    anchors.left: parent.left
                    anchors.right: controls.left
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 1

                    Text {
                        width: parent.width
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                        color: Theme.dataLabelValue
                        text: entry.isHeader ? "" : entry.modelData.id
                    }

                    Text {
                        width: parent.width
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        color: Theme.dataLabelTitle
                        text: {
                            if (entry.isHeader)
                                return ""
                            const f = entry.modelData
                            const parts = []
                            if (f.unit.length > 0)
                                parts.push(f.unit)
                            if (f.numeric === false)
                                parts.push(qsTr("ei numeerinen, ei graafia"))
                            if (f.requiredBy.length > 0)
                                parts.push(qsTr("tarvitaan: ") + f.requiredBy)
                            if (table.hints[f.id] !== undefined)
                                parts.push(table.hints[f.id])
                            return parts.join(" · ")
                        }
                    }
                }

                Row {
                    id: controls
                    visible: !entry.isHeader
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter

                    Item {
                        width: table.switchColumn
                        height: 30

                        MiniSwitch {
                            anchors.centerIn: parent
                            checked: !entry.isHeader && entry.modelData.log
                            // A field another view reads back cannot stop being
                            // saved; the subtitle names the view.
                            enabled: !entry.locked
                            onToggled: TeslaFields.setField(entry.modelData.id, "log",
                                                            !entry.modelData.log)
                        }
                    }

                    Row {
                        width: table.modeColumn
                        height: 30
                        leftPadding: (width - 2 * 70 - spacing) / 2
                        spacing: 4
                        enabled: entry.graphable
                        opacity: enabled ? 1.0 : 0.35

                        ModeButton {
                            anchors.verticalCenter: parent.verticalCenter
                            label: qsTr("Porras")
                            selected: !entry.isHeader && entry.modelData.line_mode !== "linear"
                            onPicked: TeslaFields.setField(entry.modelData.id, "line_mode", "step")
                        }
                        ModeButton {
                            anchors.verticalCenter: parent.verticalCenter
                            label: qsTr("Suora")
                            selected: !entry.isHeader && entry.modelData.line_mode === "linear"
                            onPicked: TeslaFields.setField(entry.modelData.id, "line_mode", "linear")
                        }
                    }

                    Item {
                        width: table.switchColumn
                        height: 30

                        MiniSwitch {
                            anchors.centerIn: parent
                            checked: !entry.isHeader && entry.modelData.zero_based
                            enabled: entry.graphable
                            onToggled: TeslaFields.setField(entry.modelData.id, "zero_based",
                                                            !entry.modelData.zero_based)
                        }
                    }
                }
            }
        }
    }
}

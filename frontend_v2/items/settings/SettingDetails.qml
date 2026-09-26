import QtQuick
import frontend_v2

// The details block a setting row carries under its label when the schema names
// one (`details: "<id>"`, resolved by SettingRow): a status line led by a
// traffic-light dot, then label/value pairs. Generic, so each consumer only
// computes `level`, `statusText` and `rows` from the singleton it reads.
Column {
    id: details

    // "ok" (green), "warn" (amber), "error" (red) or "unknown" (grey — the
    // state could not be established, which is not the same as bad).
    property string level: "unknown"
    property string statusText: ""
    // [{label, value}]
    property var rows: []
    property int labelWidth: 96

    topPadding: 4
    spacing: 3

    Row {
        spacing: 8

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 8
            height: 8
            radius: 4
            color: details.level === "ok" ? "#4ade80"
                 : details.level === "warn" ? "#ffb020"
                 : details.level === "error" ? "#f87171" : Theme.dataLabelTitle
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: details.width - 16
            elide: Text.ElideRight
            text: details.statusText
            font.family: Theme.fontFamily
            font.pixelSize: 12
            color: details.level === "warn" ? "#ffd48a"
                 : details.level === "error" ? "#f87171" : Theme.dataLabelValue
        }
    }

    Repeater {
        model: details.rows

        Row {
            id: pair

            required property var modelData

            spacing: 12

            Text {
                width: details.labelWidth
                text: pair.modelData.label
                font.family: Theme.fontFamily
                font.pixelSize: 12
                color: Theme.dataLabelTitle
            }

            Text {
                width: details.width - details.labelWidth - 12
                // Middle, not right: a Connect id's two ends are what tell two
                // ids apart at a glance.
                elide: Text.ElideMiddle
                text: pair.modelData.value
                font.family: Theme.fontFamily
                font.pixelSize: 12
                color: Theme.dataLabelValue
            }
        }
    }
}

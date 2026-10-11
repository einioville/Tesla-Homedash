import QtQuick
import frontend_v2

// One labelled telemetry value — the QML port of SingleTeslaDataEntry. Three
// transparent chips: title across the top (left), value at the bottom-left and
// unit at the bottom-right edge. Font sizes are FIXED for the 1280×800 layout
// (valueFontSize below).
Item {
    id: entry

    property string title: ""
    property real value: 0
    property string unit: ""

    // Fixed for the 1280×800 layout: the entry is 287.5px wide there (the 307.5px
    // list card minus its 2×10px margins), and width/8 (~35.9pt) rounds to 36; the
    // small font is half of it.
    readonly property real valueFontSize: 36
    readonly property real smallFontSize: 18

    // Real implicit height so the list's bands can size the entry (its children
    // are anchored, which would otherwise leave the Item with implicitHeight 0).
    implicitHeight: titleChip.height + 2 + valueChip.height

    // Title — top row, left, elided at the entry's width.
    Rectangle {
        id: titleChip
        anchors.left: parent.left
        anchors.top: parent.top
        color: "transparent"
        width: Math.min(titleText.implicitWidth + 6, entry.width)
        height: titleText.implicitHeight + 2
        Text {
            id: titleText
            anchors.centerIn: parent
            width: parent.width - 6
            text: entry.title
            color: Theme.dataLabelValue
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pointSize: entry.smallFontSize
        }
    }

    // Value — bottom row, left.
    Rectangle {
        id: valueChip
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        color: "transparent"
        width: valueText.implicitWidth + 6
        height: valueText.implicitHeight + 2
        Text {
            id: valueText
            anchors.centerIn: parent
            text: Math.round(entry.value)
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pointSize: entry.valueFontSize
        }
    }

    // Unit — bottom row, pushed to the right edge.
    Rectangle {
        id: unitChip
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        color: "transparent"
        width: unitText.implicitWidth + 6
        height: unitText.implicitHeight + 2
        visible: entry.unit.length > 0
        Text {
            id: unitText
            anchors.centerIn: parent
            text: entry.unit
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pointSize: entry.smallFontSize
        }
    }
}

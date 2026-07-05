import QtQuick
import frontend_v2

// One stat tile in the Trips-view detail grid: a minimalistic translucent-grey card
// with a whiteish border, a title above a large value. `value` is a preformatted
// string ("—" when the metric is unavailable), so all formatting + units live in
// TripStatsGrid. The value auto-shrinks to fit the card width (HorizontalFit) so a
// long "145 Wh/km" reads without eliding while short values stay big.
Item {
    id: root

    property string title: ""
    property string value: "—"

    Rectangle {
        anchors.fill: parent
        radius: Theme.tripCardRadius
        color: Theme.tripCardBg
        border.width: 1
        border.color: Theme.tripCardBorder
    }

    Column {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.margins: 18
        spacing: 8

        Text {
            width: parent.width
            text: root.title
            color: Theme.dataLabelTitle
            font.family: Theme.fontFamily
            font.pixelSize: 20
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            text: root.value
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pixelSize: 38
            font.bold: true
            fontSizeMode: Text.HorizontalFit
            minimumPixelSize: 22
            elide: Text.ElideRight
        }
    }
}

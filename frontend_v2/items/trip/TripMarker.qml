import QtQuick
import QtLocation
import frontend_v2

// A geo-anchored pin marking one end of a trip (start or end). A red location pin
// with a small label chip above it; placed inside the Map so it pans/zooms natively
// (no per-frame reprojection). The pin's tip anchors on the coordinate.
MapQuickItem {
    id: marker

    property string label: ""
    property color pinColor: Theme.tripMarkerColor
    property int pinSize: 34

    anchorPoint.x: content.width / 2
    anchorPoint.y: content.height   // tip ≈ bottom-centre of the pin

    sourceItem: Item {
        id: content
        width: Math.max(pinIcon.width, chip.width)
        height: chip.height + 3 + pinIcon.height

        Rectangle {
            id: chip
            anchors.top: parent.top
            anchors.horizontalCenter: parent.horizontalCenter
            radius: 6
            color: Theme.tripControlBar
            border.width: 1
            border.color: Theme.tripControlBarBorder
            implicitWidth: chipText.implicitWidth + 12
            implicitHeight: chipText.implicitHeight + 6

            Text {
                id: chipText
                anchors.centerIn: parent
                text: marker.label
                color: Theme.dataLabelValue
                font.family: Theme.fontFamily
                font.pixelSize: 13
            }
        }

        TintedIcon {
            id: pinIcon
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            source: "qrc:/resources/icons/location.svg"
            tint: marker.pinColor
            iconSize: marker.pinSize
        }
    }
}

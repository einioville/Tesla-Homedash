import QtQuick
import frontend_v2

// Seat-heater indicator: a seat silhouette tinted red while heating (white when
// off) above up to three level dots — the QML port of TeslaSeatWidget. The
// passenger seat is mirrored horizontally. (Cooling is plumbed but, like the
// Widgets original, only the heating state is surfaced.)
Column {
    id: seat

    property int level: 0          // SeatHeater* (0–3)
    property bool mirrored: false  // passenger seat flips the silhouette

    spacing: 0

    TintedIcon {
        anchors.horizontalCenter: parent.horizontalCenter
        iconSize: 30
        source: "qrc:/resources/icons/seat.svg"
        tint: seat.level > 0 ? Theme.seatHeat : Theme.iconTint
        transform: Scale {
            origin.x: 15
            xScale: seat.mirrored ? -1 : 1
        }
    }

    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 0

        Repeater {
            model: 3
            delegate: Image {
                required property int index
                width: 10
                height: 10
                source: "qrc:/resources/icons/heating.png"
                sourceSize.width: 10
                sourceSize.height: 10
                smooth: true
                visible: index < seat.level
            }
        }
    }
}

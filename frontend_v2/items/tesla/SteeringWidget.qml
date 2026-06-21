import QtQuick
import frontend_v2

// Steering-wheel-heater indicator: a wheel glyph tinted red while heating
// (white when off) above up to two level dots — the QML port of
// TeslaSteeringwidget.
Column {
    id: wheel

    property int level: 0   // HvacSteeringWheelHeatLevel

    spacing: 0

    TintedIcon {
        anchors.horizontalCenter: parent.horizontalCenter
        iconSize: 30
        source: "qrc:/resources/icons/steering.svg"
        tint: wheel.level > 0 ? Theme.seatHeat : Theme.iconTint
    }

    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 0

        Repeater {
            model: 2
            delegate: Image {
                required property int index
                width: 10
                height: 10
                source: "qrc:/resources/icons/heating.png"
                sourceSize.width: 10
                sourceSize.height: 10
                smooth: true
                visible: index < wheel.level
            }
        }
    }
}

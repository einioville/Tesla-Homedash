import QtQuick
import frontend_v2

Rectangle {
    id: button

    property string label: ""
    signal clicked()

    implicitWidth: Math.max(72, text.implicitWidth + 28)
    implicitHeight: 44
    radius: 10
    color: tap.pressed ? Qt.darker(Theme.accent, 1.3) : Theme.accent

    Accessible.role: Accessible.Button
    Accessible.name: label
    Accessible.onPressAction: button.clicked()

    Text {
        id: text
        anchors.centerIn: parent
        text: button.label
        color: "#0b0d12"
        font.pixelSize: 18
        font.bold: true
    }

    MouseArea {
        id: tap
        anchors.fill: parent
        onClicked: button.clicked()
    }
}

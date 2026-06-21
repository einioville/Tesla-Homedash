import QtQuick
import QtQuick.Layouts
import frontend_v2

// A gradient card holding a vertical stack of DataEntry rows separated by thin
// white rules — the QML port of TeslaDataEntryList. `entries` is an array of
// { title, value, unit }; the gradient origin faces a chosen corner.
//
// Each entry gets an equal-height band (mirroring the original's even addStretch
// distribution) and is centred within it, so entries never collide; the divider
// sits at the top of every band after the first, i.e. cleanly between entries.
GradientCard {
    id: list

    property var entries: []

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 0

        Repeater {
            model: list.entries

            delegate: Item {
                id: band
                required property int index
                required property var modelData

                Layout.fillWidth: true
                Layout.fillHeight: true

                Rectangle {
                    visible: band.index > 0
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 4
                    radius: 2
                    color: Theme.separator
                }

                DataEntry {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    title: band.modelData.title
                    value: band.modelData.value
                    unit: band.modelData.unit
                }
            }
        }
    }
}

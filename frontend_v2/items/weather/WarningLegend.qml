import QtQuick
import frontend_v2
import "WeatherUtil.js" as U

// The warnings WarningAreas draws, named: a dot in each one's colour, its kind and the
// headline's region and time, the first `rows` of them; a tap asks for them whole (tapped()).
// Frosted glass over the map (`backdrop`, a sibling of this panel).
GlassPanel {
    id: root

    property var warnings: []
    property Item backdrop: null
    property int rows: 4

    signal tapped()

    implicitWidth: 320
    implicitHeight: list.implicitHeight + 24
    radius: 16
    rimWidth: 0.75
    highlight: false
    backdropSource: backdrop
    backdropOrigin: Qt.point(x - (backdrop ? backdrop.x : 0), y - (backdrop ? backdrop.y : 0))

    MouseArea {
        anchors.fill: parent
        onClicked: root.tapped()
    }

    Column {
        id: list
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 12
        spacing: 8

        Repeater {
            model: root.warnings.slice(0, root.rows)

            Row {
                id: entry
                required property var modelData
                width: list.width
                spacing: 10

                Rectangle {
                    y: 4
                    width: 10
                    height: 10
                    radius: 5
                    color: U.warnColor(entry.modelData.color)
                }
                Column {
                    width: entry.width - 20
                    Text {
                        width: parent.width
                        elide: Text.ElideRight
                        text: U.warnTitle(entry.modelData)
                        color: "white"
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                    }
                    Text {
                        width: parent.width
                        elide: Text.ElideRight
                        text: {
                            const h = entry.modelData.headline || ""
                            const i = h.indexOf(":")
                            return i > 0 ? h.slice(i + 1).trim() : U.warnWhen(entry.modelData)
                        }
                        color: "#b8c2cc"
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                }
            }
        }

        Text {
            visible: root.warnings.length > root.rows
            text: qsTr("+%1 muuta").arg(root.warnings.length - root.rows)
            color: "#b8c2cc"
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }
    }
}

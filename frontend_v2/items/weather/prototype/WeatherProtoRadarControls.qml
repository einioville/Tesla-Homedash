import QtQuick
import QtQuick.Shapes
import frontend_v2

// PROTOTYPE — play/pause, the frame's time and a scrub track for a WeatherProtoRadarMap.
Rectangle {
    id: bar

    property Item radar: null
    property bool showLegend: true

    implicitWidth: row.implicitWidth + 24
    implicitHeight: 44
    radius: height / 2
    color: "#d9101418"
    border.color: "#33ffffff"
    border.width: 1

    function timeText(d) {
        return Qt.formatTime(d, "HH:mm")
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 12

        Rectangle {
            width: 32
            height: 32
            radius: 16
            color: "#26ffffff"
            anchors.verticalCenter: parent.verticalCenter

            Text {
                anchors.centerIn: parent
                text: bar.radar && bar.radar.playing ? "❚❚" : "▶"
                color: "white"
                font.pixelSize: 13
            }
            MouseArea {
                anchors.fill: parent
                onClicked: bar.radar.playing = !bar.radar.playing
            }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: 48
            text: bar.radar ? bar.timeText(bar.radar.frameTime) : ""
            color: "white"
            font.family: Theme.fontFamily
            font.pixelSize: 17
        }

        // Scrub track: one tick per frame, filled up to the shown one.
        Item {
            id: track
            width: 200
            height: 32
            anchors.verticalCenter: parent.verticalCenter

            Row {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3
                Repeater {
                    model: bar.radar ? bar.radar.frameCount : 0
                    Rectangle {
                        required property int index
                        width: (track.width - 3 * (bar.radar.frameCount - 1)) / bar.radar.frameCount
                        height: index === bar.radar.frame ? 14 : 6
                        radius: 3
                        anchors.verticalCenter: parent.verticalCenter
                        color: index <= bar.radar.frame ? "#4aa8ff" : "#40ffffff"
                    }
                }
            }
            MouseArea {
                anchors.fill: parent
                function seek(x) {
                    var n = bar.radar.frameCount
                    bar.radar.playing = false
                    bar.radar.frame = Math.max(0, Math.min(n - 1, Math.round(x / width * (n - 1))))
                }
                onPressed: (mouse) => seek(mouse.x)
                onPositionChanged: (mouse) => seek(mouse.x)
            }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: {
                if (!bar.radar)
                    return ""
                var mins = (bar.radar.frameCount - 1 - bar.radar.frame) * bar.radar.frameStepMin
                return mins === 0 ? qsTr("uusin") : "-" + mins + " min"
            }
            color: "#b8c2cc"
            font.family: Theme.fontFamily
            font.pixelSize: 13
            width: 52
        }

        // Lightning up to the shown frame, there whenever the loop has any, so the bar does
        // not change width as the count climbs from zero.
        Row {
            visible: bar.radar !== null && bar.radar.strikes.length > 0
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4
            Shape {
                width: 10
                height: 16
                anchors.verticalCenter: parent.verticalCenter
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    fillColor: "#fff6b0"
                    strokeColor: "transparent"
                    PathPolyline {
                        path: [Qt.point(6.5, 0), Qt.point(0.5, 9), Qt.point(4.5, 9), Qt.point(3, 16),
                               Qt.point(9.5, 6.5), Qt.point(5.5, 6.5), Qt.point(6.5, 0)]
                    }
                }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(implicitWidth, 24)
                text: bar.radar ? bar.radar.strikesShown : ""
                color: "white"
                font.family: Theme.fontFamily
                font.pixelSize: 13
            }
        }

        // dBZ legend, FMI's palette from light to heavy.
        Row {
            visible: bar.showLegend
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4
            Text { text: qsTr("heikko"); color: "#b8c2cc"; font.pixelSize: 11; font.family: Theme.fontFamily }
            Rectangle {
                width: 70
                height: 8
                radius: 4
                anchors.verticalCenter: parent.verticalCenter
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "#7fe0ff" }
                    GradientStop { position: 0.35; color: "#2fb35a" }
                    GradientStop { position: 0.65; color: "#f2e23a" }
                    GradientStop { position: 1.0; color: "#e0302a" }
                }
            }
            Text { text: qsTr("voimakas"); color: "#b8c2cc"; font.pixelSize: 11; font.family: Theme.fontFamily }
        }
    }
}

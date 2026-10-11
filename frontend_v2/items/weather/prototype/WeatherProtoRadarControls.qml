import QtQuick
import QtQuick.Shapes
import frontend_v2
import "../../util"

// PROTOTYPE — play/pause, the frame's time and a scrub track for a WeatherProtoRadarMap.
// Frosted glass over the radar behind it (the app's GlassPanel, as the notification pill has).
GlassPanel {
    id: bar

    property Item radar: null
    property bool showLegend: true

    implicitWidth: row.implicitWidth + 24
    implicitHeight: 44
    radius: 12
    backdropSource: bar.radar
    backdropOrigin: Qt.point(bar.x - (bar.radar ? bar.radar.x : 0), bar.y - (bar.radar ? bar.radar.y : 0))
    active: bar.radar ? bar.radar.active : false

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
            // The map's strike mark: a yellow cross outlined in black.
            Shape {
                width: 14
                height: 14
                anchors.verticalCenter: parent.verticalCenter
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "black"
                    strokeWidth: 5.5
                    fillColor: "transparent"
                    capStyle: ShapePath.RoundCap
                    PathMultiline { paths: [[Qt.point(2.5, 2.5), Qt.point(11.5, 11.5)],
                                            [Qt.point(11.5, 2.5), Qt.point(2.5, 11.5)]] }
                }
                ShapePath {
                    strokeColor: "#ffd21f"
                    strokeWidth: 2.5
                    fillColor: "transparent"
                    capStyle: ShapePath.RoundCap
                    PathMultiline { paths: [[Qt.point(2.5, 2.5), Qt.point(11.5, 11.5)],
                                            [Qt.point(11.5, 2.5), Qt.point(2.5, 11.5)]] }
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

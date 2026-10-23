import QtQuick
import QtQuick.Shapes
import frontend_v2

// Play/pause, the frame's time and a scrub track for a RadarLayer, laid out in a row (the
// Weather card) or, `vertical`, in a column with the track running up from the oldest frame to
// the newest, so time goes the way the eye reads "later" (the Kartta view's left edge). With a
// `latestOnlyKey`, a *Vain uusin* checkbox writes that setting, which the view hands the layer
// as `latestOnly` (the Weather card; a map's layer menu sets it with *Historia*). While the
// layer shows the newest frame alone, the loop's controls are gone and only its time is left.
// Frosted glass over the map behind it (the app's GlassPanel, as the notification pill has).
GlassPanel {
    id: bar

    property Item radar: null
    // What the glass frosts: the map under the radar, a sibling of this bar.
    property Item backdrop: null
    property bool vertical: false
    // The local setting the *Vain uusin* checkbox writes; empty, no checkbox.
    property string latestOnlyKey: ""
    readonly property bool latestOnly: radar !== null && radar.latestOnly

    implicitWidth: layout.implicitWidth + 24
    implicitHeight: layout.implicitHeight + (vertical ? 24 : 12)
    radius: 12
    backdropSource: bar.backdrop
    backdropOrigin: Qt.point(bar.x - (bar.backdrop ? bar.backdrop.x : 0), bar.y - (bar.backdrop ? bar.backdrop.y : 0))
    active: bar.radar ? bar.radar.active : false

    Grid {
        id: layout
        anchors.centerIn: parent
        flow: bar.vertical ? Grid.TopToBottom : Grid.LeftToRight
        rows: bar.vertical ? -1 : 1
        columns: bar.vertical ? 1 : -1
        spacing: bar.vertical ? 10 : 12
        horizontalItemAlignment: Grid.AlignHCenter
        verticalItemAlignment: Grid.AlignVCenter

        Rectangle {
            width: 32
            height: 32
            radius: 16
            color: "#26ffffff"
            visible: !bar.latestOnly

            TintedIcon {
                anchors.centerIn: parent
                iconSize: 16
                source: bar.radar && bar.radar.playing ? "qrc:/resources/icons/pause.svg"
                                                       : "qrc:/resources/icons/play.svg"
            }
            MouseArea {
                anchors.fill: parent
                onClicked: bar.radar.playing = !bar.radar.playing
            }
        }

        Text {
            width: 48
            horizontalAlignment: Text.AlignHCenter
            text: bar.radar ? Qt.formatTime(bar.radar.frameTime, "HH:mm") : ""
            color: "white"
            font.family: Theme.fontFamily
            font.pixelSize: 17
        }

        // Scrub track: one tick per frame, filled up to the shown one.
        Item {
            id: track
            visible: !bar.latestOnly
            readonly property int count: bar.radar ? bar.radar.frameCount : 0
            readonly property real length: bar.vertical ? Math.max(48, count * 14) : 200
            width: bar.vertical ? 32 : length
            height: bar.vertical ? length : 32

            Grid {
                anchors.centerIn: parent
                rows: bar.vertical ? -1 : 1
                columns: bar.vertical ? 1 : -1
                spacing: 3
                horizontalItemAlignment: Grid.AlignHCenter
                verticalItemAlignment: Grid.AlignVCenter
                Repeater {
                    model: track.count
                    Rectangle {
                        required property int index
                        // Upright, the newest frame is the top tick.
                        readonly property int frame: bar.vertical ? track.count - 1 - index : index
                        readonly property real along: (track.length - 3 * (track.count - 1)) / track.count
                        readonly property real across: frame === bar.radar.frame ? 14 : 6
                        width: bar.vertical ? across : along
                        height: bar.vertical ? along : across
                        radius: 3
                        color: frame <= bar.radar.frame ? "#4aa8ff" : "#40ffffff"
                    }
                }
            }
            MouseArea {
                anchors.fill: parent
                function seek(position) {
                    var n = bar.radar.frameCount
                    bar.radar.playing = false
                    bar.radar.frame = Math.max(0, Math.min(n - 1, Math.round(position / track.length * (n - 1))))
                }
                onPressed: (mouse) => seek(bar.vertical ? track.length - mouse.y : mouse.x)
                onPositionChanged: (mouse) => seek(bar.vertical ? track.length - mouse.y : mouse.x)
            }
        }

        Text {
            visible: !bar.latestOnly
            width: 52
            horizontalAlignment: bar.vertical ? Text.AlignHCenter : Text.AlignLeft
            text: {
                if (!bar.radar)
                    return ""
                var mins = (bar.radar.frameCount - 1 - bar.radar.frame) * bar.radar.frameStepMin
                return mins === 0 ? qsTr("uusin") : "-" + mins + " min"
            }
            color: "#b8c2cc"
            font.family: Theme.fontFamily
            font.pixelSize: 13
        }

        // Lightning up to the shown frame, there whenever the loop has any, so the bar does
        // not change size as the count climbs from zero.
        Row {
            visible: bar.radar !== null && bar.radar.strikeCount > 0
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

        // dBZ legend, FMI's palette from light to heavy; upright, heavy is at the top.
        Grid {
            rows: bar.vertical ? -1 : 1
            columns: bar.vertical ? 1 : -1
            spacing: 4
            horizontalItemAlignment: Grid.AlignHCenter
            verticalItemAlignment: Grid.AlignVCenter

            Text {
                text: bar.vertical ? qsTr("voimakas") : qsTr("heikko")
                color: "#b8c2cc"; font.pixelSize: 11; font.family: Theme.fontFamily
            }
            Rectangle {
                width: bar.vertical ? 8 : 70
                height: bar.vertical ? 70 : 8
                radius: 4
                gradient: Gradient {
                    orientation: bar.vertical ? Gradient.Vertical : Gradient.Horizontal
                    GradientStop { position: 0.0; color: bar.vertical ? "#e0302a" : "#7fe0ff" }
                    GradientStop { position: 0.35; color: bar.vertical ? "#f2e23a" : "#2fb35a" }
                    GradientStop { position: 0.65; color: bar.vertical ? "#2fb35a" : "#f2e23a" }
                    GradientStop { position: 1.0; color: bar.vertical ? "#7fe0ff" : "#e0302a" }
                }
            }
            Text {
                text: bar.vertical ? qsTr("heikko") : qsTr("voimakas")
                color: "#b8c2cc"; font.pixelSize: 11; font.family: Theme.fontFamily
            }
        }

        // Only the newest frame, no loop.
        Item {
            visible: bar.latestOnlyKey !== ""
            width: latestRow.implicitWidth
            height: latestRow.implicitHeight

            Grid {
                id: latestRow
                rows: bar.vertical ? -1 : 1
                columns: bar.vertical ? 1 : -1
                spacing: bar.vertical ? 4 : 6
                horizontalItemAlignment: Grid.AlignHCenter
                verticalItemAlignment: Grid.AlignVCenter

                Rectangle {
                    width: 20
                    height: 20
                    radius: 5
                    color: bar.latestOnly ? Theme.accent : "transparent"
                    border.color: bar.latestOnly ? Theme.accent : "#80ffffff"
                    border.width: 1.5

                    TintedIcon {
                        anchors.centerIn: parent
                        visible: bar.latestOnly
                        iconSize: 14
                        source: "qrc:/resources/icons/check.svg"
                    }
                }
                Text {
                    text: qsTr("Vain uusin")
                    color: "white"
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                }
            }
            MouseArea {
                anchors.fill: parent
                anchors.margins: -6
                onClicked: Settings.setValue(bar.latestOnlyKey, !bar.latestOnly)
            }
        }
    }
}

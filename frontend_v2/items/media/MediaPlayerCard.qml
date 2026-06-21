import QtQuick
import QtQuick.Layouts
import QtQuick.Effects
import frontend_v2

// Now-playing card for the dashboard. Rounded panel with a vertical gradient from
// the album-art dominant colour (top) to a darkened variant (bottom). The cover,
// transport controls and seek bar are the shared MediaCover / MediaTransport /
// MediaSeekBar components (also used by the fullscreen MediaView); only the
// dominant-colour background and the compact column layout live here.
Item {
    id: card

    // DashboardView binds this to its isCurrent so the seek-bar ticker idles when
    // the view is hidden.
    property bool active: true

    readonly property bool isRadio: Media.mediaType === 1
    readonly property bool isSpotify: Media.mediaType === 2

    // Animated gradient endpoints so colour changes cross-fade.
    property color topColor: Media.dominantColor
    readonly property color bottomColor: Qt.rgba(topColor.r * 0.2, topColor.g * 0.2, topColor.b * 0.2, 1.0)
    Behavior on topColor { enabled: card.active; ColorAnimation { duration: 400 } }

    RectangularShadow {
        anchors.fill: bg
        radius: Theme.cardRadius
        blur: 50
        offset: Qt.vector2d(10, 10)
        color: Theme.cardShadowColor
        z: -1
    }

    Rectangle {
        id: bg
        anchors.fill: parent
        radius: Theme.cardRadius
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: card.topColor }
            GradientStop { position: 0.45; color: card.topColor }
            GradientStop { position: 1.0; color: card.bottomColor }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 4

        MediaCover {
            Layout.alignment: Qt.AlignHCenter
            coverSize: 160
        }

        Text {
            Layout.fillWidth: true
            text: Media.title.length > 0 ? Media.title : "-"
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pointSize: 15
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }

        Text {
            Layout.fillWidth: true
            visible: card.isSpotify && Media.artists.length > 0
            text: Media.artists
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pointSize: 8
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }

        MediaTransport {
            Layout.alignment: Qt.AlignHCenter
            buttonSize: 36
        }

        MediaSeekBar {
            Layout.fillWidth: true
            visible: !card.isRadio
            active: card.active
            barHeight: 4
            handleSize: 12
            fontPointSize: 8
        }
    }
}

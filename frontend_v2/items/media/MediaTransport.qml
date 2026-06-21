import QtQuick
import frontend_v2

// Transport controls (skip back / play-pause / skip forward) shared by the
// dashboard card and the fullscreen media view. buttonSize scales the icons and
// spacing. The play/pause glyph follows the server's isPlaying echo, not the tap.
Row {
    id: root

    property int buttonSize: 36
    spacing: Math.round(buttonSize * 0.44)

    component TransportButton: Item {
        property url icon
        signal activated()
        width: root.buttonSize
        height: root.buttonSize
        Image {
            anchors.fill: parent
            source: parent.icon
            sourceSize.width: root.buttonSize
            sourceSize.height: root.buttonSize
            fillMode: Image.PreserveAspectFit
            smooth: true
        }
        MouseArea { anchors.fill: parent; onClicked: parent.activated() }
    }

    TransportButton {
        icon: "qrc:/resources/icons/skip_backward.svg"
        onActivated: Media.skipBackward()
    }
    TransportButton {
        icon: Media.isPlaying ? "qrc:/resources/icons/pause.svg"
                              : "qrc:/resources/icons/play.svg"
        onActivated: Media.pausePlay()
    }
    TransportButton {
        icon: "qrc:/resources/icons/skip_forward.svg"
        onActivated: Media.skipForward()
    }
}

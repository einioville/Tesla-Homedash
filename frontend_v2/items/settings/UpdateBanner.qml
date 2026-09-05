import QtQuick
import frontend_v2

// A slim strip across the top of the screen while an app update is running.
//
// APP-LEVEL, not part of the Options view, for the same reason SpotifyAuthAlert
// is: a rebuild takes minutes on the Pi, and the user is free to walk back to the
// dashboard while it runs. The one thing they must not do is cut the power in the
// middle of a checkout or a dependency sync, and a warning that only exists on a
// settings screen nobody is looking at cannot say so.
//
// It carries no controls. Cancelling belongs to the card that started the run,
// where the version being moved to is visible; a button here would be a
// disruptive action offered with no context.
Item {
    id: banner

    readonly property var job: Updater.state.job !== undefined && Updater.state.job !== null
                               ? Updater.state.job : ({})
    readonly property string stepLabel: {
        const steps = job.steps !== undefined ? job.steps : []
        for (let i = 0; i < steps.length; ++i) {
            if (steps[i].state === "running")
                return steps[i].label
        }
        return qsTr("Päivitys käynnissä")
    }

    visible: Updater.busy
    height: 34

    Rectangle {
        anchors.fill: parent
        color: "#e6141c26"

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: "#33ffffff"
        }

        Row {
            anchors.centerIn: parent
            spacing: 10

            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 8
                height: 8
                radius: 4
                color: Theme.accent

                SequentialAnimation on opacity {
                    running: banner.visible
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.2; duration: 700 }
                    NumberAnimation { to: 1.0; duration: 700 }
                }
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: banner.stepLabel
                font.family: Theme.fontFamily
                font.pixelSize: 13
                color: Theme.dataLabelValue
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "·  " + qsTr("Älä katkaise virtaa")
                font.family: Theme.fontFamily
                font.pixelSize: 13
                color: "#ffd48a"
            }
        }
    }
}

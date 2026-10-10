import QtQuick
import frontend_v2

// Reachability verdict for the backend address, rendered inside the Yhteydet
// card (SettingsPane picks it up from the subsection's `status` key).
//
// backendHost / backendPort are restart-tier — AppConfig reads them once — so
// without this a typo shows up only after a restart, as a dashboard that never
// connects and says nothing about why. The probe answers before the restart.
//
// Advisory: it never blocks a write. The backend may simply not be up yet when
// its address is being configured, which is a perfectly ordinary state.
Item {
    id: status

    // Follow the SAVED values, not the editors: what matters is the address that
    // will actually be used at next startup.
    readonly property string host: Settings.values.backendHost !== undefined
                                   ? Settings.values.backendHost : ""
    readonly property int port: Settings.values.backendPort !== undefined
                                ? Settings.values.backendPort : 0

    implicitHeight: line.implicitHeight + 6

    // Debounced so a host edit followed immediately by a port edit probes once,
    // against the final pair, rather than twice against a half-changed address.
    Timer {
        id: debounce
        interval: 400
        onTriggered: Probe.check(status.host, status.port)
    }

    onHostChanged: debounce.restart()
    onPortChanged: debounce.restart()
    Component.onCompleted: debounce.restart()

    Row {
        id: line
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 8
            height: 8
            radius: 4
            color: Probe.state === "reachable" ? "#4ade80"
                 : Probe.state === "unreachable" ? "#f87171"
                 : Probe.state === "checking" ? "#ffb020" : Theme.dataLabelTitle
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, line.width - 100)
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: 11
            color: Probe.state === "unreachable" ? "#ffd48a" : Theme.dataLabelTitle
            text: {
                switch (Probe.state) {
                case "checking":
                    return qsTr("Tarkistetaan") + " " + Probe.target + "…"
                case "reachable":
                    return qsTr("Palvelin tavoitettu") + " · " + Probe.target
                case "unreachable":
                    return qsTr("Ei vastausta") + " · " + Probe.target
                           + (Probe.detail.length > 0 ? " — " + Probe.detail : "")
                default:
                    return qsTr("Yhteyttä ei ole tarkistettu")
                }
            }
        }

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: retryLabel.implicitWidth + 18
            height: retryLabel.implicitHeight + 8
            radius: 6
            color: retryArea.pressed ? Theme.tripComboPressed : Theme.tripComboBg
            border.width: 1
            border.color: Theme.tripCardBorder

            Text {
                id: retryLabel
                anchors.centerIn: parent
                text: qsTr("Testaa")
                font.family: Theme.fontFamily
                font.pixelSize: 11
                color: Theme.dataLabelValue
            }

            MouseArea {
                id: retryArea
                anchors.fill: parent
                enabled: Probe.state !== "checking"
                onClicked: Probe.check(status.host, status.port)
            }
        }
    }
}

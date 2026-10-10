import QtQuick
import frontend_v2
import "../../app/Format.js" as Format

// One backend service in Järjestelmän tila: its standing, the settings it is
// running with, any list it keeps (the connected displays) and its warning and
// error counts, with *Näytä* opening the list of them.
//
// Everything comes from the service's row in System.data.services — the
// backend's duck-typed health() (backend/src/system_service/CLAUDE.md) — and is
// rendered generically: a new service, or a new setting in one, needs no change
// here. A config value is a display string, or a typed object the frontend
// formats in its own locale: {time: ms}, {bytes: n}, {duration: s}.
Rectangle {
    id: card

    // One entry of System.data.services: {id, label, state, detail, config,
    // items, errors: {warnings, errors}}.
    required property var service

    readonly property var config: service.config !== undefined ? service.config : []
    readonly property var items: service.items !== undefined ? service.items : []
    readonly property int warnings: service.errors !== undefined ? service.errors.warnings : 0
    readonly property int errors: service.errors !== undefined ? service.errors.errors : 0

    readonly property var stateStyles: ({
        "ok": { "label": qsTr("Toiminnassa"), "color": "#4ade80" },
        "warn": { "label": qsTr("Ongelmia"), "color": "#ffb020" },
        "error": { "label": qsTr("Ei toiminnassa"), "color": "#f87171" },
        "off": { "label": qsTr("Ei käytössä"), "color": "#8a8f98" }
    })
    readonly property var stateInfo: stateStyles[service.state] !== undefined ? stateStyles[service.state]
                                                                           : stateStyles["off"]

    function formatValue(value) {
        if (value === undefined || value === null)
            return "—"
        if (typeof value !== "object")
            return String(value)
        if (value.time !== undefined)
            return formatTime(value.time)
        if (value.bytes !== undefined)
            return Format.bytes(value.bytes)
        if (value.duration !== undefined)
            return Format.duration(value.duration)
        return "—"
    }

    // Today as a clock time, another day with its date — a grant valid "until
    // 14:02" means nothing without the day it is on.
    function formatTime(ms) {
        if (ms === null || ms === undefined)
            return "—"
        const date = new Date(ms)
        const today = new Date()
        if (date.toDateString() === today.toDateString())
            return qsTr("klo %1").arg(Qt.formatTime(date, "hh:mm"))
        if (date.getFullYear() === today.getFullYear())
            return Qt.formatDateTime(date, "d.M. hh:mm")
        return Qt.formatDate(date, "d.M.yyyy")
    }

    // This display's own connection in the server card's list.
    function isThisDisplay(client) {
        return Server.connected && client.port === Server.localPort
               && client.address === Server.localAddress
    }

    implicitHeight: header.height + body.implicitHeight
    color: Theme.tripCardBg
    radius: Theme.tripCardRadius
    border.width: 1
    border.color: Theme.tripCardBorder

    // --- Header band (as SettingsPane's cards) --------------------------------
    Item {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: titleText.implicitHeight + 20

        Rectangle {
            anchors.fill: parent
            anchors.leftMargin: card.border.width
            anchors.rightMargin: card.border.width
            anchors.topMargin: card.border.width
            topLeftRadius: card.radius - card.border.width
            topRightRadius: card.radius - card.border.width
            bottomLeftRadius: 0
            bottomRightRadius: 0
            color: "#33000000"
        }

        Text {
            id: titleText
            anchors.left: parent.left
            anchors.leftMargin: 14
            anchors.right: stateRow.left
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            text: card.service.label
            font.family: Theme.fontFamily
            font.pixelSize: 19
            font.bold: true
            color: Theme.dataLabelValue
            elide: Text.ElideRight
        }

        // The verdict with a dot, never the colour alone.
        Row {
            id: stateRow
            anchors.right: parent.right
            anchors.rightMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            spacing: 7

            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 9
                height: 9
                radius: 4.5
                color: card.stateInfo.color
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: card.stateInfo.label
                font.family: Theme.fontFamily
                font.pixelSize: 14
                color: card.service.state === "off" ? Theme.dataLabelTitle : Theme.dataLabelValue
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: card.border.width
            anchors.rightMargin: card.border.width
            height: 1
            color: "#38ffffff"
        }
    }

    // --- Body ----------------------------------------------------------------
    Column {
        id: body
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        topPadding: 10
        bottomPadding: 12
        spacing: 6

        Text {
            width: parent.width
            visible: text.length > 0
            text: card.service.detail !== undefined ? card.service.detail : ""
            font.family: Theme.fontFamily
            font.pixelSize: 13
            color: card.service.state === "error" ? "#f87171"
                 : card.service.state === "warn" ? "#ffd48a" : Theme.dataLabelValue
            wrapMode: Text.WordWrap
        }

        // The settings in effect, label beside value. Both wrap rather than
        // elide: a path cut in the middle hides exactly the part being looked
        // for, and a path has no spaces, so it breaks at a slash or anywhere.
        Repeater {
            model: card.config

            Row {
                required property var modelData

                width: body.width
                spacing: 10

                Text {
                    width: parent.width * 0.42
                    text: modelData[0]
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: Theme.dataLabelTitle
                    wrapMode: Text.WordWrap
                }

                Text {
                    width: parent.width * 0.58 - parent.spacing
                    text: card.formatValue(modelData[1])
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: Theme.dataLabelValue
                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                }
            }
        }

        // The connected displays (the server card's items).
        Text {
            visible: card.items.length > 0
            topPadding: 4
            text: qsTr("Yhdistetyt näytöt")
            font.family: Theme.fontFamily
            font.pixelSize: 13
            color: Theme.dataLabelTitle
        }

        Repeater {
            model: card.items

            Row {
                id: client

                required property var modelData

                width: body.width
                spacing: 8

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 6
                    height: 6
                    radius: 3
                    color: Theme.accent
                }

                Text {
                    text: client.modelData.address + ":" + client.modelData.port
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: Theme.dataLabelValue
                }

                Text {
                    text: qsTr("yhdistetty %1").arg(card.formatTime(client.modelData.since_ms))
                          + (card.isThisDisplay(client.modelData) ? " · " + qsTr("tämä näyttö") : "")
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: Theme.dataLabelTitle
                }
            }
        }

        // --- Warnings and errors -------------------------------------------
        Item {
            width: body.width
            height: 10

            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: "#1affffff"
            }
        }

        Item {
            width: body.width
            height: viewButton.implicitHeight

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: 14

                Text {
                    text: qsTr("Virheitä") + " " + card.errors
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: card.errors > 0 ? "#f87171" : Theme.dataLabelTitle
                }

                Text {
                    text: qsTr("Varoituksia") + " " + card.warnings
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: card.warnings > 0 ? "#ffd48a" : Theme.dataLabelTitle
                }
            }

            DialogButton {
                id: viewButton
                anchors.right: parent.right
                label: qsTr("Näytä")
                onActivated: System.openLog(card.service.id, card.service.label)
            }
        }
    }
}

import QtQuick
import frontend_v2
import "../../app/Format.js" as Format

// The top of Järjestelmän tila: one verdict for the whole system, the issues
// behind it and how long the host and the backend have been up.
//
// The verdict is the worst of two kinds of issue. A service's comes from its
// card — the backend's health() (backend/src/system_service/CLAUDE.md) — so a
// service that is "off" on purpose (no Zappi, a flat tariff) is no issue. The
// host's are judged here, against the latest graph sample: a disk, memory or
// CPU temperature past a threshold below. While the backend is unreachable only
// that is reported, since everything else would be stale.
Rectangle {
    id: card

    // System.data.services, and whether the first status reply is in.
    property var services: []
    property bool connected: false
    property bool loaded: false
    // Seconds; NaN while unknown.
    property real hostUptime: NaN
    property real backendUptime: NaN
    // The latest graph sample (SystemHistory); NaN / empty while there is none.
    property var disk: ({})
    property real memPct: NaN
    property real cpuTemp: NaN

    readonly property var stateColors: ({
        "ok": "#4ade80", "warn": "#ffb020", "error": "#f87171", "off": "#8a8f98"
    })

    // Raspberry Pi firmware throttles the clock from 80 °C and hard at 85 °C.
    readonly property real tempWarnC: 80
    readonly property real tempErrorC: 85

    // {state, label, detail}, errors first, then warnings, each in card order.
    readonly property var issues: {
        if (!connected || !loaded)
            return []
        const found = []
        for (const service of services) {
            if (service.state === "error" || service.state === "warn")
                found.push({ "state": service.state, "label": service.label,
                             "detail": service.detail !== undefined ? service.detail : "" })
        }
        if (disk.used_pct !== undefined && disk.used_pct !== null && disk.used_pct >= 90) {
            found.push({ "state": disk.used_pct >= 95 ? "error" : "warn", "label": qsTr("Levy"),
                         "detail": qsTr("Levytila vähissä · %1 vapaana").arg(Format.bytes(disk.free_b)) })
        }
        if (!isNaN(memPct) && memPct >= 90) {
            found.push({ "state": memPct >= 97 ? "error" : "warn", "label": qsTr("Muisti"),
                         "detail": qsTr("Muisti lähes täynnä · %1 % käytössä").arg(memPct.toFixed(0)) })
        }
        if (!isNaN(cpuTemp) && cpuTemp >= tempWarnC) {
            found.push({ "state": cpuTemp >= tempErrorC ? "error" : "warn", "label": qsTr("Lämpötila"),
                         "detail": qsTr("Suoritin kuumenee · %1 °C").arg(cpuTemp.toFixed(1)) })
        }
        return found.filter(i => i.state === "error").concat(found.filter(i => i.state === "warn"))
    }

    readonly property int errorCount: issues.filter(i => i.state === "error").length
    readonly property int runningCount: services.filter(s => s.state === "ok").length
    readonly property int offCount: services.filter(s => s.state === "off").length

    readonly property string verdict: !connected ? "error"
                                    : !loaded ? "off"
                                    : errorCount > 0 ? "error"
                                    : issues.length > 0 ? "warn" : "ok"

    readonly property string headline: !connected ? qsTr("Ei yhteyttä palvelimeen")
                                     : !loaded ? qsTr("Haetaan tilaa…")
                                     : errorCount > 0 ? qsTr("Vikoja havaittu")
                                     : issues.length > 0 ? qsTr("Ongelmia havaittu")
                                     : qsTr("Järjestelmä kunnossa")

    readonly property string subline: {
        if (!connected)
            return qsTr("Palveluiden tila näkyy, kun yhteys palaa")
        if (!loaded)
            return ""
        const running = qsTr("%1 palvelua toiminnassa").arg(runningCount)
        const off = offCount > 0 ? " · " + qsTr("%1 ei käytössä").arg(offCount) : ""
        if (issues.length === 0)
            return running + off
        const count = issues.length === 1 ? qsTr("1 ongelma") : qsTr("%1 ongelmaa").arg(issues.length)
        return count + " · " + running
    }

    implicitHeight: content.implicitHeight
    color: Theme.tripCardBg
    radius: Theme.tripCardRadius
    border.width: 1
    border.color: Theme.tripCardBorder

    Column {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        topPadding: 16
        bottomPadding: 16
        spacing: 12

        // --- Verdict, with the uptimes at the right ---------------------------
        Item {
            width: content.width
            height: Math.max(verdictRow.height, uptimeGrid.height)

            Row {
                id: verdictRow
                anchors.left: parent.left
                anchors.right: uptimeGrid.left
                anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                spacing: 14

                // The verdict's dot with a soft halo — never the colour alone,
                // the headline says it too.
                Item {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 26
                    height: 26

                    Rectangle {
                        anchors.fill: parent
                        radius: width / 2
                        color: card.stateColors[card.verdict]
                        opacity: 0.22
                    }

                    Rectangle {
                        anchors.centerIn: parent
                        width: 14
                        height: 14
                        radius: 7
                        color: card.stateColors[card.verdict]
                    }
                }

                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    width: verdictRow.width - 26 - verdictRow.spacing
                    spacing: 3

                    Text {
                        width: parent.width
                        text: card.headline
                        font.family: Theme.fontFamily
                        font.pixelSize: 22
                        font.bold: true
                        color: Theme.dataLabelValue
                        elide: Text.ElideRight
                    }

                    Text {
                        width: parent.width
                        visible: text.length > 0
                        text: card.subline
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                        color: Theme.dataLabelTitle
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // Hidden while disconnected: the last reply's uptimes would be stale.
            Grid {
                id: uptimeGrid
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                visible: card.connected && card.loaded
                columns: 2
                columnSpacing: 14
                rowSpacing: 4
                horizontalItemAlignment: Grid.AlignRight

                Text {
                    visible: !isNaN(card.hostUptime)
                    text: qsTr("Laite päällä")
                    font.family: Theme.fontFamily
                    font.pixelSize: 14
                    color: Theme.dataLabelTitle
                }
                Text {
                    visible: !isNaN(card.hostUptime)
                    text: isNaN(card.hostUptime) ? "" : Format.duration(card.hostUptime)
                    font.family: Theme.fontFamily
                    font.pixelSize: 14
                    color: Theme.dataLabelValue
                }
                Text {
                    visible: !isNaN(card.backendUptime)
                    text: qsTr("Palvelin käynnissä")
                    font.family: Theme.fontFamily
                    font.pixelSize: 14
                    color: Theme.dataLabelTitle
                }
                Text {
                    visible: !isNaN(card.backendUptime)
                    text: isNaN(card.backendUptime) ? "" : Format.duration(card.backendUptime)
                    font.family: Theme.fontFamily
                    font.pixelSize: 14
                    color: Theme.dataLabelValue
                }
            }
        }

        // --- The issues -------------------------------------------------------
        Rectangle {
            visible: card.issues.length > 0
            width: content.width
            height: 1
            color: "#1affffff"
        }

        Column {
            visible: card.issues.length > 0
            width: content.width
            spacing: 8

            Repeater {
                model: card.issues

                Row {
                    id: issue

                    required property var modelData

                    width: content.width
                    spacing: 10

                    Rectangle {
                        y: (issueLabel.implicitHeight - height) / 2
                        width: 9
                        height: 9
                        radius: 4.5
                        color: card.stateColors[issue.modelData.state]
                    }

                    Text {
                        id: issueLabel
                        width: 150
                        text: issue.modelData.label
                        font.family: Theme.fontFamily
                        font.pixelSize: 15
                        font.bold: true
                        color: Theme.dataLabelValue
                        elide: Text.ElideRight
                    }

                    Text {
                        width: issue.width - 9 - issueLabel.width - 2 * issue.spacing
                        text: issue.modelData.detail
                        font.family: Theme.fontFamily
                        font.pixelSize: 15
                        color: issue.modelData.state === "error" ? "#f87171" : "#ffd48a"
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }
}

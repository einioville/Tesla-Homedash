import QtQuick
import frontend_v2

// The maintenance dashboard: how the host and the backend are doing.
//
// Rendered inside the Ylläpito card from the subsection's `status: "systemStatus"`
// key, the same hook the backend-reachability probe uses. Polling is gated on
// `System.active`, which is bound to this item's visibility below — a settings
// screen nobody has opened must not make the backend sample /proc every 5 s.
//
// Every value is read defensively out of an opaque map: the backend's status
// document is a dashboard, not a contract, and a metric that is missing on this
// host (no thermal zone on WSL2) has to render as "—" rather than break the view.
Item {
    id: panel

    readonly property var host: System.data.host !== undefined ? System.data.host : ({})
    readonly property var backend: System.data.backend !== undefined ? System.data.backend : ({})
    readonly property var errors: System.data.errors !== undefined ? System.data.errors : ({})
    readonly property var services: System.data.services !== undefined ? System.data.services : []
    readonly property var disks: host.disks !== undefined ? host.disks : []

    implicitHeight: content.implicitHeight

    // Poll only while on screen. `visible` is false whenever another section is
    // selected, because the Loader that builds this is inactive there.
    onVisibleChanged: System.active = visible
    Component.onCompleted: System.active = visible
    Component.onDestruction: System.active = false

    function fmtBytes(value) {
        if (value === undefined || value === null)
            return "—"
        const units = ["B", "kB", "MB", "GB", "TB"]
        let v = value
        let i = 0
        while (v >= 1024 && i < units.length - 1) { v /= 1024; ++i }
        return (i === 0 ? v.toFixed(0) : v.toFixed(1)) + " " + units[i]
    }

    function fmtDuration(seconds) {
        if (seconds === undefined || seconds === null)
            return "—"
        const s = Math.floor(seconds)
        const d = Math.floor(s / 86400)
        const h = Math.floor((s % 86400) / 3600)
        const m = Math.floor((s % 3600) / 60)
        if (d > 0)
            return d + " pv " + h + " h"
        if (h > 0)
            return h + " h " + m + " min"
        return m + " min"
    }

    function fmtPct(value) {
        return (value === undefined || value === null) ? "—" : value.toFixed(0) + " %"
    }

    Column {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 8

        Text {
            visible: !System.loaded
            text: qsTr("Haetaan tilatietoja…")
            font.family: Theme.fontFamily
            font.pixelSize: 12
            color: Theme.dataLabelTitle
        }

        // --- Host + backend figures, two per row -------------------------
        Grid {
            visible: System.loaded
            width: parent.width
            columns: 2
            columnSpacing: 18
            rowSpacing: 6

            Repeater {
                model: [
                    { "label": qsTr("Käyttöaste"),
                      "value": panel.fmtPct(panel.host.cpu_pct)
                               + (panel.host.cpu_count ? " / " + panel.host.cpu_count + " ydintä" : "") },
                    { "label": qsTr("Kuormitus"),
                      "value": panel.host.load ? panel.host.load.map(function (v) {
                                   return v.toFixed(2) }).join("  ") : "—" },
                    { "label": qsTr("Muisti vapaana"),
                      "value": panel.fmtBytes(panel.host.mem_available_b) + " / "
                               + panel.fmtBytes(panel.host.mem_total_b) },
                    { "label": qsTr("Lämpötila"),
                      "value": panel.host.cpu_temp_c !== undefined && panel.host.cpu_temp_c !== null
                               ? panel.host.cpu_temp_c.toFixed(1) + " °C" : "—" },
                    { "label": qsTr("Verkko"),
                      "value": "↓ " + panel.fmtBytes(panel.host.net_rx_bytes_per_s) + "/s   ↑ "
                               + panel.fmtBytes(panel.host.net_tx_bytes_per_s) + "/s" },
                    { "label": qsTr("Järjestelmä käynnissä"),
                      "value": panel.fmtDuration(panel.host.uptime_s) },
                    { "label": qsTr("Palvelin käynnissä"),
                      "value": panel.fmtDuration(panel.backend.uptime_s) },
                    { "label": qsTr("Palvelimen muisti"),
                      "value": panel.fmtBytes(panel.backend.rss_b) }
                ]

                Row {
                    required property var modelData
                    width: (content.width - 18) / 2
                    spacing: 6

                    Text {
                        width: parent.width * 0.5
                        text: modelData.label
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        color: Theme.dataLabelTitle
                    }
                    Text {
                        text: modelData.value
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        color: Theme.dataLabelValue
                    }
                }
            }
        }

        // --- Storage ------------------------------------------------------
        Repeater {
            model: panel.disks

            Row {
                required property var modelData
                width: content.width
                spacing: 6

                Text {
                    width: content.width * 0.25
                    text: qsTr("Levy") + " " + modelData.path
                    elide: Text.ElideMiddle
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    color: Theme.dataLabelTitle
                }

                // A bar, because "89 %" and "31 %" read the same in a table but
                // not at a glance, and disk-full is the failure this view exists
                // to catch early.
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: content.width * 0.4
                    height: 6
                    radius: 3
                    color: Theme.sliderGroove

                    Rectangle {
                        width: parent.width * Math.min(1, (modelData.used_pct || 0) / 100)
                        height: parent.height
                        radius: 3
                        color: (modelData.used_pct || 0) > 90 ? "#f87171"
                             : (modelData.used_pct || 0) > 75 ? "#ffb020" : Theme.accent
                    }
                }

                Text {
                    text: panel.fmtBytes(modelData.free_b) + " " + qsTr("vapaana")
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    color: Theme.dataLabelValue
                }
            }
        }

        // --- Per-service health ------------------------------------------
        Flow {
            visible: panel.services.length > 0
            width: parent.width
            spacing: 12

            Repeater {
                model: panel.services

                Row {
                    required property var modelData
                    spacing: 5

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 7
                        height: 7
                        radius: 3.5
                        color: modelData.state === "ok" ? "#4ade80"
                             : modelData.state === "warn" ? "#ffb020"
                             : modelData.state === "error" ? "#f87171"
                             : Theme.dataLabelTitle
                    }
                    Text {
                        text: modelData.label
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        color: Theme.dataLabelValue
                    }
                    Text {
                        visible: text.length > 0
                        text: modelData.detail !== undefined && modelData.detail.length > 0
                              ? "· " + modelData.detail : ""
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        color: Theme.dataLabelTitle
                    }
                }
            }
        }

        // --- Errors since boot --------------------------------------------
        Text {
            visible: System.loaded
            width: parent.width
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: 11
            color: (panel.errors.total || 0) > 0 ? "#ffd48a" : Theme.dataLabelTitle
            text: {
                const total = panel.errors.total || 0
                if (total === 0)
                    return qsTr("Ei varoituksia käynnistyksen jälkeen")
                const by = panel.errors.by_logger || ({})
                const parts = []
                for (const name in by)
                    parts.push(name + " " + by[name])
                return qsTr("Varoituksia käynnistyksen jälkeen") + ": " + total
                       + (parts.length > 0 ? " (" + parts.join(", ") + ")" : "")
            }
        }

        // The most recent few, verbatim — a count alone never says what broke.
        Repeater {
            model: panel.errors.recent !== undefined ? panel.errors.recent : []

            Text {
                required property var modelData
                width: content.width
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: 10
                color: Theme.dataLabelTitle
                text: modelData.level + " · " + modelData.logger + " · " + modelData.message
            }
        }
    }
}

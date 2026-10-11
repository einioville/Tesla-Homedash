import QtQuick
import frontend_v2
import "../../app/Format.js" as Format

// Järjestelmän tila: an overview — is the system healthy, what is wrong, how
// long it has been up — then the backend host's last ten minutes as graphs (CPU
// per core, memory, disk, network and CPU temperature), then a card per backend
// service with its standing, settings and warning/error counts.
//
// SettingsPane renders this INSTEAD of settings cards, because the section's group
// names `view: "systemStatus"`: it is a status screen, not options. The graphs are
// SystemHistory's, the cards System's; both are polled only while this item is
// visible, which is false whenever another section or another view is on screen
// (core/CLAUDE.md). Both count their consumers, so this retains once and
// releases once.
Item {
    id: section

    property bool retained: false
    function syncPoll() {
        if (visible === retained)
            return
        retained = visible
        if (retained) {
            SystemHistory.retain()
            System.retain()
        } else {
            SystemHistory.release()
            System.release()
        }
    }
    onVisibleChanged: syncPoll()
    Component.onCompleted: syncPoll()
    Component.onDestruction: {
        if (retained) {
            SystemHistory.release()
            System.release()
        }
    }

    readonly property var services: System.data.services !== undefined ? System.data.services : []
    readonly property real graphHeight: 290

    readonly property var columns: SystemHistory.series
    readonly property var info: SystemHistory.info
    readonly property var times: columns.t !== undefined ? columns.t : []
    readonly property real windowMs: (info.window_s !== undefined ? info.window_s : 600) * 1000
    readonly property real memTotal: info.mem_total_b !== undefined && info.mem_total_b !== null
                                     ? info.mem_total_b : 0
    readonly property var disk: info.disk !== undefined && info.disk !== null ? info.disk : ({})

    // The dark categorical palette, in its fixed order, validated (lightness band,
    // chroma, colour-blind separation of neighbours, contrast) against the card
    // surface these lines sit on, #212121. Assigned by core number, so a core
    // keeps its colour. A host with more than eight cores reuses the hues DASHED
    // for cores 9–16 rather than inventing a ninth colour, and alternates past that.
    readonly property var lineColors: ["#3987e5", "#d95926", "#199e70", "#c98500",
                                    "#d55181", "#008300", "#9085e9", "#e66767"]

    readonly property var units: ["B", "kB", "MB", "GB", "TB"]

    function fmtPct(value) {
        return value.toFixed(0) + " %"
    }

    // The unit a rate graph is drawn in: the largest that keeps the window's peak
    // under 1000 of it. The shared graph labels its axis with plain numbers, as
    // every graph in the app does, and the unit goes in the title.
    function rateUnit(lists) {
        let peak = 0
        for (const list of lists) {
            for (const v of list) {
                if (!isNaN(v) && v > peak)
                    peak = v
            }
        }
        let unit = 0
        while (unit < units.length - 1 && peak / Math.pow(1024, unit) >= 1000)
            ++unit
        return { "scale": Math.pow(1024, unit), "label": units[unit] + "/s" }
    }

    function scaled(list, by) {
        return list.map(v => v / by)
    }

    function column(name) {
        return columns[name] !== undefined ? columns[name] : []
    }

    function newest(list) {
        return list.length > 0 && list[list.length - 1] !== null ? list[list.length - 1] : NaN
    }

    function seconds(value) {
        return value !== undefined && value !== null ? value : NaN
    }

    // --- Per-graph data -------------------------------------------------------
    readonly property var cpuSeries: {
        const cores = column("cpu")
        const out = []
        for (let i = 0; i < cores.length; ++i) {
            out.push({
                "label": qsTr("Ydin %1").arg(i + 1),
                "values": cores[i],
                "color": lineColors[i % lineColors.length],
                "dashed": Math.floor(i / lineColors.length) % 2 === 1
            })
        }
        return out
    }

    readonly property var memPct: {
        const used = column("memUsed")
        return used.map(v => memTotal > 0 ? 100 * v / memTotal : NaN)
    }

    readonly property var diskUnit: rateUnit([column("diskRead"), column("diskWrite")])
    readonly property var netUnit: rateUnit([column("netRx"), column("netTx")])
    readonly property bool loading: !SystemHistory.loaded && Server.connected

    ElasticFlickable {
        id: flick
        anchors.fill: parent
        contentHeight: content.implicitHeight
        clip: true

        Column {
            id: content
            width: flick.width
            spacing: 10

            SystemOverviewCard {
                width: content.width
                height: implicitHeight
                services: section.services
                connected: Server.connected
                loaded: System.loaded
                hostUptime: section.seconds(System.data.uptime_s)
                backendUptime: section.seconds(System.data.backend_uptime_s)
                disk: section.disk
                memPct: section.newest(section.memPct)
                cpuTemp: section.newest(section.column("cpuTemp"))
            }

            Grid {
                id: grid
                width: content.width
                columns: 2
                spacing: 10

                readonly property real cellWidth: (width - spacing) / 2
                readonly property real cellHeight: section.graphHeight

                SystemGraphCard {
                    id: cpuCard
                    width: grid.cellWidth
                    height: grid.cellHeight
                    title: qsTr("Suoritin")
                    unit: "%"
                    times: section.times
                    windowMs: section.windowMs
                    loading: section.loading
                    lines: section.cpuSeries
                    fixedMinY: 0
                    fixedMaxY: 100
                    formatValue: function (v) { return section.fmtPct(v) }
                    // The mean over the cores at the newest sample.
                    summary: {
                        const last = section.times.length - 1
                        if (last < 0 || section.cpuSeries.length === 0)
                            return ""
                        let sum = 0
                        let n = 0
                        for (const core of section.cpuSeries) {
                            const v = core.values[last]
                            if (!isNaN(v)) { sum += v; ++n }
                        }
                        return n > 0 ? qsTr("keskim.") + " " + section.fmtPct(sum / n) : ""
                    }
                }

                SystemGraphCard {
                    width: grid.cellWidth
                    height: grid.cellHeight
                    title: qsTr("Muisti")
                    unit: "%"
                    times: section.times
                    windowMs: section.windowMs
                    loading: section.loading
                    live: true
                    lines: [{ "label": qsTr("Käytössä"), "values": section.memPct,
                              "color": Theme.accent }]
                    fixedMinY: 0
                    fixedMaxY: 100
                    formatValue: function (v) { return v.toFixed(1) + " %" }
                    summary: {
                        const used = section.column("memUsed")
                        if (used.length === 0)
                            return ""
                        return Format.bytes(used[used.length - 1]) + " / "
                               + Format.bytes(section.memTotal)
                    }
                }

                SystemGraphCard {
                    width: grid.cellWidth
                    height: grid.cellHeight
                    title: qsTr("Levy")
                    unit: section.diskUnit.label
                    times: section.times
                    windowMs: section.windowMs
                    loading: section.loading
                    zeroBased: true
                    lines: [
                        { "label": qsTr("Luku"), "color": section.lineColors[0],
                          "values": section.scaled(section.column("diskRead"), section.diskUnit.scale) },
                        { "label": qsTr("Kirjoitus"), "color": section.lineColors[1],
                          "values": section.scaled(section.column("diskWrite"), section.diskUnit.scale) }
                    ]
                    formatValue: function (v) { return v.toFixed(1) + " " + section.diskUnit.label }
                    widestValue: "999.9 kB/s"
                    // The graph is the disk's I/O; its space, which changes too slowly to
                    // graph, is the headline.
                    summary: section.disk.used_pct !== undefined && section.disk.used_pct !== null
                             ? Format.bytes(section.disk.free_b) + " " + qsTr("vapaana")
                             : ""
                }

                SystemGraphCard {
                    width: grid.cellWidth
                    height: grid.cellHeight
                    title: qsTr("Verkko")
                    unit: section.netUnit.label
                    times: section.times
                    windowMs: section.windowMs
                    loading: section.loading
                    zeroBased: true
                    lines: [
                        { "label": qsTr("Lataus"), "color": section.lineColors[0],
                          "values": section.scaled(section.column("netRx"), section.netUnit.scale) },
                        { "label": qsTr("Lähetys"), "color": section.lineColors[1],
                          "values": section.scaled(section.column("netTx"), section.netUnit.scale) }
                    ]
                    formatValue: function (v) { return v.toFixed(1) + " " + section.netUnit.label }
                    widestValue: "999.9 kB/s"
                }
            }

            SystemGraphCard {
                id: tempCard
                width: content.width
                height: section.graphHeight
                title: qsTr("Lämpötila")
                unit: "°C"
                times: section.times
                windowMs: section.windowMs
                loading: section.loading
                live: true
                lines: [{ "label": qsTr("Suoritin"), "values": section.column("cpuTemp"),
                          "color": section.lineColors[1] }]
                fixedMinY: 0
                fixedMaxY: 100
                formatValue: function (v) { return v.toFixed(1) + " °C" }
                unavailableText: section.info.temp_available === false
                                 ? qsTr("Tällä laitteella ei ole lämpötila-anturia") : ""
                summary: {
                    const temps = section.column("cpuTemp")
                    if (temps.length === 0 || isNaN(temps[temps.length - 1]))
                        return ""
                    let peak = -Infinity
                    for (const v of temps) {
                        if (!isNaN(v) && v > peak)
                            peak = v
                    }
                    return temps[temps.length - 1].toFixed(1) + " °C · " + qsTr("huippu") + " "
                           + peak.toFixed(1) + " °C"
                }
            }

            // --- Services ---------------------------------------------------
            Text {
                topPadding: 8
                text: qsTr("Palvelut")
                font.family: Theme.fontFamily
                font.pixelSize: 22
                color: Theme.dataLabelValue
            }

            Text {
                visible: section.services.length === 0
                text: Server.connected ? qsTr("Haetaan palveluiden tilaa…")
                                       : qsTr("Ei yhteyttä palvelimeen")
                font.family: Theme.fontFamily
                font.pixelSize: 13
                color: Theme.dataLabelTitle
            }

            // Two cards a row, each row as tall as its taller card. The model is
            // a COUNT, not the list: a poll replaces the list every five seconds,
            // and handing a Repeater a new array would rebuild every card.
            Repeater {
                model: Math.ceil(section.services.length / 2)

                Item {
                    id: serviceRow

                    required property int index

                    readonly property var leftService: section.services[2 * index]
                    readonly property bool hasRight: 2 * index + 1 < section.services.length

                    width: content.width
                    height: Math.max(leftCard.implicitHeight,
                                     rightLoader.item !== null ? rightLoader.item.implicitHeight : 0)

                    SystemServiceCard {
                        id: leftCard
                        width: (parent.width - 10) / 2
                        height: parent.height
                        service: serviceRow.leftService !== undefined ? serviceRow.leftService
                                                                      : ({ "label": "", "state": "off" })
                    }

                    Loader {
                        id: rightLoader
                        x: leftCard.width + 10
                        width: leftCard.width
                        height: parent.height
                        active: serviceRow.hasRight
                        sourceComponent: SystemServiceCard {
                            service: serviceRow.hasRight ? section.services[2 * serviceRow.index + 1]
                                                         : ({ "label": "", "state": "off" })
                        }
                    }
                }
            }
        }
    }
}

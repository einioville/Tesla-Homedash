import QtQuick
import frontend_v2

// The Ylläpito › Päivitys card's status widget (#56): what the backend's device runs, the
// releases it could move to, and an install while it runs. The backend does all of it
// (backend/src/update_service/CLAUDE.md; Updater in core/CLAUDE.md); this lists, asks and shows.
// The card's one row, under it, is Näytä esijulkaisut.
//
// Asenna takes a second tap within 4 s, the Options view's guard for a button with no way back
// (SettingAction): a dialog would need a way to dismiss it, which a keyboard-less panel lacks. The
// warnings for that move show while the row is open.
Column {
    id: root

    readonly property var doc: Updater.state
    readonly property var current: doc.current !== undefined ? doc.current : ({})
    readonly property var job: doc.job !== undefined && doc.job !== null ? doc.job : null
    readonly property bool development: doc.mode === "development"
    readonly property var releases: {
        const all = doc.releases !== undefined ? doc.releases : []
        return all.filter(r => Updater.showPrereleases || !r.prerelease || r.direction === "current")
    }
    // A display on another device than the backend runs the release it was installed with; one
    // on the backend's own device switches together with it.
    readonly property bool displayBehind: /^v\d/.test(Updater.appVersion)
                                          && /^v\d/.test(Server.backendVersion)
                                          && Updater.appVersion !== Server.backendVersion
    readonly property var status: {
        if (!Updater.loaded)
            return { level: "unknown", text: qsTr("Haetaan tietoja…") }
        if (development)
            return { level: "unknown", text: Updater.reason }
        if (doc.rollback)
            return { level: "error",
                     text: qsTr("%1 ei toiminut, joten %2 palautettiin (%3)")
                           .arg(doc.rollback.failed).arg(doc.rollback.restored)
                           .arg(doc.rollback.reason === "crashloop" ? qsTr("kaatui käynnistyessään")
                                                                   : qsTr("ei vastannut 5 minuutissa")) }
        if (doc.health)
            return { level: "warn", text: qsTr("Varmistetaan, että %1 toimii…").arg(doc.health.to) }
        if (doc.checkError)
            return { level: "warn", text: doc.checkError }
        if (Updater.newRelease !== "")
            return { level: "warn", text: qsTr("Uusi versio %1 on saatavilla").arg(Updater.newRelease) }
        return { level: "ok", text: qsTr("Ajan tasalla") }
    }

    // The open row, and the one whose Asenna waits for its second tap.
    property string expanded: ""
    property string armed: ""

    width: parent ? parent.width : 0
    spacing: 12

    onVisibleChanged: Updater.active = visible
    Component.onCompleted: Updater.active = visible
    Component.onDestruction: Updater.active = false

    Timer {
        id: disarm
        interval: 4000
        onTriggered: root.armed = ""
    }

    function dateText(iso) {
        return iso ? new Date(iso).toLocaleDateString(Qt.locale("fi_FI"), "d.M.yyyy") : ""
    }

    function warningFor(release) {
        if (release.direction !== "downgrade")
            return qsTr("Laite käynnistyy uudelleen. Jos uusi versio ei toimi viidessä minuutissa, "
                        + "edellinen palautetaan itsestään.")
        if (release.snapshot)
            return qsTr("Asetukset palautetaan sellaisiksi kuin ne olivat, kun versiosta %1 "
                        + "siirryttiin pois. Sen jälkeen tehdyt muutokset menetetään.").arg(release.tag)
        return qsTr("Versiota %1 ei ole ajettu tällä laitteella: se käynnistyy nykyisillä asetuksilla, "
                    + "joista se ei välttämättä tunne kaikkia.").arg(release.tag)
    }

    component Note: Text {
        width: root.width
        wrapMode: Text.WordWrap
        font.family: Theme.fontFamily
        font.pixelSize: 12
        color: Theme.dataLabelTitle
    }

    component Badge: Rectangle {
        property alias text: badgeText.text
        property color tint: Theme.accent
        width: badgeText.implicitWidth + 12
        height: 18
        radius: 9
        color: Qt.rgba(tint.r, tint.g, tint.b, 0.18)

        Text {
            id: badgeText
            anchors.centerIn: parent
            font.family: Theme.fontFamily
            font.pixelSize: 11
            color: parent.tint
        }
    }

    SettingDetails {
        width: root.width
        level: root.status.level
        statusText: root.status.text
        rows: {
            const out = [{ label: qsTr("Versio"), value: root.current.version || "—" }]
            if (root.development) {
                out.push({ label: qsTr("Commit"), value: (root.current.commit || "").substring(0, 7) || "—" })
                return out
            }
            if (root.doc.lastSwitch)
                out.push({ label: qsTr("Asennettu"),
                           value: qsTr("%1 → %2, %3").arg(root.doc.lastSwitch.from)
                                  .arg(root.doc.lastSwitch.to).arg(Format.moment(root.doc.lastSwitch.atMs)) })
            out.push({ label: qsTr("Tarkistettu"),
                       value: root.doc.checkedMs ? Format.moment(root.doc.checkedMs) : "—" })
            return out
        }
    }

    Note {
        visible: root.displayBehind
        color: "#ffd48a"
        text: qsTr("Päivitä tämä näyttö: näyttö on %1, palvelin %2. Näyttö päivitetään omalla laitteellaan.")
              .arg(Updater.appVersion).arg(Server.backendVersion)
    }

    // An install: running, or how the last one ended.
    Column {
        width: root.width
        spacing: 6
        visible: root.job !== null

        Text {
            width: root.width
            wrapMode: Text.WordWrap
            text: Updater.busy ? qsTr("Asennetaan %1").arg(root.job ? root.job.tag : "")
                               : (root.job ? root.job.message : "")
            font.family: Theme.fontFamily
            font.pixelSize: 14
            color: Updater.busy || root.job === null ? Theme.dataLabelValue
                 : root.job.ok ? "#4ade80" : "#f87171"
        }

        Repeater {
            model: root.job ? root.job.steps : []
            Row {
                id: step
                required property var modelData
                spacing: 8

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 8
                    height: 8
                    radius: 4
                    color: step.modelData.state === "done" ? "#4ade80"
                         : step.modelData.state === "running" ? Theme.accent
                         : step.modelData.state === "failed" ? "#f87171" : "#55ffffff"
                }
                Text {
                    text: step.modelData.label
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    color: step.modelData.state === "pending" ? Theme.dataLabelTitle : Theme.dataLabelValue
                }
            }
        }

        Rectangle {
            readonly property var progress: root.job ? root.job.progress : null
            visible: Updater.busy && progress !== null && progress !== undefined && progress.total > 0
                     && root.job.stepId === "download"
            width: root.width
            height: 4
            radius: 2
            color: "#33ffffff"

            Rectangle {
                width: parent.visible ? parent.width * Math.min(1, parent.progress.done / parent.progress.total) : 0
                height: parent.height
                radius: 2
                color: Theme.accent
            }
        }

        Note {
            visible: root.job !== null && root.job.log.length > 0 && (Updater.busy || !root.job.ok)
            text: root.job ? root.job.log.slice(-6).join("\n") : ""
            font.family: "monospace"
            font.pixelSize: 11
            maximumLineCount: 6
            elide: Text.ElideRight
        }

        DialogButton {
            visible: root.job !== null && root.job.cancellable === true
            label: qsTr("Peruuta")
            onActivated: Updater.cancel()
        }
    }

    // The releases, newest first.
    Column {
        width: root.width
        visible: !root.development && root.releases.length > 0

        Repeater {
            model: root.releases

            Item {
                id: row
                required property var modelData
                readonly property bool open: root.expanded === modelData.tag
                readonly property bool isArmed: root.armed === modelData.tag

                width: root.width
                height: content.implicitHeight + 20

                Rectangle {
                    width: parent.width
                    height: 1
                    color: "#1fffffff"
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: root.expanded = row.open ? "" : row.modelData.tag
                }

                Column {
                    id: content
                    y: 10
                    width: parent.width
                    spacing: 6

                    Row {
                        spacing: 8

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: row.modelData.tag
                            font.family: Theme.fontFamily
                            font.pixelSize: 14
                            color: Theme.dataLabelValue
                        }
                        Badge {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: row.modelData.direction === "current"
                            text: qsTr("Käytössä")
                            tint: "#4ade80"
                        }
                        Badge {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: row.modelData.tag === Updater.newRelease
                            text: qsTr("Uusi")
                        }
                        Badge {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: row.modelData.prerelease
                            text: qsTr("Esijulkaisu")
                            tint: "#ffb020"
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: [root.dateText(row.modelData.publishedAt),
                                   row.modelData.size > 0 && row.modelData.installable
                                       ? Format.bytes(row.modelData.size) : ""]
                                  .filter(s => s !== "").join(" · ")
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            color: Theme.dataLabelTitle
                        }
                    }

                    Note {
                        visible: !row.modelData.installable && row.modelData.direction !== "current"
                                 && row.modelData.reason !== ""
                        text: row.modelData.reason
                        color: "#ffd48a"
                    }

                    Note {
                        visible: row.open && row.modelData.notes !== ""
                        text: row.modelData.notes
                        maximumLineCount: 12
                        elide: Text.ElideRight
                    }

                    Note {
                        visible: row.open && row.modelData.installable
                        text: root.warningFor(row.modelData)
                        color: row.modelData.direction === "downgrade" && !row.modelData.snapshot
                               ? "#f87171" : "#ffd48a"
                    }

                    DialogButton {
                        visible: row.open && row.modelData.installable && !Updater.busy
                        primary: row.isArmed
                        label: row.isArmed ? qsTr("Vahvista: asenna %1").arg(row.modelData.tag)
                                           : (row.modelData.direction === "downgrade"
                                              ? qsTr("Palaa versioon %1").arg(row.modelData.tag)
                                              : qsTr("Asenna %1").arg(row.modelData.tag))
                        onActivated: {
                            if (row.isArmed) {
                                root.armed = ""
                                disarm.stop()
                                Updater.apply(row.modelData.tag)
                            } else {
                                root.armed = row.modelData.tag
                                disarm.restart()
                            }
                        }
                    }
                }
            }
        }
    }

    DialogButton {
        visible: !root.development && Updater.loaded
        enabled: !Updater.checking && !Updater.busy
        label: Updater.checking ? qsTr("Tarkistetaan…") : qsTr("Tarkista päivitykset")
        onActivated: Updater.check(true)
    }
}

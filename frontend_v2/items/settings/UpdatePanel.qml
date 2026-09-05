import QtQuick
import frontend_v2

// The "Päivitys" card: which version this dashboard is running, which one the
// selected channel offers, and the one button that moves between them.
//
// Rendered from the subsection's `status: "appUpdate"` key, the same hook the
// backend probe and the maintenance dashboard use. Everything it shows is the
// backend's UPDATE_STATE document, read defensively out of an opaque map — a
// deployment with no git reports `available: false` and this card explains that
// rather than offering a button that could not work.
//
// The CHANNEL SELECTOR lives here rather than as a settings row below, which is
// why `updateChannel` is a `hidden` schema entry. It decides what the verdict
// underneath it says, so it has to come first; and a two-way choice on a 10"
// touch panel is a pair of segments you hit with a fingertip, not a dropdown.
// The value is still an ordinary persisted local setting.
Item {
    id: panel

    readonly property string channel: {
        const saved = Settings.values.updateChannel
        return saved === "releases" ? "releases" : "development"
    }
    readonly property var current: Updater.state.current !== undefined
                                   ? Updater.state.current : ({})
    // Indexed straight out of `Updater.state`, NOT through a Q_INVOKABLE helper.
    // Calling an invokable registers no property dependency, so a binding built
    // on one never re-evaluates: the card would freeze on whatever state existed
    // when the Loader constructed it, while the sibling bindings that do read
    // `Updater.state` kept refreshing around it — a check time updating above a
    // stale version.
    readonly property var target: {
        const channels = Updater.state.channels
        if (channels === undefined || channels === null)
            return ({})
        const entry = channels[panel.channel]
        return entry !== undefined && entry !== null ? entry : ({})
    }
    readonly property var job: Updater.state.job !== undefined && Updater.state.job !== null
                               ? Updater.state.job : ({})
    readonly property bool hasJob: Object.keys(panel.job).length > 0
    readonly property string verdict: target.verdict !== undefined ? target.verdict : "unknown"
    readonly property var dirtyFiles: Updater.state.dirtyFiles !== undefined
                                      ? Updater.state.dirtyFiles : []

    // What stops an update right now, in the order the user should fix it. Empty
    // means the button is live.
    readonly property string blocker: {
        if (!Server.connected)
            return qsTr("Ei yhteyttä palvelimeen")
        if (Updater.loaded && !Updater.available)
            return Updater.reason
        if (Updater.state.dirty === true)
            return qsTr("Työhakemistossa on paikallisia muutoksia — päivitys ei ylikirjoita niitä")
        if (verdict === "unknown")
            return target.message !== undefined && target.message.length > 0
                   ? target.message : qsTr("Kohdeversiota ei voitu selvittää")
        // A target that does not itself carry the update card is a one-way door
        // on a device with no keyboard, so the backend refuses it and says so.
        if (verdict !== "up_to_date" && target.eligible === false)
            return target.eligibleReason !== undefined && target.eligibleReason.length > 0
                   ? target.eligibleReason : qsTr("Kohdeversioon ei voi siirtyä")
        // Everything a run needs, checked before the button rather than ten
        // minutes into it: uv, the build script, a Qt kit, disk headroom.
        const tools = Updater.state.tools !== undefined ? Updater.state.tools : ({})
        if (tools.blocker !== undefined && tools.blocker.length > 0)
            return tools.blocker
        return ""
    }

    readonly property bool canUpdate: blocker.length === 0 && !Updater.busy
                                      && verdict !== "up_to_date"
                                      && target.eligible === true
                                      && target.commit !== undefined
                                      && target.commit.length > 0

    implicitHeight: content.implicitHeight

    // Asking is gated on being on screen: the check contacts the remote, and a
    // settings section nobody opened must not do that. Mirrors SystemStatusPanel.
    onVisibleChanged: Updater.active = visible
    Component.onCompleted: Updater.active = visible
    Component.onDestruction: Updater.active = false

    // A tap arms, a second tap within four seconds runs — the same second-tap
    // confirmation SettingAction uses for the restart buttons, and for the same
    // reason: a stray palm must not start a ten-minute rebuild, and a modal would
    // need somewhere to put a Cancel button on a keyboard-less panel.
    property bool armed: false

    Timer {
        id: disarm
        interval: 4000
        onTriggered: panel.armed = false
    }

    // Arming is meaningless once the target or the ability to act on it changes.
    onCanUpdateChanged: { armed = false; disarm.stop() }

    function fmtDate(iso) {
        if (iso === undefined || iso === null || iso.length === 0)
            return ""
        const date = new Date(iso)
        return isNaN(date.getTime()) ? "" : Qt.formatDateTime(date, "d.M.yyyy HH:mm")
    }

    function fmtClock(ms) {
        if (ms === undefined || ms === null)
            return ""
        return Qt.formatDateTime(new Date(ms), "HH:mm")
    }

    function verdictColor(name) {
        switch (name) {
        case "up_to_date": return "#4ade80"
        case "update":     return Theme.accent
        case "downgrade":  return "#ffb020"
        case "switch":     return "#ffb020"
        default:           return Theme.dataLabelTitle
        }
    }

    function verdictText(name) {
        switch (name) {
        case "up_to_date": return qsTr("Ajan tasalla")
        case "update":     return qsTr("Päivitys saatavilla")
        case "downgrade":  return qsTr("Tarjolla on vanhempi versio")
        case "switch":     return qsTr("Eri kehityshaara")
        default:           return qsTr("Tuntematon")
        }
    }

    // The action's own wording. A downgrade and a branch switch are not
    // "updates", and calling them that on the button would be a lie about what
    // the next tap does.
    function actionText() {
        const name = target.label !== undefined ? target.label : ""
        switch (verdict) {
        case "update":    return qsTr("Päivitä") + (name.length > 0 ? " → " + name : "")
        case "downgrade": return qsTr("Palaa versioon") + " " + name
        case "switch":    return qsTr("Vaihda versioon") + " " + name
        default:          return qsTr("Päivitä")
        }
    }

    function distanceText() {
        const ahead = target.ahead !== undefined ? target.ahead : 0
        const behind = target.behind !== undefined ? target.behind : 0
        if (verdict === "update" && ahead > 0)
            return ahead + " " + qsTr("uutta committia")
        if (verdict === "downgrade" && behind > 0)
            return behind + " " + qsTr("committia taaksepäin")
        if (verdict === "switch")
            return ahead + " " + qsTr("eteen") + ", " + behind + " " + qsTr("taakse")
        return ""
    }

    Column {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 10

        // --- Channel ------------------------------------------------------
        Row {
            spacing: 10

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("Päivityskanava")
                font.family: Theme.fontFamily
                font.pixelSize: 12
                color: Theme.dataLabelTitle
            }

            Row {
                spacing: 0

                Repeater {
                    model: [
                        { "value": "development", "label": qsTr("Kehitys") },
                        { "value": "releases", "label": qsTr("Julkaisut") }
                    ]

                    Rectangle {
                        required property int index
                        required property var modelData

                        readonly property bool selected: panel.channel === modelData.value

                        width: 108
                        height: 32
                        color: selected ? Theme.accent
                             : (segmentTap.pressed ? Theme.tripComboPressed : Theme.tripComboBg)
                        border.width: 1
                        border.color: selected ? Theme.accent : Theme.tripCardBorder
                        // One pill split in two: only the outer corners round, so
                        // the pair reads as a single control rather than as two
                        // buttons that happen to be adjacent.
                        topLeftRadius: index === 0 ? 8 : 0
                        bottomLeftRadius: index === 0 ? 8 : 0
                        topRightRadius: index === 1 ? 8 : 0
                        bottomRightRadius: index === 1 ? 8 : 0

                        Behavior on color {
                            ColorAnimation { duration: Theme.pressDuration }
                        }

                        Text {
                            anchors.centerIn: parent
                            text: modelData.label
                            font.family: Theme.fontFamily
                            font.pixelSize: 13
                            color: parent.selected ? "#08192b" : Theme.dataLabelValue
                        }

                        MouseArea {
                            id: segmentTap
                            anchors.fill: parent
                            // Nothing may change the target under a run that is
                            // already applying one.
                            enabled: !Updater.busy
                            onClicked: {
                                if (!parent.selected)
                                    Settings.setValue("updateChannel", modelData.value)
                            }
                        }
                    }
                }
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: Updater.checking
                      ? qsTr("Tarkistetaan…")
                      : (Updater.state.fetchedMs
                         ? qsTr("Tarkistettu klo") + " " + panel.fmtClock(Updater.state.fetchedMs)
                         : "")
                font.family: Theme.fontFamily
                font.pixelSize: 11
                color: Theme.dataLabelTitle
            }
        }

        // --- Versions -----------------------------------------------------
        Row {
            width: parent.width
            spacing: 24
            visible: Updater.loaded && Updater.available

            // Asymmetric on purpose: the running version is a fact, the offered
            // one is the decision, so the offered column gets the extra room for
            // its commit subject.
            Column {
                width: (parent.width - 24) * 0.42
                spacing: 2

                Text {
                    text: qsTr("Käytössä")
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    color: Theme.dataLabelTitle
                }
                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    text: (panel.current.label !== undefined && panel.current.label.length > 0
                           ? panel.current.label : "—")
                          + (Updater.state.branch !== undefined && Updater.state.branch.length > 0
                             ? "  ·  " + Updater.state.branch : "")
                    font.family: Theme.fontFamily
                    font.pixelSize: 16
                    color: Theme.dataLabelValue
                }
                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    text: panel.fmtDate(panel.current.date)
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    color: Theme.dataLabelTitle
                }
                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    visible: text.length > 0
                    text: panel.current.subject !== undefined ? panel.current.subject : ""
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    color: Theme.dataLabelTitle
                }
            }

            Column {
                width: (parent.width - 24) * 0.58
                spacing: 2

                Text {
                    text: qsTr("Tarjolla")
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    color: Theme.dataLabelTitle
                }

                Row {
                    width: parent.width
                    spacing: 8

                    Text {
                        text: (panel.target.label !== undefined && panel.target.label.length > 0
                               ? panel.target.label : "—")
                        font.family: Theme.fontFamily
                        font.pixelSize: 16
                        color: Theme.dataLabelValue
                    }

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: verdictLabel.implicitWidth + 16
                        height: 20
                        radius: 10
                        color: Qt.rgba(0, 0, 0, 0.25)
                        border.width: 1
                        border.color: panel.verdictColor(panel.verdict)

                        Text {
                            id: verdictLabel
                            anchors.centerIn: parent
                            text: panel.verdictText(panel.verdict)
                            font.family: Theme.fontFamily
                            font.pixelSize: 11
                            color: panel.verdictColor(panel.verdict)
                        }
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: text.length > 0
                        text: panel.distanceText()
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        color: Theme.dataLabelTitle
                    }
                }

                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    text: panel.fmtDate(panel.target.date)
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    color: Theme.dataLabelTitle
                }
                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    visible: text.length > 0
                    text: panel.target.subject !== undefined ? panel.target.subject : ""
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    color: Theme.dataLabelTitle
                }
            }
        }

        // --- Why the button is not live -----------------------------------
        Column {
            width: parent.width
            spacing: 2
            visible: panel.blocker.length > 0 && !panel.hasJob

            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                text: panel.blocker
                font.family: Theme.fontFamily
                font.pixelSize: 12
                color: "#ffd48a"
            }

            // Naming the files is the whole point: "there are local changes" on a
            // screen with no shell is not something the user can act on.
            Repeater {
                model: panel.dirtyFiles

                Text {
                    required property var modelData
                    width: content.width
                    elide: Text.ElideMiddle
                    text: "· " + modelData
                    font.family: Theme.fontFamily
                    font.pixelSize: 10
                    color: Theme.dataLabelTitle
                }
            }
        }

        // --- Actions ------------------------------------------------------
        Row {
            spacing: 10
            visible: !Updater.busy

            Rectangle {
                width: 150
                height: 34
                radius: 8
                opacity: Server.connected && !Updater.checking ? 1.0 : 0.4
                color: checkTap.pressed ? Theme.tripComboPressed : Theme.tripComboBg
                border.width: 1
                border.color: Theme.tripCardBorder

                Text {
                    anchors.centerIn: parent
                    text: qsTr("Tarkista")
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: Theme.dataLabelValue
                }

                MouseArea {
                    id: checkTap
                    anchors.fill: parent
                    enabled: Server.connected && !Updater.checking
                    onClicked: Updater.check(true)
                }
            }

            Rectangle {
                width: Math.max(190, actionLabel.implicitWidth + 32)
                height: 34
                radius: 8
                opacity: panel.canUpdate ? 1.0 : 0.4
                color: !panel.armed
                       ? (applyTap.pressed ? Theme.tripComboPressed : Theme.tripComboBg)
                       : (applyTap.pressed ? "#ccffb020" : "#99ffb020")
                border.width: 1
                border.color: panel.armed ? "#80ffb020" : Theme.tripCardBorder

                Behavior on color {
                    ColorAnimation { duration: Theme.pressDuration }
                }

                Text {
                    id: actionLabel
                    anchors.centerIn: parent
                    text: panel.armed ? qsTr("Vahvista") : panel.actionText()
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: panel.armed ? "#1a1206" : Theme.dataLabelValue
                }

                MouseArea {
                    id: applyTap
                    anchors.fill: parent
                    enabled: panel.canUpdate
                    onClicked: {
                        if (panel.armed) {
                            panel.armed = false
                            disarm.stop()
                            Updater.apply(panel.channel, panel.target.commit)
                        } else {
                            panel.armed = true
                            disarm.restart()
                        }
                    }
                }
            }
        }

        // --- The run ------------------------------------------------------
        Column {
            width: parent.width
            spacing: 6
            visible: panel.hasJob

            Rectangle {
                width: parent.width
                height: 1
                color: "#1affffff"
            }

            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                visible: text.length > 0
                text: {
                    if (panel.job.message !== undefined && panel.job.message.length > 0)
                        return panel.job.message
                    if (panel.job.targetLabel !== undefined && panel.job.targetLabel.length > 0)
                        return qsTr("Päivitetään versioon") + " " + panel.job.targetLabel
                    return ""
                }
                font.family: Theme.fontFamily
                font.pixelSize: 13
                color: panel.job.ok === false ? "#f87171"
                     : panel.job.ok === true ? "#4ade80" : Theme.dataLabelValue
            }

            // Step list. A failed run leaves the steps after the failure PENDING
            // rather than marking them failed: they never ran, and saying
            // otherwise would point at the wrong step.
            Repeater {
                model: panel.job.steps !== undefined ? panel.job.steps : []

                Row {
                    required property var modelData
                    spacing: 8

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 7
                        height: 7
                        radius: 3.5
                        color: modelData.state === "done" ? "#4ade80"
                             : modelData.state === "running" ? Theme.accent
                             : modelData.state === "failed" ? "#f87171"
                             : Theme.sliderGroove

                        SequentialAnimation on opacity {
                            running: modelData.state === "running"
                            loops: Animation.Infinite
                            NumberAnimation { to: 0.25; duration: 600 }
                            NumberAnimation { to: 1.0; duration: 600 }
                        }
                    }

                    Text {
                        text: modelData.label
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        color: modelData.state === "pending"
                               ? Theme.dataLabelTitle : Theme.dataLabelValue
                    }
                }
            }

            // The tail of the command output. A build that fails explains itself
            // in its last few lines, and on this device there is no journal to
            // go and read instead.
            Column {
                width: parent.width
                spacing: 0
                visible: logView.count > 0

                Repeater {
                    id: logView
                    model: {
                        const lines = panel.job.log !== undefined ? panel.job.log : []
                        return lines.slice(Math.max(0, lines.length - 6))
                    }

                    Text {
                        required property var modelData
                        width: content.width
                        elide: Text.ElideRight
                        text: modelData
                        font.family: "monospace"
                        font.pixelSize: 10
                        color: Theme.dataLabelTitle
                    }
                }
            }

            Rectangle {
                visible: Updater.busy && panel.job.cancellable === true
                width: 150
                height: 32
                radius: 8
                color: cancelTap.pressed ? Theme.tripComboPressed : Theme.tripComboBg
                border.width: 1
                border.color: Theme.tripCardBorder

                Text {
                    anchors.centerIn: parent
                    text: qsTr("Peruuta")
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: Theme.dataLabelValue
                }

                MouseArea {
                    id: cancelTap
                    anchors.fill: parent
                    onClicked: Updater.cancel()
                }
            }
        }

        // --- This binary is older than the checkout ------------------------
        // Only possible if a restart was missed (a failed build that still moved
        // the tree, or a rollback that did not run). Worth saying out loud: every
        // version figure above describes the REPOSITORY, and until this is
        // resolved the dashboard on screen is not that version.
        Text {
            width: parent.width
            wrapMode: Text.WordWrap
            visible: Updater.restartPending
            text: qsTr("Käyttöliittymä on käännetty versiosta")
                  + " " + Updater.buildCommit.substring(0, 7) + " — "
                  + qsTr("käynnistä sovellus uudelleen Ylläpito-osiosta")
            font.family: Theme.fontFamily
            font.pixelSize: 12
            color: "#ffd48a"
        }

        // --- Where this checkout lives ------------------------------------
        Text {
            width: parent.width
            elide: Text.ElideMiddle
            visible: Updater.available && text.length > 0
            text: {
                const path = Updater.state.repoPath !== undefined ? Updater.state.repoPath : ""
                const remote = Updater.state.remoteUrl !== undefined ? Updater.state.remoteUrl : ""
                if (path.length === 0)
                    return ""
                return path + (remote.length > 0 ? "  ·  " + remote : "")
            }
            font.family: Theme.fontFamily
            font.pixelSize: 10
            color: Theme.dataLabelTitle
        }
    }
}

import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import frontend_v2

// Options view ("Asetukset"): a master/detail settings screen — sections down the
// left, the selected section's settings filling the pane on the right.
//
// Both halves are rendered from schemas rather than hand-laid rows: the sidebar
// lists the groups, the pane lists that group's settings, and both local
// (config/settings.json) and backend (config_service.SETTINGS_SCHEMA) sources
// flow through the same code. Adding a tunable anywhere adds a row here with no
// QML change.
//
// Selection is held as a group ID, not an index: the section list grows from
// three entries to eight when the backend's schema arrives, and shrinks again if
// the backend disappears, so an index would quietly select a different section.
//
// State is preserved across view switches (ViewController keeps views alive), so
// the section you were on is still selected when you come back. No per-frame work
// happens here.
Rectangle {
    id: view

    property bool isCurrent: false
    color: Theme.tripBackground

    // The section the user last CHOSE. Deliberately kept even while that section
    // is absent from the list: the backend's five sections disappear when the
    // connection drops and come back when it returns, and overwriting this on
    // every list change would bounce the user to the first section and leave them
    // there after a reconnect. Only a tap changes it.
    property string currentSectionId: ""

    // A device scan must not outlive the screen that started it: the popup is a
    // child of this view, so leaving for the dashboard hides it while the backend
    // keeps polling Spotify every 2 s — with the radio silenced — for the whole
    // 300 s TTL, and coming back resurrects a stale dialog. Cancelling here is
    // what sends SPOTIFY_DEVICE_SCAN_STOP.
    onIsCurrentChanged: {
        if (!isCurrent && SpotifyDevice.phase !== "idle")
            SpotifyDevice.cancel()
        // Same reasoning, cheaper stakes: ViewController keeps this view alive, so
        // the issues box or the spotlight left standing would still be there on
        // return, with the settings underneath unreachable. The USB import closes
        // too (unmounting the stick) — but not mid-copy: the home return fires
        // after minutes without a touch, which a long copy easily outlasts, and
        // the dialog is simply still there on the way back.
        if (!isCurrent) {
            if (UsbImport.phase !== "copying")
                UsbImport.close()
            issuesPopup.close()
            spotlight.dismiss()
        } else {
            // The device checks in SettingsIssues read this; throttled in C++.
            SpotifyDevice.refreshStatus()
        }
    }

    // The last write result, shown beside the title of the row that made it
    // (SettingsPane.rowFeedback explains why the view holds it).
    property var rowFeedback: ({ key: "", text: "", error: false })

    readonly property var allGroups: Settings.groups

    // The section actually shown: the chosen one when it exists, otherwise the
    // first available. Resolving on read (rather than writing back to
    // currentSectionId) is what makes the choice survive a reconnect.
    readonly property var currentGroup: {
        for (let i = 0; i < allGroups.length; ++i) {
            if (allGroups[i].id === currentSectionId)
                return allGroups[i]
        }
        return allGroups.length > 0 ? allGroups[0] : undefined
    }

    function showFeedback(key, message, isError) {
        // A result with no row to sit beside — a refused restart, a lost
        // connection — goes to the app's notification pill instead.
        if (key.length === 0 || pane.rowItem(key) === null) {
            Notifications.post("settings", message)
            return
        }
        rowFeedback = { key: key, text: message, error: isError }
        feedbackTimer.interval = isError ? 6000 : 2500
        feedbackTimer.restart()
    }

    Timer {
        id: feedbackTimer
        onTriggered: view.rowFeedback = { key: "", text: "", error: false }
    }

    SettingsIssues {
        id: issueDetector
    }

    Connections {
        target: Settings

        // Actions Settings does not handle itself belong to a view. The Spotify
        // re-authorization is one: the backend owns the exchange, but the consent
        // page is a UI concern and lives here. Device identification is the same
        // shape — the backend does the scanning, this side only shows it.
        function onActionRequested(key) {
            if (key === "spotifyReauth")
                SpotifyAuth.begin()
            else if (key === "spotifyIdentifyDevice")
                SpotifyDevice.begin()
            else if (key === "screensaverImport")
                UsbImport.begin()
        }

        function onWriteFailed(key, message) {
            view.showFeedback(key, message, true)
        }

        // A restart-tier write needs no wording of its own: the row already
        // carries its "uudelleenkäynnistys" badge and the restart banner appears.
        function onWriteSucceeded(key, applied) {
            if (applied !== "unchanged")
                view.showFeedback(key, qsTr("Tallennettu"), false)
        }
    }

    // --- Screen content ---------------------------------------------------
    // Everything the view normally shows, in one container purely so the device
    // dialog can blur it. The blur is applied as a LAYER EFFECT on this item
    // rather than as a sibling MultiEffect reading it as a source: a sibling
    // would draw the blurred copy ON TOP of the still-crisp original, which
    // shows through anywhere the content is not opaque. A layer replaces the
    // item's own rendering, so there is exactly one image on screen.
    //
    // The layer (an offscreen FBO plus a blur shader every frame) exists only
    // while the dialog is up; the rest of the time this is a plain Item and
    // costs nothing. If it proves too heavy on the Pi, the lever is
    // `layer.textureSize` at half resolution — a blur hides the downscale.
    Item {
        id: content
        anchors.fill: parent

        layer.enabled: devicePopup.visible || usbImportPopup.visible || issuesPopup.visible
                       || spotlight.active
        layer.effect: MultiEffect {
            blurEnabled: true
            blur: 1.0
            // Well below GlassPanel's 64: this covers the whole 1280x800 view
            // rather than a dock-sized strip, and the extra passes buy nothing
            // once the content is unreadable, which is the entire point.
            blurMax: 32
            // The blurred image must stay exactly the view's size; padding would
            // grow the layer past the screen edges.
            autoPaddingEnabled: false
        }

        // --- Header -----------------------------------------------------------
        Item {
            id: header
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Theme.gridMargin
            height: 40

            Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("Asetukset")
                font.family: Theme.fontFamily
                font.pixelSize: 24
                color: Theme.dataLabelValue
            }

            // Only when something is wrong. A lost backend is one of the issues,
            // which is what keeps a screen showing only the local sections from
            // reading as a bug.
            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10
                visible: issueDetector.issues.length > 0

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 8
                    height: 8
                    radius: 4
                    color: issueDetector.hasErrors ? "#f87171" : "#ffb020"
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: qsTr("Ongelmia havaittu")
                    font.family: Theme.fontFamily
                    font.pixelSize: 14
                    color: issueDetector.hasErrors ? "#f87171" : "#ffd48a"
                }

                DialogButton {
                    anchors.verticalCenter: parent.verticalCenter
                    label: qsTr("Tarkista")
                    onActivated: issuesPopup.open()
                }
            }
        }

        // --- Restart banner ---------------------------------------------------
        // Appears only once a restart-tier setting has actually been WRITTEN, so a
        // restart is never suggested speculatively. The two halves are independent:
        // backendHost/Port are consumed by AppConfig here, timeZone and friends are
        // consumed by the backend's services, and each is fixed by restarting a
        // different process. The Yllapito section carries the same two buttons
        // permanently, for when something is wedged rather than pending.
        Rectangle {
            id: restartBanner
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: header.bottom
            anchors.leftMargin: Theme.gridMargin
            anchors.rightMargin: Theme.gridMargin
            anchors.topMargin: visible ? 6 : 0
            height: visible ? 46 : 0
            visible: Settings.restartPending || Settings.appRestartPending
            radius: Theme.tripCardRadius
            color: "#33ffb020"
            border.width: 1
            border.color: "#80ffb020"

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.right: restartButtons.left
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: {
                    if (Settings.restartPending && Settings.appRestartPending)
                        return qsTr("Muutokset vaativat sovelluksen ja palvelimen uudelleenkäynnistyksen")
                    if (Settings.appRestartPending)
                        return qsTr("Muutokset vaativat sovelluksen uudelleenkäynnistyksen")
                    return qsTr("Muutokset vaativat palvelimen uudelleenkäynnistyksen")
                }
                font.family: Theme.fontFamily
                font.pixelSize: 14
                color: "#ffd48a"
                elide: Text.ElideRight
            }

            Row {
                id: restartButtons
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8

                // One button per pending restart, each labelled with WHAT it restarts
                // — "Käynnistä uudelleen" alone would be ambiguous when both are up.
                Repeater {
                    model: [
                        { "label": qsTr("Sovellus"), "app": true,
                          "shown": Settings.appRestartPending },
                        { "label": qsTr("Palvelin"), "app": false,
                          "shown": Settings.restartPending }
                    ]

                    Rectangle {
                        required property var modelData

                        visible: modelData.shown
                        width: visible ? actionLabel.implicitWidth + 28 : 0
                        height: 32
                        radius: 8
                        // This is the SECOND way to reach the same two restarts —
                        // SettingAction's rows in Ylläpito are the first — so it
                        // carries the same gate. An update is minutes of checkout,
                        // build and dependency sync, and the backend vetoes a
                        // restart for the whole of it; a button that fires into a
                        // veto is a button that does nothing.
                        opacity: Updater.busy ? 0.4 : 1.0
                        color: buttonArea.pressed ? "#ccffb020" : "#99ffb020"

                        Text {
                            id: actionLabel
                            anchors.centerIn: parent
                            text: qsTr("Käynnistä") + " · " + modelData.label
                            font.family: Theme.fontFamily
                            font.pixelSize: 13
                            color: "#1a1206"
                        }

                        MouseArea {
                            id: buttonArea
                            anchors.fill: parent
                            enabled: !Updater.busy
                            onClicked: {
                                if (modelData.app) {
                                    Notifications.post("settings", qsTr("Sovellus käynnistyy uudelleen…"))
                                    Settings.restartApp()
                                } else {
                                    // No optimistic message here: the backend can
                                    // REFUSE this one (a keyless CONFIG_SET_RESULT,
                                    // which lands in the notification pill), and a
                                    // cheerful "restarting…" queued ahead of the
                                    // refusal would contradict it.
                                    Settings.requestBackendRestart()
                                }
                            }
                        }
                    }
                }
            }
        }

        // --- Master / detail --------------------------------------------------
        SettingsSidebar {
            id: sidebar
            anchors.left: parent.left
            anchors.top: restartBanner.bottom
            anchors.bottom: parent.bottom
            anchors.leftMargin: Theme.gridMargin
            anchors.topMargin: 8
            // Clear of the dock's swipe zone and the home indicator.
            anchors.bottomMargin: Theme.gridMargin + 28
            width: 260

            groups: view.allGroups
            currentId: view.currentGroup !== undefined ? view.currentGroup.id : ""
            onSectionSelected: (id) => view.currentSectionId = id
        }

        SettingsPane {
            id: pane
            anchors.left: sidebar.right
            anchors.right: parent.right
            anchors.top: sidebar.top
            anchors.bottom: sidebar.bottom
            // Same gutter as the margin between the cards and the screen edge, so the
            // two panels read as one grid rather than a pair with a wider seam.
            anchors.leftMargin: Theme.gridMargin
            anchors.rightMargin: Theme.gridMargin

            groupData: view.currentGroup
            rowFeedback: view.rowFeedback
        }
    }

    // --- Device identification --------------------------------------------
    // Deliberately a child of THIS view rather than of Main.qml, unlike the
    // re-authorization prompt: a device scan can only ever be started from the
    // Spotify card a few pixels above, so it belongs to this screen and darkens
    // only this screen. Last child so it stacks over the sidebar and the pane,
    // and OUTSIDE `content` so it is not swept into the blur it asks for.
    SpotifyDevicePopup {
        id: devicePopup
        anchors.fill: parent
    }

    // The screensaver photo import, opened by the Kuvakansio row's "Tuo USB:ltä".
    // Same placement rule and reasons as the device dialog.
    UsbImportPopup {
        id: usbImportPopup
        anchors.fill: parent
    }

    // --- Issues -------------------------------------------------------------
    // The header's "Tarkista" opens this; "Korjaa" closes it, selects the section
    // holding the fix and spotlights that row. Both outside `content`, like the
    // dialogs above, so the blur they ask for does not swallow them.
    SettingsIssuesPopup {
        id: issuesPopup
        anchors.fill: parent
        issues: issueDetector.issues
        onFixRequested: (issue) => {
            issuesPopup.close()
            view.currentSectionId = issue.section
            spotlight.show(issue.key)
        }
    }

    SettingSpotlight {
        id: spotlight
        anchors.fill: parent
        pane: pane
    }
}

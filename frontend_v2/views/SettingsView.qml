import QtQuick
import QtQuick.Controls
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

    // Transient result banner (a rejected value, a confirmed write).
    property string toastText: ""
    property bool toastIsError: false

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

    function showToast(message, isError) {
        toastText = message
        toastIsError = isError
        toastTimer.restart()
    }

    Timer {
        id: toastTimer
        interval: 4000
        onTriggered: view.toastText = ""
    }

    Connections {
        target: Settings

        function onWriteFailed(key, message) {
            view.showToast(key.length > 0 ? key + ": " + message : message, true)
        }

        function onWriteSucceeded(key, applied) {
            if (applied === "restart")
                view.showToast(qsTr("Tallennettu — vaatii uudelleenkäynnistyksen"), false)
            else if (applied !== "unchanged")
                view.showToast(qsTr("Tallennettu"), false)
        }
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

        // Connection state: without it, a settings screen showing only the three
        // local sections reads as a bug rather than "the backend isn't there".
        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 8
                height: 8
                radius: 4
                color: Server.connected ? "#4ade80" : "#f87171"
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: Server.connected ? qsTr("Yhdistetty") : Server.stateText
                font.family: Theme.fontFamily
                font.pixelSize: 13
                color: Theme.dataLabelTitle
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
                        onClicked: {
                            if (modelData.app) {
                                view.showToast(qsTr("Sovellus käynnistyy uudelleen…"), false)
                                Settings.restartApp()
                            } else {
                                Settings.requestBackendRestart()
                                view.showToast(qsTr("Palvelin käynnistyy uudelleen…"), false)
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
        anchors.bottom: footer.top
        anchors.leftMargin: Theme.gridMargin
        anchors.topMargin: 8
        anchors.bottomMargin: 6
        width: 260

        groups: view.allGroups
        currentId: view.currentGroup !== undefined ? view.currentGroup.id : ""
        onSectionSelected: (id) => view.currentSectionId = id
    }

    SettingsPane {
        anchors.left: sidebar.right
        anchors.right: parent.right
        anchors.top: sidebar.top
        anchors.bottom: sidebar.bottom
        anchors.leftMargin: 18
        anchors.rightMargin: Theme.gridMargin

        groupData: view.currentGroup
    }

    // --- Footer -----------------------------------------------------------
    Item {
        id: footer
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        // Clear of the dock's swipe zone and the home indicator.
        anchors.bottomMargin: Theme.gridMargin + 28
        anchors.leftMargin: Theme.gridMargin
        anchors.rightMargin: Theme.gridMargin
        height: 18

        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width * 0.6
            text: Settings.storagePath
            font.family: Theme.fontFamily
            font.pixelSize: 10
            color: Theme.dataLabelTitle
            elide: Text.ElideMiddle
        }

        // Transient write result, right-aligned so it never reflows the list.
        Text {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width * 0.4
            horizontalAlignment: Text.AlignRight
            text: view.toastText
            visible: view.toastText.length > 0
            font.family: Theme.fontFamily
            font.pixelSize: 12
            color: view.toastIsError ? "#f87171" : "#4ade80"
            elide: Text.ElideLeft
        }
    }
}

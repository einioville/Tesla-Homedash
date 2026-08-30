import QtQuick
import frontend_v2

// One settings row: label + optional help/unit on the left, a type-appropriate
// editor on the right, and a badge when the value only takes effect after a
// restart.
//
// This is the whole reason the settings are schema-driven: the row picks its
// editor from `setting.type` rather than being hand-written per setting, so a new
// tunable — local (config/settings.json) or backend (config_service's
// SETTINGS_SCHEMA) — appears here with no QML change at all.
//
// `setting` is one entry from Settings.groups: key, type, label, help, unit,
// min/max/step, options, value, apply ("live"/"hook"/"restart"), origin
// ("local"/"backend"), an optional editor hint, and for local ones, modified.
Item {
    id: row

    required property var setting

    // Width given to the editor on the right. The detail pane widens this from
    // the default now that one section fills the screen.
    property int editorWidth: 240

    readonly property bool needsRestart: setting.apply === "restart"
    readonly property bool isLocal: setting.origin === "local"

    // A setting can declare that it only MATTERS while another setting holds a
    // particular value — the screensaver's dwell time means nothing with the
    // screensaver off. Such a row is faded AND inert — see `enabled` below.
    //
    // The rule may name a setting in EITHER half, so the value is resolved via
    // Settings.valueOf rather than Settings.values, which knows only local keys.
    // valuesRevision is read purely to make this binding re-evaluate: an
    // invokable call captures no property to depend on.
    readonly property bool relevant: {
        const revision = Settings.valuesRevision
        const dep = row.setting.relevantWhen
        if (dep === undefined || dep === null || dep.key === undefined)
            return true
        const current = Settings.valueOf(dep.key)
        if (dep.equals !== undefined)
            return current === dep.equals
        if (dep.notEquals !== undefined)
            return current !== dep.notEquals
        return true
    }

    opacity: relevant ? 1.0 : Theme.settingIrrelevantOpacity
    // Blocks every editor in the row at once: `enabled` propagates down the
    // item tree, so no MouseArea, TextField, Slider or ComboBox below needs
    // to know about relevance. A control that changes a value with no effect
    // is worse than one that visibly cannot be used.
    enabled: relevant

    Behavior on opacity {
        NumberAnimation { duration: Theme.pressDuration }
    }

    // Advisory bounds: a value that is VALID but unwise. min/max still bound what
    // can be entered — this only warns, and never blocks a write, because the
    // user may well have a reason (see the myenergi poll interval, where too
    // frequent a poll earns 429s from the cloud and a deepening backoff).
    readonly property bool warned: {
        const v = setting.value
        if (typeof v !== "number")
            return false
        if (setting.warnBelow !== undefined && v < setting.warnBelow)
            return true
        return setting.warnAbove !== undefined && v > setting.warnAbove
    }

    implicitHeight: Math.max(56, labelColumn.implicitHeight + 20)

    // --- Left: label, help text, restart badge ---------------------------
    Column {
        id: labelColumn
        anchors.left: parent.left
        anchors.right: editorLoader.left
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2

        Row {
            spacing: 8

            Text {
                text: row.setting.label !== undefined ? row.setting.label : row.setting.key
                font.family: Theme.fontFamily
                font.pixelSize: 15
                color: Theme.dataLabelValue
                anchors.verticalCenter: parent.verticalCenter
            }

            // Restart badge. Deliberately per-row rather than one banner: which
            // settings are restart-tier depends on the deployment (the backend
            // downgrades a hook setting to restart when its service is absent),
            // so the honest place to say it is next to the value itself.
            Rectangle {
                visible: row.needsRestart
                anchors.verticalCenter: parent.verticalCenter
                width: badgeText.implicitWidth + 12
                height: badgeText.implicitHeight + 4
                radius: 4
                color: "#33ffb020"
                border.width: 1
                border.color: "#80ffb020"

                Text {
                    id: badgeText
                    anchors.centerIn: parent
                    text: qsTr("uudelleenkäynnistys")
                    font.family: Theme.fontFamily
                    font.pixelSize: 10
                    color: "#ffd48a"
                }
            }

            // Marks a local setting the user has changed away from its default,
            // so "what have I touched?" is answerable at a glance.
            Text {
                visible: row.isLocal && row.setting.modified === true
                anchors.verticalCenter: parent.verticalCenter
                text: "•"
                font.pixelSize: 16
                color: Theme.accent
            }
        }

        Text {
            visible: text.length > 0
            width: labelColumn.width
            text: row.setting.help !== undefined ? row.setting.help : ""
            font.family: Theme.fontFamily
            font.pixelSize: 12
            color: Theme.dataLabelTitle
            wrapMode: Text.WordWrap
        }

        // Only while the threshold is actually crossed, so it reads as a
        // consequence of the current value rather than as permanent small print.
        Row {
            visible: row.warned
            spacing: 6

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "⚠"
                font.pixelSize: 12
                color: "#ffb020"
            }

            Text {
                width: labelColumn.width - 18
                text: row.setting.warnMessage !== undefined ? row.setting.warnMessage : ""
                font.family: Theme.fontFamily
                font.pixelSize: 12
                color: "#ffd48a"
                wrapMode: Text.WordWrap
            }
        }
    }

    // --- Right: the editor ------------------------------------------------
    Loader {
        id: editorLoader
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: row.setting.type === "bool" ? 56 : row.editorWidth

        sourceComponent: {
            switch (row.setting.type) {
            case "bool":
                return switchComponent
            case "int":
            case "float":
                // Sliders are OPT-IN. They only work when the exact number does
                // not matter; for a port, a tariff or an interval you need to hit
                // a specific value, and a 65534-step track cannot do that. The
                // schema marks the few genuine "feel" dials with editor: "slider".
                return row.setting.editor === "slider" ? sliderComponent : numberComponent
            case "enum":
                return selectComponent
            case "action":
                return actionComponent
            default:
                return textComponent
            }
        }
    }

    Component {
        id: switchComponent
        SettingSwitch { setting: row.setting }
    }
    Component {
        id: sliderComponent
        SettingSlider { setting: row.setting }
    }
    Component {
        id: numberComponent
        SettingNumber { setting: row.setting }
    }
    Component {
        id: selectComponent
        SettingSelect { setting: row.setting }
    }
    Component {
        id: textComponent
        SettingText { setting: row.setting }
    }
    Component {
        id: actionComponent
        SettingAction { setting: row.setting }
    }
}

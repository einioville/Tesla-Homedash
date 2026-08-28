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

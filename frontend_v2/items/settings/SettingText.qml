import QtQuick
import QtQuick.Controls
import frontend_v2

// String editor: a dark-themed single-line field.
//
// Commits on editingFinished (Enter or focus loss), never per keystroke — a
// backend key would otherwise send a CONFIG_SET, and get a rejection, for every
// intermediate prefix as the user types ("E", "Eu", "Eur"...).
//
// A rejected write leaves the field showing what the user typed while `setting`
// still holds the old value; SettingsView surfaces the reason, and moving away
// and back re-syncs from the authoritative value.
Item {
    id: control

    required property var setting

    implicitWidth: 240
    implicitHeight: 36

    // Re-sync from the authoritative value unless the user is mid-edit.
    onSettingChanged: if (!field.activeFocus) field.text = control.currentText()

    function currentText() {
        const value = control.setting.value
        return value === undefined || value === null ? "" : String(value)
    }

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: field.activeFocus ? Theme.tripComboPressed : Theme.tripComboBg
        border.width: 1
        border.color: field.activeFocus ? Theme.accent : Theme.tripCardBorder

        TextField {
            id: field
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            text: control.currentText()
            font.family: Theme.fontFamily
            font.pixelSize: 14
            color: Theme.dataLabelValue
            selectByMouse: true
            verticalAlignment: TextInput.AlignVCenter
            // The surrounding Rectangle is the visual field; the control's own
            // Basic-style background would paint a light box over the dark theme.
            background: null
            // The values typed here are hosts, URLs, serial numbers and place
            // names: the on-screen keyboard's sentence capitalisation would mangle
            // most of them, and prediction holds text in pre-edit, off `text`.
            inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
            // A `secret` setting (an API key) is masked on a panel anyone walks
            // past, and shown in full only while it is being edited — a key typed
            // blind on a touch keyboard would never come out right.
            echoMode: control.setting.secret === true && !activeFocus
                      ? TextInput.Password : TextInput.Normal

            // Enter commits (editingFinished follows) and closes the keyboard,
            // leaving focus where it is — clearing focus here would fire
            // editingFinished a second time and send the same write twice.
            onAccepted: Qt.inputMethod.hide()

            onEditingFinished: {
                if (text !== control.currentText())
                    Settings.setValue(control.setting.key, text)
            }
        }
    }
}

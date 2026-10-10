import QtQuick
import frontend_v2

// Boolean editor: the shared ToggleSwitch over one setting.
//
// The value is the schema's; a tap round-trips through Settings (and, for a
// backend key, the server) rather than being held here. The knob moves when
// the new value comes back, which the row lives through: rows survive a write
// (SettingsPane), so the switch animates instead of reappearing already moved.
ToggleSwitch {
    id: control

    required property var setting

    checked: setting.value === true
    onToggled: Settings.setValue(control.setting.key, !control.checked)
}

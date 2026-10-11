import QtQuick
import frontend_v2

// Enum editor. Reuses TripComboBox so the dark field/popup/delegate styling — and
// the two dropdown fixes it carries (the opaque row background from issue #9, the
// padding/elide fix from #19) — apply here for free rather than being rebuilt.
//
// Options arrive as [{value, label}] from the schema. The backend resolves dynamic
// ones (audio.outputDevice's choices are the host's audio sinks), so this delegate
// never has to know where a list comes from.
TripComboBox {
    id: control

    required property var setting

    // Guards the initial currentIndex assignment: setting currentIndex fires
    // activated-free currentIndexChanged, and writing from that would push the
    // schema's own value straight back at the backend on every rebuild.
    property bool syncing: true

    readonly property var options: setting.options !== undefined ? setting.options : []

    implicitWidth: 240
    implicitHeight: 40

    model: options
    textRole: "label"

    formatEntry: function (entry) {
        if (entry === undefined || entry === null)
            return ""
        return entry.label !== undefined ? entry.label : String(entry.value)
    }

    function indexOfValue(value) {
        for (let i = 0; i < options.length; ++i) {
            if (options[i].value === value)
                return i
        }
        return -1
    }

    function syncFromSetting() {
        syncing = true
        currentIndex = indexOfValue(setting.value)
        syncing = false
    }

    onSettingChanged: syncFromSetting()
    Component.onCompleted: syncFromSetting()

    // `activated` (not currentIndexChanged) so only a real user choice writes.
    //
    // A value named in the setting's `onSelect` runs that action INSTEAD of being
    // written — a dialog that asks something first and writes the value itself
    // (DEBUG asks for how long). The field shows the current value again until
    // that write comes back, so a cancelled dialog leaves nothing to undo; and it
    // runs even when the value is already chosen, which is how the duration of a
    // running DEBUG is changed.
    onActivated: function (index) {
        if (syncing || index < 0 || index >= options.length)
            return
        const chosen = options[index].value
        const action = setting.onSelect !== undefined ? setting.onSelect[String(chosen)] : undefined
        if (action !== undefined) {
            syncFromSetting()
            Settings.invokeAction(action)
        } else if (chosen !== setting.value) {
            Settings.setValue(setting.key, chosen)
        }
    }
}

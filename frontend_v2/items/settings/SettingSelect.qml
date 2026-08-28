import QtQuick
import QtQuick.Controls
import frontend_v2

// Enum editor. Reuses TripComboBox so the dark field/popup/delegate styling — and
// the two dropdown fixes it carries (the opaque row background from issue #9, the
// padding/elide fix from #19) — apply here for free rather than being rebuilt.
//
// Options arrive as [{value, label}] from the schema. The backend resolves dynamic
// ones (defaultRadioStation's choices are the configured radioMediaIds keys), so
// this delegate never has to know where a list comes from.
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
    onActivated: function (index) {
        if (syncing || index < 0 || index >= options.length)
            return
        const chosen = options[index].value
        if (chosen !== setting.value)
            Settings.setValue(setting.key, chosen)
    }
}

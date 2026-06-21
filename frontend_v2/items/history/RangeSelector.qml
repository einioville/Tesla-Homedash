import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import frontend_v2

// Time-range picker: 1h / 1d / 1vk / 1kk presets plus a custom range that reveals
// two date+time pickers, and a Live toggle. Emits rangeChanged(code, startMs, endMs)
// (preset ms bounds are 0, ignored by the backend) and liveToggled(on). Live is
// forced off for the custom range.
RowLayout {
    id: root
    spacing: 8

    // Mirrors protocol HISTORY_RANGE_*: 0=1h, 1=1d, 2=1M, 3=custom, 4=1week.
    property int activeCode: 0
    signal rangeChanged(int code, double startMs, double endMs)

    // Live mode: a rolling, self-updating window. Applies to the presets only —
    // a custom past range can't be "live" — so it is forced off for custom below.
    property bool live: false
    signal liveToggled(bool on)

    onActiveCodeChanged: if (activeCode === 3 && live) {
        live = false
        liveToggled(false)
    }

    function emitRange() {
        if (activeCode === 3) {
            // The pickers carry an exact date+time, so the ms bounds are used
            // verbatim (no whole-day rounding).
            const startMs = startPicker.selected.getTime()
            const endMs = endPicker.selected.getTime()
            if (isNaN(startMs) || isNaN(endMs) || endMs <= startMs) {
                return  // ignore an empty or inverted range
            }
            root.rangeChanged(3, startMs, endMs)
        } else {
            root.rangeChanged(activeCode, 0, 0)
        }
    }

    component RangeButton: Rectangle {
        id: btn
        property string label: ""
        property int code: 0
        implicitWidth: 60
        implicitHeight: 40
        radius: 8
        color: root.activeCode === btn.code ? Theme.accent
                                            : (tap.pressed ? "#3a4150" : "#2a2f3a")

        Text {
            anchors.centerIn: parent
            text: btn.label
            color: "#ffffff"
            font.family: Theme.fontFamily
            font.pixelSize: 16
        }

        MouseArea {
            id: tap
            anchors.fill: parent
            onClicked: {
                root.activeCode = btn.code
                root.emitRange()
            }
        }
    }

    RangeButton { label: "1h";  code: 0 }
    RangeButton { label: "1pv"; code: 1 }
    RangeButton { label: "1vk"; code: 4 }
    RangeButton { label: "1kk"; code: 2 }
    RangeButton { label: "Oma"; code: 3 }

    // Live toggle — turns the selected preset into a rolling window that seeds
    // from history then advances every second from live telemetry. Disabled (and
    // forced off, above) for the custom range. Styled to match RangeButton.
    Rectangle {
        id: liveButton
        implicitWidth: 70
        implicitHeight: 40
        radius: 8
        enabled: root.activeCode !== 3
        opacity: enabled ? 1.0 : 0.4
        color: root.live ? Theme.accent
                         : (liveTap.pressed ? "#3a4150" : "#2a2f3a")

        Text {
            anchors.centerIn: parent
            text: root.live ? "● LIVE" : "LIVE"
            color: "#ffffff"
            font.family: Theme.fontFamily
            font.pixelSize: 16
        }

        MouseArea {
            id: liveTap
            anchors.fill: parent
            onClicked: {
                root.live = !root.live
                root.liveToggled(root.live)
            }
        }
    }

    DateTimePicker {
        id: startPicker
        visible: root.activeCode === 3
        // Default the start to one hour ago so the custom range opens non-empty.
        Component.onCompleted: {
            var d = new Date()
            d.setHours(d.getHours() - 1)
            startPicker.selected = d
        }
        onEdited: root.emitRange()
    }

    DateTimePicker {
        id: endPicker
        visible: root.activeCode === 3
        // Defaults to "now".
        onEdited: root.emitRange()
    }
}

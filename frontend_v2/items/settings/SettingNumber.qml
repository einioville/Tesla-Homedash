import QtQuick
import QtQuick.Controls
import frontend_v2

// Numeric editor: [−] [typed value] [+]. The DEFAULT for int/float settings.
//
// A slider only works when the exact number does not matter — you are feeling for
// a point on a range. Most numeric settings here are the opposite: a port, a
// tariff in €/kWh, a poll interval in seconds are values you know and need to hit
// exactly. Rendering those as sliders made them unusable (backendPort spans 65534
// steps, so one pixel of a 320px track is ~205 ports). So sliders are now opt-in
// via the schema's `editor: "slider"`, and this is what everything else gets.
//
// The field accepts typing for a big jump; the ± buttons (with hold-to-repeat)
// handle nudging without a keyboard, which is what the 10" touch panel needs.
Item {
    id: control

    required property var setting

    readonly property bool isInt: setting.type === "int"
    readonly property real minimum: setting.min !== undefined ? setting.min : -Infinity
    readonly property real maximum: setting.max !== undefined ? setting.max : Infinity
    readonly property real stepSize: setting.step !== undefined ? setting.step : (isInt ? 1 : 0.1)

    // A nullable setting that is null means "not configured" — distinct from its
    // minimum. It shows as an empty field, and clearing the field restores null.
    readonly property bool nullable: setting.nullable === true
    readonly property bool isUnset: nullable && (setting.value === null
                                                 || setting.value === undefined)

    // Decimals to render: derived from the step so 0.001 shows 3 and 0.5 shows 1.
    readonly property int decimals: {
        if (isInt)
            return 0
        const s = String(stepSize)
        const dot = s.indexOf(".")
        return dot < 0 ? 0 : Math.min(6, s.length - dot - 1)
    }

    implicitWidth: 240
    implicitHeight: 38

    function formatted(value) {
        return control.isInt ? String(Math.round(value)) : value.toFixed(control.decimals)
    }

    function currentText() {
        return control.isUnset ? "" : control.formatted(Number(control.setting.value))
    }

    function clamp(value) {
        return Math.min(control.maximum, Math.max(control.minimum, value))
    }

    // Writes `value`, clamped, unless it already matches. Passing null clears a
    // nullable setting.
    function commit(value) {
        if (value === null) {
            if (!control.isUnset)
                Settings.setValue(control.setting.key, null)
            return
        }
        const clamped = control.clamp(value)
        // Round floats to the step's precision so 0.30000000000000004 never
        // reaches the backend and fails an equality check against 0.3.
        const rounded = control.isInt
                        ? Math.round(clamped)
                        : Number(clamped.toFixed(control.decimals))
        // BEFORE the write, not after: Settings.setValue() rebuilds
        // Settings.groups, which destroys and rebuilds this very delegate,
        // so any statement after it evaluates in a dead context and throws.
        field.text = control.formatted(rounded)
        if (rounded !== control.setting.value)
            Settings.setValue(control.setting.key, rounded)
    }

    function nudge(direction) {
        const base = control.isUnset ? (control.setting.min !== undefined ? control.setting.min : 0)
                                     : Number(control.setting.value)
        control.commit(base + direction * control.stepSize)
    }

    // Re-sync from the authoritative value unless the user is mid-edit.
    onSettingChanged: if (!field.activeFocus) field.text = control.currentText()

    Row {
        id: row
        anchors.fill: parent
        spacing: 6

        // --- minus -------------------------------------------------------
        Rectangle {
            id: minusButton
            width: 40
            height: control.height
            radius: 8
            color: minusArea.pressed ? Theme.tripComboPressed : Theme.tripComboBg
            border.width: 1
            border.color: Theme.tripCardBorder
            opacity: enabled ? 1.0 : 0.4
            enabled: control.isUnset || Number(control.setting.value) > control.minimum

            Text {
                anchors.centerIn: parent
                text: "−"
                font.family: Theme.fontFamily
                font.pixelSize: 18
                color: Theme.dataLabelValue
            }

            MouseArea {
                id: minusArea
                anchors.fill: parent
                onClicked: control.nudge(-1)
            }

            // Hold to repeat — without it, moving a 30-minute timeout to 120 is
            // 90 separate taps.
            Timer {
                interval: 120
                repeat: true
                running: minusArea.pressed && minusButton.enabled
                triggeredOnStart: false
                onTriggered: control.nudge(-1)
            }
        }

        // --- value -------------------------------------------------------
        Rectangle {
            // Whatever is left after the two 40px buttons and the two gaps.
            width: control.width - minusButton.width - plusButton.width - 2 * row.spacing
            height: control.height
            radius: 8
            color: field.activeFocus ? Theme.tripComboPressed : Theme.tripComboBg
            border.width: 1
            border.color: field.activeFocus ? Theme.accent : Theme.tripCardBorder

            TextField {
                id: field
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: unitLabel.visible ? unitLabel.width + 14 : 10
                text: control.currentText()
                placeholderText: control.nullable ? "—" : ""
                font.family: Theme.fontFamily
                font.pixelSize: 15
                color: Theme.dataLabelValue
                horizontalAlignment: TextInput.AlignHCenter
                verticalAlignment: TextInput.AlignVCenter
                selectByMouse: true
                // The surrounding Rectangle is the visual field; the Basic style's
                // own background would paint a light box over the dark theme.
                background: null
                // Digits, one separator, optional leading minus. Not a range check —
                // commit() clamps — just a guard against nonsense reaching parseFloat.
                validator: RegularExpressionValidator {
                    regularExpression: control.isInt ? /-?\d*/ : /-?\d*[.,]?\d*/
                }

                onEditingFinished: {
                    const raw = text.trim().replace(",", ".")
                    if (raw.length === 0) {
                        if (control.nullable) {
                            control.commit(null)
                        } else {
                            // Not clearable: put the authoritative value back
                            // rather than writing something arbitrary.
                            text = control.currentText()
                        }
                        return
                    }
                    const parsed = parseFloat(raw)
                    if (isNaN(parsed)) {
                        text = control.currentText()
                        return
                    }
                    control.commit(parsed)
                }
            }

            Text {
                id: unitLabel
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                visible: control.setting.unit !== undefined && !control.isUnset
                text: control.setting.unit !== undefined ? control.setting.unit : ""
                font.family: Theme.fontFamily
                font.pixelSize: 12
                color: Theme.dataLabelTitle
            }
        }

        // --- plus --------------------------------------------------------
        Rectangle {
            id: plusButton
            width: 40
            height: control.height
            radius: 8
            color: plusArea.pressed ? Theme.tripComboPressed : Theme.tripComboBg
            border.width: 1
            border.color: Theme.tripCardBorder
            opacity: enabled ? 1.0 : 0.4
            enabled: control.isUnset || Number(control.setting.value) < control.maximum

            Text {
                anchors.centerIn: parent
                text: "+"
                font.family: Theme.fontFamily
                font.pixelSize: 17
                color: Theme.dataLabelValue
            }

            MouseArea {
                id: plusArea
                anchors.fill: parent
                onClicked: control.nudge(1)
            }

            Timer {
                interval: 120
                repeat: true
                running: plusArea.pressed && plusButton.enabled
                triggeredOnStart: false
                onTriggered: control.nudge(1)
            }
        }
    }
}

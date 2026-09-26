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
//
// A held button steps a PENDING value that only the field shows, and the press
// commits it once, on release. Committing per step cannot work here: every
// Settings.setValue() rebuilds Settings.groups — at once for a local key, on the
// schema broadcast for a backend one — which destroys this delegate and the
// press with it, so a hold stopped after one step. And each step was a disk
// write (a backend CONFIG_SET is a config.json save plus apply hooks).
//
// `editor: "time"` reuses the same stepper for a time of day stored as minutes
// since midnight: the value reads as HH:MM, the ± buttons WRAP past midnight
// (22:00 is eight steps back from 00:00, not eighty-eight forward), and the field
// takes no typing — the number pad has no colon.
Item {
    id: control

    required property var setting

    readonly property bool isInt: setting.type === "int"
    readonly property bool isTime: setting.editor === "time"
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
        if (control.isTime) {
            const minutes = Math.round(value)
            const pad = (n) => (n < 10 ? "0" : "") + n
            return pad(Math.floor(minutes / 60)) + ":" + pad(minutes % 60)
        }
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

    // Steps taken by the press in progress, not yet committed; null when none.
    property var pendingValue: null

    // What the ± buttons step from and test against their limits: the pending
    // value during a press, else the setting's own (NaN while a nullable one is
    // unset, which leaves both buttons usable).
    readonly property real stepFrom: pendingValue !== null
                                     ? pendingValue
                                     : (isUnset ? NaN : Number(setting.value))
    readonly property bool canStepDown: isTime || isNaN(stepFrom) || stepFrom > minimum
    readonly property bool canStepUp: isTime || isNaN(stepFrom) || stepFrom < maximum

    // Steps the pending value and shows it; nothing is written yet.
    function stepPending(direction) {
        const base = !isNaN(control.stepFrom)
                     ? control.stepFrom
                     : (control.setting.min !== undefined ? control.setting.min : 0)
        let next = base + direction * control.stepSize
        if (control.isTime) {
            // Wrap around the day: one step past max lands on min and back.
            const span = control.maximum - control.minimum + control.stepSize
            next = control.minimum + ((next - control.minimum) % span + span) % span
        }
        next = control.clamp(next)
        control.pendingValue = control.isInt ? Math.round(next)
                                             : Number(next.toFixed(control.decimals))
        field.text = control.formatted(control.pendingValue)
    }

    // Commits what the press stepped to, once. Clears the pending value first,
    // because commit() may destroy this delegate.
    function commitPending() {
        if (control.pendingValue === null)
            return
        const value = control.pendingValue
        control.pendingValue = null
        control.commit(value)
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
            // Dimmed rather than disabled: disabling the item mid-hold would
            // cancel the very press that reached the limit.
            opacity: control.canStepDown ? 1.0 : 0.4

            Text {
                anchors.centerIn: parent
                text: "−"
                font.family: Theme.fontFamily
                font.pixelSize: 18
                color: Theme.dataLabelValue
            }

            // Hold to repeat — without it, moving a 30-minute timeout to 120 is
            // 90 separate taps.
            HoldRepeatArea {
                id: minusArea
                anchors.fill: parent
                canStep: control.canStepDown
                onStepped: control.stepPending(-1)
                onFinished: control.commitPending()
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
                selectByMouse: !control.isTime
                // A time is stepped, never typed (see the header).
                readOnly: control.isTime
                activeFocusOnPress: !control.isTime
                // The surrounding Rectangle is the visual field; the Basic style's
                // own background would paint a light box over the dark theme.
                background: null
                // Digits, one separator, optional leading minus. Not a range check —
                // commit() clamps — just a guard against nonsense reaching parseFloat.
                validator: RegularExpressionValidator {
                    regularExpression: control.isInt ? /-?\d*/ : /-?\d*[.,]?\d*/
                }
                // The on-screen keyboard's number pad. The digits-only pad has no
                // minus key, so a setting that may go negative gets the fuller one.
                inputMethodHints: control.isInt && control.minimum >= 0
                                  ? Qt.ImhDigitsOnly : Qt.ImhFormattedNumbersOnly

                // Enter commits (editingFinished follows) and closes the keyboard;
                // see SettingText for why focus stays put.
                onAccepted: Qt.inputMethod.hide()

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
            opacity: control.canStepUp ? 1.0 : 0.4

            Text {
                anchors.centerIn: parent
                text: "+"
                font.family: Theme.fontFamily
                font.pixelSize: 17
                color: Theme.dataLabelValue
            }

            HoldRepeatArea {
                id: plusArea
                anchors.fill: parent
                canStep: control.canStepUp
                onStepped: control.stepPending(1)
                onFinished: control.commitPending()
            }
        }
    }
}

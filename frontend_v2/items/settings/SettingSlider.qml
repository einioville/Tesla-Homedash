import QtQuick
import QtQuick.Controls
import frontend_v2

// Numeric editor (int and float): a slider with a live readout.
//
// One line — track, then the readout at its right — so the control centres on the
// row's label like every other editor. The readout used to sit ABOVE the track,
// which pushed the track below the label's centre line.
//
// The important behaviour here is COMMIT-ON-RELEASE. A slider emits a value on
// every frame of a drag; writing each one would rewrite the settings file dozens
// of times a second and, for a backend setting, fire a CONFIG_SET packet per
// frame (each of which the backend persists to config.json and answers with a
// schema broadcast). So the drag only moves a local display value, and the write
// happens once the finger lifts — or, for keyboard/step changes that never touch
// `pressed`, after a short idle debounce.
Item {
    id: control

    required property var setting

    readonly property bool isInt: setting.type === "int"
    readonly property real minimum: setting.min !== undefined ? setting.min : 0
    readonly property real maximum: setting.max !== undefined ? setting.max : 100
    readonly property real stepSize: setting.step !== undefined ? setting.step : (isInt ? 1 : 0.1)

    // Optional text shown INSTEAD of the number at the slider's top stop, for a
    // maximum that means something other than its numeric value — "rajoittamaton"
    // for the graph point cap, where the top stop disables the cap entirely.
    readonly property string maxLabel: setting.maxLabel !== undefined ? setting.maxLabel : ""
    readonly property bool atMaxLabel: maxLabel.length > 0 && displayValue >= maximum

    // A nullable setting that is currently null means "not configured", which is
    // NOT the same as its minimum — the flat electricity tariff falling back to
    // null makes the Charging view show "—" rather than pricing energy at zero.
    // So an unset value reads as "—" and gets a clear button once it is set,
    // instead of silently looking like a real 0.000.
    readonly property bool nullable: setting.nullable === true
    readonly property bool isUnset: nullable && (setting.value === null
                                                 || setting.value === undefined)

    // Display value: follows the authoritative setting except while the user is
    // actively dragging, when it follows the finger.
    property real displayValue: setting.value !== undefined && setting.value !== null
                                ? setting.value : minimum

    implicitWidth: 240
    implicitHeight: 24

    // Re-sync when the authoritative value changes underneath us (another client
    // wrote it, or our own write came back), but never while dragging.
    onSettingChanged: if (!slider.pressed) displayValue = setting.value !== undefined
                                                          && setting.value !== null
                                                          ? setting.value : minimum

    // The readout text for a value — the number and its unit.
    function format(value) {
        return (control.isInt ? Math.round(value)
                              : value.toFixed(control.stepSize < 0.1 ? 3 : 2))
               + (control.setting.unit !== undefined ? " " + control.setting.unit : "")
    }

    function commit() {
        const value = control.isInt ? Math.round(control.displayValue) : control.displayValue
        if (value !== control.setting.value)
            Settings.setValue(control.setting.key, value)
    }

    // Dim the track while unset, so an untouched nullable setting does not look
    // like a deliberate minimum.
    opacity: control.isUnset ? 0.75 : 1.0

    // Fires only for changes that never involve a press (arrow keys, a11y steps).
    Timer {
        id: debounce
        interval: 400
        onTriggered: control.commit()
    }

    // Sized for the widest text the readout can show, so the track keeps its length
    // while a drag adds a digit ("95 %" -> "100 %") or reaches the max label.
    TextMetrics {
        id: widest
        font: readout.font
        text: [control.format(control.minimum), control.format(control.maximum),
               control.maxLabel, "—"].reduce((a, b) => b.length > a.length ? b : a, "")
    }

    Row {
        id: valueRow
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8

        Text {
            id: readout
            anchors.verticalCenter: parent.verticalCenter
            width: Math.ceil(widest.advanceWidth)
            horizontalAlignment: Text.AlignRight
            text: control.isUnset
                  ? "—"
                  : control.atMaxLabel ? control.maxLabel : control.format(control.displayValue)
            font.family: Theme.fontFamily
            font.pixelSize: 13
            color: control.isUnset ? Theme.dataLabelTitle : Theme.accent
        }

        // Clears a nullable setting back to "not configured". Its space is kept
        // while there is nothing to clear, so clearing does not stretch the track.
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            visible: control.nullable
            opacity: control.isUnset ? 0 : 1
            width: 18
            height: 18
            radius: 9
            color: clearArea.pressed ? Theme.tripComboPressed : Theme.tripComboBg
            border.width: 1
            border.color: Theme.tripCardBorder

            Text {
                anchors.centerIn: parent
                text: "×"
                font.pixelSize: 13
                color: Theme.dataLabelTitle
            }

            MouseArea {
                id: clearArea
                anchors.fill: parent
                enabled: !control.isUnset
                onClicked: Settings.setValue(control.setting.key, null)
            }
        }
    }

    Slider {
        id: slider
        anchors.left: parent.left
        anchors.right: valueRow.left
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        height: 24

        from: control.minimum
        to: control.maximum
        stepSize: control.stepSize
        value: control.displayValue
        live: true

        onMoved: {
            control.displayValue = value
            // A drag commits on release; a click straight onto the groove also
            // lands here with pressed still true, so the release handles both.
            if (!pressed)
                debounce.restart()
        }

        onPressedChanged: {
            if (!pressed) {
                debounce.stop()
                control.commit()
            }
        }

        background: Rectangle {
            x: slider.leftPadding
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            width: slider.availableWidth
            height: 5
            radius: 3
            color: Theme.sliderGroove

            Rectangle {
                width: slider.visualPosition * parent.width
                height: parent.height
                radius: 3
                color: Theme.accent
            }
        }

        handle: Rectangle {
            x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            // Generous for a fingertip on the 10" panel.
            width: 22
            height: 22
            radius: height / 2
            color: slider.pressed ? Theme.accent : Theme.dataLabelValue
            border.width: 1
            border.color: Theme.tripCardBorder
        }
    }
}

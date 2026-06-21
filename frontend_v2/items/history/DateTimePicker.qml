import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import frontend_v2

// Touch-friendly date + time picker. A field shows the current value and opens a
// popup with a month calendar (MonthGrid) plus hour/minute spin boxes. Exposes
// `selected` (a JS Date) and emits edited() when the user confirms with OK.
Item {
    id: root

    property date selected: new Date()
    signal edited()

    implicitWidth: 170
    implicitHeight: 40

    Rectangle {
        id: field
        anchors.fill: parent
        radius: 8
        color: fieldTap.pressed ? "#3a4150" : "#2a2f3a"

        Text {
            anchors.centerIn: parent
            text: Qt.formatDateTime(root.selected, "dd.MM.yyyy HH:mm")
            color: "#ffffff"
            font.family: Theme.fontFamily
            font.pixelSize: 15
        }

        TapHandler {
            id: fieldTap
            onTapped: {
                // Seed the popup's working state from the current selection.
                popup.viewYear = root.selected.getFullYear()
                popup.viewMonth = root.selected.getMonth()
                popup.pickDate = root.selected
                hourBox.value = root.selected.getHours()
                minuteBox.value = root.selected.getMinutes()
                popup.open()
            }
        }
    }

    Popup {
        id: popup
        y: field.height + 6
        width: 300
        padding: 12
        modal: true
        dim: true

        property int viewYear: root.selected.getFullYear()
        property int viewMonth: root.selected.getMonth()   // 0-based, like JS Date
        property date pickDate: root.selected

        background: Rectangle {
            color: "#1b2230"
            radius: 12
            border.color: Theme.dockBorder
            border.width: 1
        }

        function shiftMonth(delta) {
            var m = popup.viewMonth + delta
            var y = popup.viewYear
            while (m < 0) { m += 12; y -= 1 }
            while (m > 11) { m -= 12; y += 1 }
            popup.viewMonth = m
            popup.viewYear = y
        }

        function sameDay(a, b) {
            return a.getFullYear() === b.getFullYear()
                && a.getMonth() === b.getMonth()
                && a.getDate() === b.getDate()
        }

        contentItem: ColumnLayout {
            spacing: 10

            // Month navigation header.
            RowLayout {
                Layout.fillWidth: true

                Rectangle {
                    implicitWidth: 36; implicitHeight: 36; radius: 8
                    color: prevTap.pressed ? "#3a4150" : "#2a2f3a"
                    Text { anchors.centerIn: parent; text: "‹"; color: "#ffffff"; font.pixelSize: 20 }
                    TapHandler { id: prevTap; onTapped: popup.shiftMonth(-1) }
                }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: grid.title
                    color: "#ffffff"
                    font.family: Theme.fontFamily
                    font.pixelSize: 16
                }
                Rectangle {
                    implicitWidth: 36; implicitHeight: 36; radius: 8
                    color: nextTap.pressed ? "#3a4150" : "#2a2f3a"
                    Text { anchors.centerIn: parent; text: "›"; color: "#ffffff"; font.pixelSize: 20 }
                    TapHandler { id: nextTap; onTapped: popup.shiftMonth(1) }
                }
            }

            // Weekday header. Hard-coded Monday-first to match the fi_FI locale
            // forced on the grid below, so the columns line up.
            RowLayout {
                Layout.fillWidth: true
                Repeater {
                    model: ["Ma", "Ti", "Ke", "To", "Pe", "La", "Su"]
                    Text {
                        required property string modelData
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        text: modelData
                        color: "#9aa3b2"
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                }
            }

            MonthGrid {
                id: grid
                Layout.fillWidth: true
                locale: Qt.locale("fi_FI")  // Monday-first, Finnish month titles
                month: popup.viewMonth
                year: popup.viewYear
                onClicked: function(date) { popup.pickDate = date }

                delegate: Item {
                    required property var model
                    implicitWidth: 36
                    implicitHeight: 34

                    Rectangle {
                        anchors.centerIn: parent
                        width: 30; height: 30; radius: 15
                        visible: popup.sameDay(model.date, popup.pickDate)
                        color: Theme.accent
                    }
                    Text {
                        anchors.centerIn: parent
                        text: model.day
                        color: popup.sameDay(model.date, popup.pickDate) ? "#0b0d12" : "#ffffff"
                        // Dim days spilling in from the adjacent months.
                        opacity: model.month === grid.month ? 1.0 : 0.35
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                    }
                }
            }

            // Time row.
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: qsTr("Aika")
                    color: "#9aa3b2"
                    font.family: Theme.fontFamily
                    font.pixelSize: 14
                }
                Item { Layout.fillWidth: true }
                SpinBox {
                    id: hourBox
                    from: 0; to: 23; wrap: true
                    value: root.selected.getHours()
                    textFromValue: function(value) { return ("0" + value).slice(-2) }
                }
                Text { text: ":"; color: "#ffffff"; font.pixelSize: 18 }
                SpinBox {
                    id: minuteBox
                    from: 0; to: 59; wrap: true
                    value: root.selected.getMinutes()
                    textFromValue: function(value) { return ("0" + value).slice(-2) }
                }
            }

            TextButton {
                Layout.fillWidth: true
                label: qsTr("OK")
                onClicked: {
                    var d = new Date(popup.pickDate)
                    d.setHours(hourBox.value, minuteBox.value, 0, 0)
                    root.selected = d
                    root.edited()
                    popup.close()
                }
            }
        }
    }
}

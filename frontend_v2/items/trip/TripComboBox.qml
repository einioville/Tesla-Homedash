import QtQuick
import QtQuick.Controls
import frontend_v2

// Dark-themed ComboBox shared by the week + trip selectors. The Qt Basic style's
// default popup and item-delegate backgrounds are light, so hovering an entry paints
// a white square over the map — this restyles the field, popup and delegate to the
// dark theme and gives the hover highlight a muted colour instead of white.
//
// Subclasses set `model`/`textRole` as usual and may override `formatEntry` to build
// a rich per-row label (TripSelector does, for the weekday/time/distance line).
ComboBox {
    id: control

    // Per-row text formatter used by the delegate. Default reads textRole; override
    // for a computed label.
    property var formatEntry: function(entry) {
        if (entry === undefined || entry === null)
            return ""
        if (control.textRole && entry[control.textRole] !== undefined)
            return entry[control.textRole]
        return "" + entry
    }

    font.family: Theme.fontFamily
    font.pixelSize: 16
    // Tall enough for two lines: the trip/week labels are long and were being cut off,
    // so both the field and the popup rows wrap onto a second line.
    implicitHeight: 52

    background: Rectangle {
        radius: 8
        color: control.pressed ? Theme.tripComboPressed : Theme.tripComboBg
        border.width: 1
        border.color: Theme.tripControlBarBorder
    }

    contentItem: Text {
        leftPadding: 12
        rightPadding: control.indicator ? control.indicator.width + 12 : 12
        text: control.displayText
        font: control.font
        color: Theme.dataLabelValue
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
        maximumLineCount: 2
        elide: Text.ElideRight
    }

    delegate: ItemDelegate {
        id: entryDelegate
        width: ListView.view ? ListView.view.width : control.width
        height: 52
        required property int index
        required property var modelData
        // Hover / keyboard highlight (NOT the white default) — this is the fix.
        highlighted: control.highlightedIndex === index
        background: Rectangle {
            radius: 6
            color: entryDelegate.highlighted ? Theme.tripComboHover : "transparent"
        }
        contentItem: Text {
            leftPadding: 8
            rightPadding: 8
            text: control.formatEntry(entryDelegate.modelData)
            font: control.font
            color: Theme.dataLabelValue
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
    }

    popup: Popup {
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(listView.contentHeight + 8, 360)
        padding: 4

        background: Rectangle {
            radius: 8
            color: Theme.tripComboPopupBg
            border.width: 1
            border.color: Theme.tripControlBarBorder
        }

        contentItem: ListView {
            id: listView
            clip: true
            implicitHeight: contentHeight
            model: control.delegateModel
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
    }
}

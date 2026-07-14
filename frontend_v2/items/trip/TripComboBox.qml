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
        // The control's Basic-style rightPadding already reserves the indicator's width
        // (the template places the contentItem inside it), so pad only the 12px gap —
        // adding indicator.width here too double-counted it and cut the collapsed
        // label off ~30px early.
        rightPadding: 12
        text: control.displayText
        font: control.font
        color: Theme.dataLabelValue
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
        elide: Text.ElideRight
        // Shrink-before-elide, constrained by the item HEIGHT (52px ≈ two lines), not
        // maximumLineCount: the Text.Fit search only shrinks on physical overflow — a
        // maximumLineCount truncation elides at full size without ever trying a smaller
        // font (qquicktext.cpp fit loop) — so the label shrinks (≥12px) until it all
        // fits and elides only below the minimum.
        fontSizeMode: Text.Fit
        minimumPixelSize: 12
    }

    delegate: ItemDelegate {
        id: entryDelegate
        width: ListView.view ? ListView.view.width : control.width
        height: 52
        // The Basic style's default padding (12) left the row text only 28px of height —
        // one line — so elide+wrap cut the label instead of wrapping it (issue #19). Zero
        // padding hands the Text the full 52px, enough for two lines.
        padding: 0
        required property int index
        required property var modelData
        // Hover / keyboard highlight (NOT the white default) — this is the fix.
        highlighted: control.highlightedIndex === index
        background: Rectangle {
            radius: 6
            color: entryDelegate.highlighted ? Theme.tripComboHover : "transparent"
        }
        contentItem: Text {
            leftPadding: 12
            rightPadding: 12
            text: control.formatEntry(entryDelegate.modelData)
            font: control.font
            color: Theme.dataLabelValue
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.WordWrap
            // Height-constrained like the field text (no maximumLineCount) so Text.Fit
            // can actually shrink instead of eliding — see the contentItem note above.
            elide: Text.ElideRight
            fontSizeMode: Text.Fit
            minimumPixelSize: 12
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

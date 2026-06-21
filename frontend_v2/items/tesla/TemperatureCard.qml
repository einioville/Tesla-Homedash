import QtQuick
import frontend_v2

// Title above a "value unit" readout (e.g. "Sisä" / "22.5 °C"), centred and
// transparent — the QML port of TemperatureCard.
//
// The value field reserves a FIXED width (sized to the widest temperature it can
// show, measured via TextMetrics) so flipping between e.g. "21 °C" and "21.5 °C"
// — or a minus sign appearing — never changes the card's width and reflows the
// surrounding climate controls (the ± arrows, seat heaters and starter button).
Column {
    id: card

    property string title: ""
    property real value: 0
    property string unit: ""

    spacing: 0

    // Round to one decimal so a raw double never stringifies to IEEE-754 noise
    // like "20.700000000000003" (which the old C++ QString::number suppressed) —
    // that would overflow the fixed-width field below. Whole degrees drop the
    // trailing ".0", matching the old readout (e.g. "21 °C", "21.5 °C").
    function display(v) {
        var r = Math.round(v * 10) / 10
        return Number.isInteger(r) ? r.toFixed(0) : r.toFixed(1)
    }

    TextMetrics {
        id: valueMetrics
        font: valueText.font
        // Widest case the readout can reach: minus sign, two integer digits, a
        // decimal and the unit. '8' is used as the widest glyph.
        text: "-88.8 " + card.unit
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: card.title
        color: Theme.dataLabelValue
        font.family: Theme.fontFamily
        font.pointSize: 12
        horizontalAlignment: Text.AlignHCenter
    }

    Text {
        id: valueText
        anchors.horizontalCenter: parent.horizontalCenter
        width: valueMetrics.width
        text: card.display(card.value) + " " + card.unit
        color: Theme.dataLabelValue
        font.family: Theme.fontFamily
        font.pointSize: 12
        horizontalAlignment: Text.AlignHCenter
    }
}

import QtQuick
import QtQuick.Layouts
import frontend_v2

// One forecast hour — the QML port of WeatherForecastCard. Translucent panel
// with the hour on top, then temperature / wind / precipitation / cloud cover
// rows separated by thin white rules, each with a white-tinted glyph.
Rectangle {
    id: cardRoot

    property int hour: 0
    property int temperature: 0
    property int windSpeed: 0
    property int precipitation: 0
    property int cloudCover: 0

    color: Theme.weatherCardBg
    radius: 2
    border.width: 1
    border.color: Theme.weatherCardBorder

    component MetricRow: RowLayout {
        id: mrow
        property url icon
        property string value
        property string unit
        spacing: 4
        TintedIcon { iconSize: 20; source: mrow.icon; tint: Theme.iconTint }
        Text {
            text: mrow.value
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pointSize: 17
        }
        Text {
            text: mrow.unit
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pointSize: 12
        }
    }

    component Rule: Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 2
        radius: 2
        color: Theme.separator
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 2

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: cardRoot.hour < 10 ? "0" + cardRoot.hour : "" + cardRoot.hour
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pointSize: 17
        }
        MetricRow {
            Layout.alignment: Qt.AlignHCenter
            icon: "qrc:/resources/icons/weather/thermometer.svg"
            value: cardRoot.temperature + ""
            unit: "°C"
        }
        Rule {}
        MetricRow {
            Layout.alignment: Qt.AlignHCenter
            icon: "qrc:/resources/icons/weather/wind.svg"
            value: cardRoot.windSpeed + ""
            unit: "m/s"
        }
        Rule {}
        MetricRow {
            Layout.alignment: Qt.AlignHCenter
            icon: "qrc:/resources/icons/weather/rain.svg"
            value: cardRoot.precipitation + ""
            unit: "mm"
        }
        Rule {}
        MetricRow {
            Layout.alignment: Qt.AlignHCenter
            icon: "qrc:/resources/icons/weather/clouds.svg"
            value: cardRoot.cloudCover + ""
            unit: "%"
        }
    }
}

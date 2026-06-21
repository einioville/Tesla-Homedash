import QtQuick
import QtQuick.Layouts
import frontend_v2

// Current-hour banner — the QML port of CurrentWeatherCard. A horizontal strip:
// big temperature on the left, then wind / precipitation / cloud cover pushed
// to the right and separated by vertical white rules. Binds Weather.current.
Rectangle {
    id: banner

    color: Theme.weatherCardBg
    radius: 2
    border.width: 1
    border.color: Theme.weatherCardBorder

    function field(name) {
        return (Weather.hasData && Weather.current[name] !== undefined)
               ? Weather.current[name] + "" : "-"
    }

    component Metric: RowLayout {
        id: m
        property url icon
        property string value
        property string unit
        spacing: 4
        TintedIcon { iconSize: 20; source: m.icon; tint: Theme.iconTint }
        Text {
            text: m.value
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pointSize: 20
        }
        Text {
            text: m.unit
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pointSize: 15
        }
    }

    component VRule: Rectangle {
        Layout.preferredWidth: 4
        Layout.fillHeight: true
        Layout.topMargin: 4
        Layout.bottomMargin: 4
        radius: 2
        color: Theme.separator
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 10
        // Even gaps between the temperature block, the stretch and each
        // metric/divider on the right so the dividers aren't flush against text.
        spacing: 14

        // Temperature (large). The thermometer glyph is sized to the value's
        // text height so it stands as tall as the number beside it.
        RowLayout {
            spacing: 4
            TintedIcon {
                iconSize: Math.round(tempValue.implicitHeight)
                source: "qrc:/resources/icons/weather/thermometer.svg"
                tint: Theme.iconTint
            }
            Text {
                id: tempValue
                text: banner.field("temperature")
                color: Theme.dataLabelValue
                font.family: Theme.fontFamily
                font.pointSize: 32
            }
            Text {
                text: "°C"
                color: Theme.dataLabelValue
                font.family: Theme.fontFamily
                font.pointSize: 20
            }
        }

        Item { Layout.fillWidth: true }

        Metric { icon: "qrc:/resources/icons/weather/wind.svg"; value: banner.field("windSpeed"); unit: "m/s" }
        VRule {}
        Metric { icon: "qrc:/resources/icons/weather/rain.svg"; value: banner.field("precipitation"); unit: "mm" }
        VRule {}
        Metric { icon: "qrc:/resources/icons/weather/clouds.svg"; value: banner.field("cloudCover"); unit: "%" }
    }
}

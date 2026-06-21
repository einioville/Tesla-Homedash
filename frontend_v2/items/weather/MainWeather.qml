import QtQuick
import QtQuick.Layouts
import frontend_v2

// Weather panel — the QML port of MainWeather. A top-right-anchored gradient
// card with the current-hour banner across the top and a row of five forecast
// cards below, driven by the Weather singleton (current map + forecast model).
GradientCard {
    id: weather

    gradientCx: 1.0
    gradientCy: 0.0

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 10

        CurrentWeatherCard {
            Layout.fillWidth: true
            Layout.preferredHeight: 80
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10

            Repeater {
                model: Weather.forecast

                // Show at most the next five hours. A hidden Layout child takes
                // no space, so any extra rows a backend might still send are
                // dropped rather than squeezing the five we want.
                delegate: WeatherForecastCard {
                    visible: index < 5
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    hour: model.hour
                    temperature: model.temperature
                    windSpeed: model.windSpeed
                    precipitation: model.precipitation
                    cloudCover: model.cloudCover
                }
            }
        }
    }
}

import QtQuick
import frontend_v2

// Weather panel — the Weather view's hourly chart card: twelve hours across, every one
// labelled, scrollable through the whole forecast, over the same live data.
WeatherProtoHourlyCard {
    hours: Weather.view.hourly || []
    hoursVisible: 12
    labelEvery: 1
}

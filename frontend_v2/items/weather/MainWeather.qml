import QtQuick
import frontend_v2

// Weather panel — the Weather view's hourly chart card: twelve hours across, every one
// labelled, scrollable through the whole forecast, over the same live data. Here alone
// the hours a warning is in force in carry a badge; the Weather view has no room for them.
WeatherHourlyCard {
    hours: Weather.view.hourly || []
    hoursVisible: 12
    labelEvery: 1
    warningBadges: true
}

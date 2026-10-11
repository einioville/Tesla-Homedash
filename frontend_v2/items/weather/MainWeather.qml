import QtQuick
import frontend_v2
import "prototype/WeatherProtoSnapshot.js" as Snap

// Weather panel — the Weather view's hourly chart card: twelve hours across, every one
// labelled, scrollable through the whole forecast, over the same data (PROTOTYPE: the FMI
// snapshot from prototype/fetch_snapshot.py).
WeatherProtoHourlyCard {
    hours: Snap.data.hourly || []
    hoursVisible: 12
    labelEvery: 1
}

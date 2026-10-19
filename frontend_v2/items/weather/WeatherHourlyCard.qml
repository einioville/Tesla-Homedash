import QtQuick
import frontend_v2

// The hourly chart in its card: `hoursVisible` hours across, scrollable through
// all of `hours`. The title names the hours on screen ("SEURAAVAT 24 TUNTIA" at the start,
// their span once scrolled) unless `heading` overrides it, and "↺ Nyt" glides back to now.
// Used by the Weather view and the dashboard's weather panel, which marks the hours
// warnings are in force in (`warningBadges`).
Card {
    id: card

    property var hours: []
    property int hoursVisible: 24
    property int labelEvery: 2
    // Replaces the title while set (the Weather view's selected day).
    property string heading: ""
    property bool warningBadges: false

    // "↺ Nyt" was tapped; the chart is already gliding back.
    signal backToNow
    // The user dragged or flicked the chart.
    signal userScrolled
    // A warning badge was tapped.
    signal warningsRequested

    function scrollToHour(index) {
        chart.scrollToHour(index)
    }

    title: {
        if (heading !== "")
            return heading
        if (chart.atStart || !hours.length)
            return qsTr("SEURAAVAT %1 TUNTIA").arg(hoursVisible)
        var a = hours[chart.firstVisible]
        var b = hours[Math.min(hours.length - 1, chart.firstVisible + hoursVisible - 1)]
        return (a.wd + " " + a.date + " klo " + a.hour + " – " + b.wd + " " + b.date + " klo " + b.hour).toUpperCase()
    }
    // Snow among the hours on screen at the start, where the note shows: its amounts are cm.
    readonly property bool snowAhead: hours.slice(0, hoursVisible).some(h => h.precipForm === "snow" && h.precip > 0)
    note: chart.atStart ? (snowAhead ? qsTr("lämpötila · sade mm/h · lumi cm/h") : qsTr("lämpötila · sade (mm/h)")) : ""

    Rectangle {
        visible: !chart.atStart
        z: 3
        anchors.right: parent.right
        anchors.rightMargin: 10
        y: 5
        width: backRow.implicitWidth + 24; height: 24; radius: 12
        color: "#26ffffff"
        Row {
            id: backRow
            anchors.centerIn: parent
            spacing: 4
            TintedIcon {
                anchors.verticalCenter: parent.verticalCenter
                iconSize: 13
                source: "qrc:/resources/icons/rotate_left.svg"
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("Nyt")
                color: "white"
                font.family: Theme.fontFamily
                font.pixelSize: 12
            }
        }
        MouseArea {
            anchors.fill: parent
            onClicked: {
                card.backToNow()
                chart.scrollToHour(0)
            }
        }
    }

    WeatherChart {
        id: chart
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        anchors.topMargin: 30
        anchors.bottomMargin: 6
        hours: card.hours
        hoursVisible: card.hoursVisible
        labelEvery: card.labelEvery
        warningBadges: card.warningBadges
        onUserScrolled: card.userScrolled()
        onWarningTapped: card.warningsRequested()
    }
}

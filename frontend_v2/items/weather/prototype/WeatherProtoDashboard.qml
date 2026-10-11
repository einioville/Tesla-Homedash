import QtQuick
import QtQuick.Layouts
import frontend_v2
import "WeatherProtoUtil.js" as U

// PROTOTYPE — variant A, "Kojelauta": everything at once in the app's card grid.
//   row 1: now (merged station observations), sun and moon under it | the radar loop, big
//   row 2: the hourly chart, 24 h wide and scrollable through the whole forecast | the
//          coming days, three at a time and scrollable; a tapped day scrolls the chart
//
// The grid fills the view in the proportions it was designed in at 1280×800 — columns
// 420 : 830 (row 2: 840 : 410), rows 550 : 220, the now card 340 of row 1 — with the
// dashboard's fixed margin and gaps, so the cards grow with the window and lay their
// contents out in whatever size they get.
Item {
    id: root

    readonly property real gap: 10
    readonly property real margin: Theme.gridMargin
    readonly property real innerW: width - 2 * margin - gap
    readonly property real innerH: height - 2 * margin - gap
    readonly property real leftW: innerW * 420 / 1250
    readonly property real topH: innerH * 550 / 770

    property var wx: ({})
    property bool active: true
    property bool demoLightning: false
    // A SmartSymbol to colour the backdrop by instead of the current one; 100 and up is night.
    property int demoSymbol: 0

    readonly property var now: wx.now || ({})
    readonly property var here: (wx.warnings || []).filter(w => w.appliesHere)

    property date clock: new Date()
    Timer {
        interval: 60000
        running: root.active
        repeat: true
        triggeredOnStart: true
        onTriggered: root.clock = new Date()
    }

    // The backdrop takes on the current weather: its kind from the symbol, its light from where
    // the sun is now, so dusk and dawn blend over the hour around sunset and sunrise.
    readonly property int skySymbol: demoSymbol > 0 ? demoSymbol : (now.symbol || 0)
    readonly property real dayness: demoSymbol > 0 ? (demoSymbol >= 100 ? 0 : 1) : U.dayness(clock, wx.astro)
    readonly property var sky: U.skyColors(skySymbol, dayness)

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop {
                position: 0.0
                color: root.sky[0]
                Behavior on color { ColorAnimation { duration: 2000 } }
            }
            GradientStop {
                position: 1.0
                color: root.sky[1]
                Behavior on color { ColorAnimation { duration: 2000 } }
            }
        }
    }

    component Card: WeatherProtoCard {}

    component Metric: Column {
        property string label
        property string value
        property string sub
        property real arrow: -1
        spacing: 2
        Text { text: parent.label; color: "#8f9aa6"; font.family: Theme.fontFamily; font.pixelSize: 12 }
        Row {
            spacing: 6
            WeatherProtoWindArrow {
                visible: parent.parent.arrow >= 0
                direction: parent.parent.arrow
                size: 15
                anchors.verticalCenter: parent.verticalCenter
            }
            Text { text: parent.parent.value; color: "white"; font.family: Theme.fontFamily; font.pixelSize: 19 }
        }
        Text { text: parent.sub; color: "#6f7a86"; font.family: Theme.fontFamily; font.pixelSize: 11; visible: text !== "" }
    }

    // ---- row 1 ---------------------------------------------------------------------------
    Card {
        id: nowCard
        x: root.margin; y: root.margin
        width: root.leftW; height: (root.topH - root.gap) * 340 / 540
        title: "NYT · " + (root.wx.meta.place || "").toUpperCase()
        note: root.now.time ? qsTr("havainto ") + root.now.time : ""

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            anchors.topMargin: 36
            spacing: 8

            Rectangle {
                visible: root.here.length > 0
                Layout.fillWidth: true
                Layout.preferredHeight: 30
                radius: 8
                color: root.here.length ? U.warnColor(root.here[0].color) : "transparent"
                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    text: root.here.length ? "⚠  " + root.here[0].headline : ""
                    color: "#1a1400"
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Image {
                    Layout.preferredWidth: 108
                    Layout.preferredHeight: 108
                    sourceSize: Qt.size(216, 216)
                    source: U.icon(root.now.symbol)
                }
                Column {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        text: U.temp(root.now.temp)
                        color: "white"
                        font.family: Theme.fontFamily
                        font.pixelSize: 72
                    }
                    Text {
                        text: U.capitalize(root.now.text)
                        color: "white"
                        font.family: Theme.fontFamily
                        font.pixelSize: 18
                    }
                    Text {
                        text: qsTr("Tuntuu kuin ") + U.temp(root.now.feels)
                        color: "#8f9aa6"
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                    }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 3
                rowSpacing: 8
                columnSpacing: 10
                Metric {
                    Layout.fillWidth: true
                    label: qsTr("Tuuli")
                    arrow: root.now.windDir ?? -1
                    value: Math.round(root.now.wind) + " m/s"
                    sub: qsTr("puuskat ") + Math.round(root.now.gust)
                }
                Metric {
                    Layout.fillWidth: true
                    label: qsTr("Sade")
                    value: U.num(root.now.precipRate) + " mm/h"
                    sub: root.now.wawaText || ""
                }
                Metric {
                    Layout.fillWidth: true
                    label: qsTr("Kosteus")
                    value: Math.round(root.now.humidity) + " %"
                    sub: qsTr("kastepiste ") + U.temp(root.now.dewPoint)
                }
                Metric {
                    Layout.fillWidth: true
                    label: qsTr("Paine")
                    value: Math.round(root.now.pressure) + " hPa"
                }
                Metric {
                    Layout.fillWidth: true
                    label: qsTr("Näkyvyys")
                    value: U.visibility(root.now.visibility)
                    sub: U.cloudText(root.now.cloudOktas)
                }
                Metric {
                    Layout.fillWidth: true
                    label: qsTr("Lumi")
                    value: root.now.snowDepth === null || root.now.snowDepth < 0
                           ? qsTr("Ei lunta") : Math.round(root.now.snowDepth) + " cm"
                }
            }

            Item { Layout.fillHeight: true }
        }
    }

    // Sun and moon, side by side under the current weather.
    Card {
        id: sunCard
        x: root.margin; y: nowCard.y + nowCard.height + root.gap
        width: (nowCard.width - root.gap) / 2; height: radarCard.height - nowCard.height - root.gap
        title: qsTr("AURINKO")
        WeatherProtoSunArc {
            anchors.fill: parent
            anchors.margins: 14
            anchors.topMargin: 40
            astro: root.wx.astro
            now: root.clock
        }
    }

    Card {
        id: moonCard
        x: sunCard.x + sunCard.width + root.gap; y: sunCard.y
        width: sunCard.width; height: sunCard.height
        title: qsTr("KUU")
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 40
            spacing: 4
            WeatherProtoMoon {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 72; height: 72
                illuminated: root.wx.astro.moonPhase
                waxing: root.wx.astro.moonWaxing
            }
            Item { width: 1; height: 4 }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.wx.astro.moonPhase < 3 ? qsTr("Uusikuu")
                    : root.wx.astro.moonPhase > 97 ? qsTr("Täysikuu")
                    : root.wx.astro.moonWaxing ? qsTr("Kasvava kuu") : qsTr("Vähenevä kuu")
                color: "white"; font.family: Theme.fontFamily; font.pixelSize: 16
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Math.round(root.wx.astro.moonPhase) + qsTr(" % valaistu")
                color: "#8f9aa6"; font.family: Theme.fontFamily; font.pixelSize: 12
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "↑ " + root.wx.astro.moonrise + "   ↓ " + root.wx.astro.moonset
                color: "#8f9aa6"; font.family: Theme.fontFamily; font.pixelSize: 12
            }
        }
    }

    Card {
        id: radarCard
        x: nowCard.x + nowCard.width + root.gap; y: root.margin
        width: root.width - root.margin - x; height: root.topH
        clip: true
        color: "black"

        WeatherProtoRadarMap {
            id: radar
            anchors.fill: parent
            anchors.margins: 1
            latitude: root.wx.meta.lat
            longitude: root.wx.meta.lon
            zoom: 8.0
            placeOffset: Qt.point(0, -20)
            active: root.active
            demoLightning: root.demoLightning
        }
        Text {
            x: 14; y: 10
            text: qsTr("SADETUTKA")
            color: "white"
            font.family: Theme.fontFamily
            font.pixelSize: 12
            font.letterSpacing: 1.2
            style: Text.Outline
            styleColor: "#80000000"
        }
        WeatherProtoRadarControls {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 12
            radar: radar
        }
    }

    // ---- row 2 ---------------------------------------------------------------------------
    // The chart and the days work together: tapping a day scrolls the chart to that day,
    // tapping it again returns the chart to now, and dragging the chart lets go of the day.
    property string selectedDay: ""

    function toggleDay(day) {
        if (selectedDay === day) {
            selectedDay = ""
            chart.scrollToHour(0)
            return
        }
        selectedDay = day
        var hs = wx.hourly || []
        for (var i = 0; i < hs.length; i++) {
            if (hs[i].day === day) {
                chart.scrollToHour(i)
                return
            }
        }
    }

    Card {
        id: chartCard
        x: root.margin; y: radarCard.y + radarCard.height + root.gap
        width: root.innerW * 840 / 1250; height: root.height - root.margin - y
        title: {
            var hs = root.wx.hourly || []
            if (root.selectedDay !== "") {
                var d = (root.wx.daily || []).find(x => x.day === root.selectedDay)
                return d ? (U.WEEKDAYS_LONG[d.wd] + " " + d.date).toUpperCase() : ""
            }
            if (chart.atStart || !hs.length)
                return qsTr("SEURAAVAT 24 TUNTIA")
            var a = hs[chart.firstVisible]
            var b = hs[Math.min(hs.length - 1, chart.firstVisible + chart.hoursVisible - 1)]
            return (a.wd + " " + a.date + " klo " + a.hour + " – " + b.wd + " " + b.date + " klo " + b.hour).toUpperCase()
        }
        note: chart.atStart ? qsTr("lämpötila · sade (mm/h)") : ""

        Rectangle {
            visible: !chart.atStart
            z: 3
            anchors.right: parent.right
            anchors.rightMargin: 10
            y: 5
            width: backText.implicitWidth + 24; height: 24; radius: 12
            color: "#26ffffff"
            Text {
                id: backText
                anchors.centerIn: parent
                text: qsTr("↺ Nyt")
                color: "white"
                font.family: Theme.fontFamily
                font.pixelSize: 12
            }
            MouseArea {
                anchors.fill: parent
                onClicked: {
                    root.selectedDay = ""
                    chart.scrollToHour(0)
                }
            }
        }

        WeatherProtoChart {
            id: chart
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            anchors.topMargin: 30
            anchors.bottomMargin: 6
            hours: root.wx.hourly || []
            labelEvery: 2
            onUserScrolled: root.selectedDay = ""
        }
    }

    Card {
        id: daysCard
        x: chartCard.x + chartCard.width + root.gap; y: chartCard.y
        width: root.width - root.margin - x; height: chartCard.height
        title: qsTr("SEURAAVAT PÄIVÄT")

        // From tomorrow (the chart's first 24 hours cover today) to the last day the
        // forecast covers almost in full; three at a time.
        readonly property var days: (root.wx.daily || []).slice(1).filter(d => d.hours >= 20)
        readonly property int perPage: 3
        // One scale for every day, so bars compare across the whole list.
        readonly property real lo: days.length ? Math.min.apply(null, days.map(d => d.min)) : 0
        readonly property real hi: days.length ? Math.max.apply(null, days.map(d => d.max)) : 1

        // Where the three shown days sit in the list.
        Row {
            anchors.right: parent.right
            anchors.rightMargin: 14
            y: 15
            spacing: 4
            Repeater {
                model: daysCard.days.length
                Rectangle {
                    required property int index
                    readonly property bool shown: index >= dayList.first && index < dayList.first + daysCard.perPage
                    width: shown ? 10 : 5; height: 5; radius: 2.5
                    color: shown ? "#d0ffffff" : "#40ffffff"
                    Behavior on width { NumberAnimation { duration: 150 } }
                }
            }
        }

        ListView {
            id: dayList
            anchors.fill: parent
            anchors.margins: 10
            anchors.topMargin: 34
            orientation: ListView.Horizontal
            model: daysCard.days
            clip: true
            snapMode: ListView.SnapToItem
            boundsBehavior: Flickable.StopAtBounds

            readonly property real itemW: width / daysCard.perPage
            readonly property int first: Math.round(contentX / itemW)

            delegate: Item {
                id: dayCol
                required property int index
                required property var modelData
                readonly property bool selected: root.selectedDay === modelData.day
                width: dayList.itemW
                height: dayList.height

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 2
                    radius: 10
                    color: dayCol.selected ? "#24ffffff" : "transparent"
                    border.color: dayCol.selected ? "#70ffffff" : "transparent"
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                // Divider on the left, except on whichever day sits at the list's left edge,
                // where it would read as a stray line once the list has scrolled.
                Rectangle {
                    visible: dayCol.x - dayList.contentX > 0.5
                    width: 1
                    height: parent.height - 10
                    y: 5
                    color: "#14ffffff"
                }

                Column {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 6
                    spacing: 2

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: dayCol.index === 0 ? qsTr("Huomenna") : U.capitalize(U.WEEKDAYS_LONG[dayCol.modelData.wd])
                        color: "white"; font.family: Theme.fontFamily; font.pixelSize: 15
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: dayCol.modelData.date
                        color: "#6f7a86"; font.family: Theme.fontFamily; font.pixelSize: 11
                    }
                    Image {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 48; height: 48
                        sourceSize: Qt.size(96, 96)
                        source: U.icon(dayCol.modelData.symbol)
                    }
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 8
                        Text {
                            id: maxText
                            text: U.temp(dayCol.modelData.max)
                            color: "white"; font.family: Theme.fontFamily; font.pixelSize: 19
                        }
                        Text {
                            anchors.baseline: maxText.baseline
                            text: U.temp(dayCol.modelData.min)
                            color: "#8f9aa6"; font.family: Theme.fontFamily; font.pixelSize: 15
                        }
                    }
                    // The day's range against the whole list's range.
                    Item {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 84; height: 6
                        Rectangle { anchors.fill: parent; radius: 3; color: "#1affffff" }
                        Rectangle {
                            readonly property real span: Math.max(1, daysCard.hi - daysCard.lo)
                            height: 6
                            radius: 3
                            x: (dayCol.modelData.min - daysCard.lo) / span * parent.width
                            width: Math.max(6, (dayCol.modelData.max - dayCol.modelData.min) / span * parent.width)
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0; color: U.tempColor(dayCol.modelData.min) }
                                GradientStop { position: 1; color: U.tempColor(dayCol.modelData.max) }
                            }
                        }
                    }
                    Item { width: 1; height: 4 }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: dayCol.modelData.precip >= 0.1 ? U.num(dayCol.modelData.precip) + " mm" : qsTr("poutaa")
                        color: dayCol.modelData.precip >= 0.1 ? "#6cb8ff" : "#6f7a86"
                        font.family: Theme.fontFamily; font.pixelSize: 12
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: qsTr("tuuli ") + Math.round(dayCol.modelData.windMax) + " m/s"
                        color: "#6f7a86"; font.family: Theme.fontFamily; font.pixelSize: 12
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: root.toggleDay(dayCol.modelData.day)
                }
            }
        }
    }
}

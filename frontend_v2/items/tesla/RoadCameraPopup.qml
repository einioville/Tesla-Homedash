import QtQuick
import frontend_v2
import "../../app/Format.js" as Format

// One Fintraffic road weather camera, whole: its pictures, one per direction it looks
// (`presets`, chosen with the tabs under the picture), and the nearest road weather station's
// readings beside them. Opened from a RoadCameras marker with the station's id; everything is
// fetched from Digitraffic (CC BY 4.0, credited in the footer) when it opens, and a reply for a
// station since closed is dropped. A picture is taken every ten minutes; its time is shown, and
// it is in the URL so a new one is not served from the image cache.
ModalDialog {
    id: popup

    property bool shown: false
    property string stationId: ""
    // { name, municipality, presets: [{ id, name, url }] }
    property var station: null
    // Preset id → when its picture was taken (ISO).
    property var taken: ({})
    // The road weather station's readings by sensor name, and when they were measured.
    property var readings: ({})
    property string readAt: ""
    property int preset: 0

    readonly property var current: station && station.presets.length > preset ? station.presets[preset] : null

    visible: shown

    function open(id) {
        stationId = id
        station = null
        taken = {}
        readings = {}
        readAt = ""
        preset = 0
        shown = true
        get("https://tie.digitraffic.fi/api/weathercam/v1/stations/" + id, id, function (d) {
            var p = d.properties
            station = {
                name: (p.names && p.names.fi) || p.name,
                municipality: p.municipality || "",
                presets: p.presets.filter(x => x.inCollection)
                                  .map(x => ({ id: x.id, name: x.presentationName || "", url: x.imageUrl }))
            }
            if (p.nearestWeatherStationId)
                get("https://tie.digitraffic.fi/api/weather/v1/stations/" + p.nearestWeatherStationId + "/data", id,
                    function (w) {
                        var map = {}
                        for (var s of w.sensorValues || [])
                            map[s.name] = s
                        readings = map
                        readAt = w.dataUpdatedTime || ""
                    })
        })
        get("https://tie.digitraffic.fi/api/weathercam/v1/stations/" + id + "/data", id, function (d) {
            var map = {}
            for (var p of d.presets || [])
                map[p.id] = p.measuredTime
            taken = map
        })
    }

    function close() { shown = false }

    function get(url, forStation, done) {
        var xhr = new XMLHttpRequest()
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE || forStation !== popup.stationId || !popup.shown)
                return
            if (xhr.status !== 200) {
                console.warn("Road camera fetch failed: HTTP", xhr.status, url)
                return
            }
            done(JSON.parse(xhr.responseText))
        }
        xhr.open("GET", url)
        xhr.setRequestHeader("Digitraffic-User", "Tesla-Homedash")
        xhr.send()
    }

    function value(name) {
        var s = readings[name]
        return s ? s.value : undefined
    }

    function describe(name) {
        var s = readings[name]
        return s && s.sensorValueDescriptionFi ? s.sensorValueDescriptionFi : "—"
    }

    function clock(iso) {
        return iso ? Format.moment(new Date(iso).getTime()) : "—"
    }

    onScrimClicked: close()
    cardTopMargin: Theme.gridMargin + 20
    cardWidth: 940
    // Ends above the menu's swipe-up strip.
    cardHeight: Math.min(560, popup.height - cardTopMargin - 72 - Theme.gridMargin)

    Text {
        id: title
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 20
        elide: Text.ElideRight
        text: popup.station ? popup.station.name : qsTr("Ladataan…")
        font.family: Theme.fontFamily
        font.pixelSize: 19
        font.bold: true
        color: Theme.dataLabelValue
    }
    Text {
        id: subtitle
        anchors.left: title.left
        anchors.top: title.bottom
        anchors.topMargin: 2
        text: popup.station ? popup.station.municipality : ""
        font.family: Theme.fontFamily
        font.pixelSize: 13
        color: Theme.dataLabelTitle
    }

    Rectangle {
        id: picture
        anchors.left: parent.left
        anchors.top: subtitle.bottom
        anchors.margins: 20
        anchors.topMargin: 14
        width: 640
        height: 360
        radius: 10
        color: "#14181d"
        clip: true

        Image {
            id: image
            anchors.fill: parent
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            source: popup.current ? popup.current.url + "?t=" + (popup.taken[popup.current.id] || "") : ""
        }
        Text {
            anchors.centerIn: parent
            visible: image.status !== Image.Ready
            text: image.status === Image.Error ? qsTr("Kuvaa ei saatu") : qsTr("Ladataan…")
            font.family: Theme.fontFamily
            font.pixelSize: 14
            color: Theme.dataLabelTitle
        }
        Rectangle {
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.margins: 10
            visible: popup.current !== null && !!popup.taken[popup.current.id]
            width: takenText.implicitWidth + 16
            height: 24
            radius: 12
            color: "#99000000"
            Text {
                id: takenText
                anchors.centerIn: parent
                text: popup.current ? popup.clock(popup.taken[popup.current.id]) : ""
                font.family: Theme.fontFamily
                font.pixelSize: 12
                color: "white"
            }
        }
    }

    // The directions the camera looks, named as Fintraffic names them.
    Row {
        anchors.left: picture.left
        anchors.top: picture.bottom
        anchors.topMargin: 10
        spacing: 8

        Repeater {
            model: popup.station ? popup.station.presets : []

            Rectangle {
                id: tab
                required property var modelData
                required property int index
                width: tabText.implicitWidth + 24
                height: 32
                radius: 16
                color: index === popup.preset ? Theme.accent : "#26ffffff"
                Text {
                    id: tabText
                    anchors.centerIn: parent
                    text: tab.modelData.name || qsTr("Kamera %1").arg(tab.index + 1)
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: "white"
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: popup.preset = tab.index
                }
            }
        }
    }

    // The nearest road weather station: what the road and the air are like there.
    Column {
        anchors.left: picture.right
        anchors.right: parent.right
        anchors.top: picture.top
        anchors.leftMargin: 24
        anchors.rightMargin: 20
        spacing: 12

        Text {
            text: qsTr("TIESÄÄASEMA")
            font.family: Theme.fontFamily
            font.pixelSize: 12
            font.letterSpacing: 1.2
            color: Theme.cardTitle
        }

        Repeater {
            model: [
                { label: qsTr("Keli"), text: popup.describe("KELI_1") },
                { label: qsTr("Tie"), text: Format.num(popup.value("TIE_1"), "°C", 1) },
                { label: qsTr("Ilma"), text: Format.num(popup.value("ILMA"), "°C", 1) },
                { label: qsTr("Tuuli"), text: Format.has(popup.value("KESKITUULI"))
                      ? Format.num(popup.value("KESKITUULI"), "", 1) + " (" + Format.num(popup.value("MAKSIMITUULI"), "", 1) + ") m/s"
                      : "—" },
                { label: qsTr("Sade"), text: popup.describe("SADE") },
                { label: qsTr("Näkyvyys"), text: Format.num(popup.value("NÄKYVYYS_KM"), "km", 0) },
                { label: qsTr("Kosteus"), text: Format.num(popup.value("ILMAN_KOSTEUS"), "%", 0) }
            ]

            Column {
                id: reading
                required property var modelData
                spacing: 1
                Text {
                    text: reading.modelData.label
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    color: Theme.dataLabelTitle
                }
                Text {
                    text: reading.modelData.text
                    font.family: Theme.fontFamily
                    font.pixelSize: 17
                    color: Theme.dataLabelValue
                }
            }
        }

        Text {
            text: qsTr("Mitattu ") + popup.clock(popup.readAt)
            font.family: Theme.fontFamily
            font.pixelSize: 12
            color: Theme.dataLabelTitle
        }
    }

    Item {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 20
        height: closeButton.height

        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: qsTr("Lähde: Fintraffic / digitraffic.fi, lisenssi CC 4.0 BY")
            font.family: Theme.fontFamily
            font.pixelSize: 11
            color: Theme.dataLabelTitle
        }
        DialogButton {
            id: closeButton
            anchors.right: parent.right
            primary: true
            label: qsTr("Sulje")
            onActivated: popup.close()
        }
    }
}

import QtQuick
import QtPositioning
import frontend_v2
import "../../app/Format.js" as Format

// One Fintraffic road weather camera, whole: its pictures, one per direction it looks
// (`presets`, chosen with the tabs under the picture), and the nearest road weather station's
// readings beside them. Opened from a RoadCameras marker with the station's id; everything is
// fetched from Digitraffic (CC BY 4.0, credited in the footer) when it opens, and a reply for a
// station since closed is dropped. A picture is taken every ten minutes; its time is shown, and
// it is in the URL so a new one is not served from the image cache. Centred, on frosted glass
// over the view's `backdrop` (ModalDialog). Opened with a list of cameras instead (the Weather
// view's, round the home), it steps through them with the arrows in its corner, saying how far
// each is.
// A still map above the readings shows where the camera is (RoadCameraMap).
// Fetched by the display, not the backend: a tap on one display asks for it (root CLAUDE.md §5.4).
ModalDialog {
    id: popup

    property bool shown: false
    property string stationId: ""
    // { name, municipality, coordinate, presets: [{ id, name, url }] }
    property var station: null
    // Preset id → when its picture was taken (ISO).
    property var taken: ({})
    // The road weather station's readings by sensor name, and when they were measured.
    property var readings: ({})
    property string readAt: ""
    property int preset: 0
    // The cameras to step through, nearest first, as { id, km } (RoadCameraStations.within);
    // empty for one camera opened from the map.
    property var cameras: []
    property int cameraIndex: 0

    readonly property var current: station && station.presets.length > preset ? station.presets[preset] : null

    visible: shown

    function open(id) {
        cameras = []
        load(id)
    }

    function openNearest(list) {
        cameras = list
        cameraIndex = 0
        if (list.length)
            load(list[0].id)
    }

    function step(by) {
        cameraIndex = Math.max(0, Math.min(cameras.length - 1, cameraIndex + by))
        load(cameras[cameraIndex].id)
    }

    function load(id) {
        stationId = id
        station = null
        taken = {}
        readings = {}
        readAt = ""
        preset = 0
        shown = true
        get("https://tie.digitraffic.fi/api/weathercam/v1/stations/" + id, id, function (d) {
            var p = d.properties
            var at = d.geometry ? d.geometry.coordinates : null
            station = {
                name: (p.names && p.names.fi) || p.name,
                municipality: p.municipality || "",
                coordinate: at ? QtPositioning.coordinate(at[1], at[0]) : QtPositioning.coordinate(),
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
            try {
                done(JSON.parse(xhr.responseText))
            } catch (e) {
                console.warn("Road camera reply unreadable:", e, url)
            }
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

    // The map is built the first time the dialog opens with it, then kept: a map reads the whole
    // tile cache folder when it starts (items/tesla/CLAUDE.md, The basemap), and kept, it holds
    // the tiles it has shown.
    onShownChanged: if (shown) whereLoader.active = true

    onScrimClicked: close()
    cardWidth: 1040
    // Centred on the 800 px screen, it ends above the menu's swipe-up strip (the bottom 72 px).
    cardHeight: 560

    Text {
        id: title
        anchors.left: parent.left
        anchors.right: stepper.visible ? stepper.left : parent.right
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
        text: {
            var parts = []
            if (popup.station && popup.station.municipality)
                parts.push(popup.station.municipality)
            if (popup.cameras.length)
                parts.push(qsTr("%1 km päässä").arg(Format.num(popup.cameras[popup.cameraIndex].km, "", 1)))
            return parts.join(" · ")
        }
        font.family: Theme.fontFamily
        font.pixelSize: 13
        color: Theme.dataLabelTitle
    }

    component StepButton: Rectangle {
        id: stepButton
        property string icon
        signal activated()
        width: 36
        height: 36
        radius: 18
        color: stepTap.pressed ? "#40ffffff" : "#26ffffff"
        opacity: enabled ? 1 : 0.35
        TintedIcon {
            anchors.centerIn: parent
            iconSize: 18
            source: stepButton.icon
        }
        MouseArea {
            id: stepTap
            anchors.fill: parent
            anchors.margins: -4
            onClicked: stepButton.activated()
        }
    }

    // Nearer and farther cameras, when there is a list to step through.
    Row {
        id: stepper
        visible: popup.cameras.length > 1
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 20
        spacing: 10

        StepButton {
            icon: "qrc:/resources/icons/arrow_left.svg"
            enabled: popup.cameraIndex > 0
            onActivated: popup.step(-1)
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: 64
            horizontalAlignment: Text.AlignHCenter
            text: (popup.cameraIndex + 1) + " / " + popup.cameras.length
            font.family: Theme.fontFamily
            font.pixelSize: 15
            color: Theme.dataLabelValue
        }
        StepButton {
            icon: "qrc:/resources/icons/arrow_right.svg"
            enabled: popup.cameraIndex < popup.cameras.length - 1
            onActivated: popup.step(1)
        }
    }

    Item {
        id: picture
        anchors.left: parent.left
        anchors.top: subtitle.bottom
        anchors.margins: 20
        anchors.topMargin: 14
        width: 640
        height: 360

        // Where the picture goes, while it loads.
        Rectangle {
            anchors.fill: parent
            radius: image.radius
            color: "#33000000"
        }
        RoundedImage {
            id: image
            anchors.fill: parent
            radius: 10
            fillMode: Image.PreserveAspectCrop
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

    // Where the camera is, then the nearest road weather station: what the road and the air are
    // like there, measured at the time beside its title.
    Column {
        anchors.left: picture.right
        anchors.right: parent.right
        anchors.top: picture.top
        anchors.leftMargin: 24
        anchors.rightMargin: 20
        spacing: 14

        Loader {
            id: whereLoader
            width: parent.width
            height: 180
            active: false
            sourceComponent: RoadCameraMap {
                active: popup.shown
                coordinate: popup.station ? popup.station.coordinate : QtPositioning.coordinate()
            }
        }

        Item {
            width: parent.width
            height: stationTitle.implicitHeight

            Text {
                id: stationTitle
                text: qsTr("TIESÄÄASEMA")
                font.family: Theme.fontFamily
                font.pixelSize: 12
                font.letterSpacing: 1.2
                color: Theme.cardTitle
            }
            Text {
                anchors.right: parent.right
                anchors.baseline: stationTitle.baseline
                visible: popup.readAt !== ""
                text: popup.clock(popup.readAt)
                font.family: Theme.fontFamily
                font.pixelSize: 12
                color: Theme.dataLabelTitle
            }
        }

        // Ordered so that, in pairs, the road's state sits beside the rain and the
        // temperatures beside each other.
        Grid {
            id: readingGrid
            width: parent.width
            columns: 2
            columnSpacing: 16
            rowSpacing: 10

            Repeater {
                model: [
                    { label: qsTr("Keli"), text: popup.describe("KELI_1") },
                    { label: qsTr("Sade"), text: popup.describe("SADE") },
                    { label: qsTr("Tie"), text: Format.num(popup.value("TIE_1"), "°C", 1) },
                    { label: qsTr("Ilma"), text: Format.num(popup.value("ILMA"), "°C", 1) },
                    { label: qsTr("Tuuli"), text: Format.has(popup.value("KESKITUULI"))
                          ? Format.num(popup.value("KESKITUULI"), "", 1) + " (" + Format.num(popup.value("MAKSIMITUULI"), "", 1) + ") m/s"
                          : "—" },
                    { label: qsTr("Näkyvyys"), text: Format.num(popup.value("NÄKYVYYS_KM"), "km", 0) },
                    { label: qsTr("Kosteus"), text: Format.num(popup.value("ILMAN_KOSTEUS"), "%", 0) }
                ]

                Column {
                    id: reading
                    required property var modelData
                    width: (readingGrid.width - readingGrid.columnSpacing) / 2
                    spacing: 1
                    Text {
                        text: reading.modelData.label
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        color: Theme.dataLabelTitle
                    }
                    Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: reading.modelData.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 17
                        color: Theme.dataLabelValue
                    }
                }
            }
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

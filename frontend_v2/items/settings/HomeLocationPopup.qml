import QtQuick
import QtQuick.Controls
import QtQuick.Shapes
import QtLocation
import QtPositioning
import frontend_v2

// The Koti row's dialog: the home found by its address (Nominatim through Geocoder, on Hae or
// Enter — its policy allows no search-as-you-type) or by a tap on the map, whose address is
// then looked up. Tallenna writes the backend's `home` setting { address, lat, lon }, and the
// backend adds the point's timezone; the write's result shows beside the row. Hung from the top,
// so the field and the hits under it stay above the on-screen keyboard.
ModalDialog {
    id: popup

    property bool shown: false
    // The point chosen, { address, lat, lon }; the address is "" while its lookup runs.
    property var chosen: null

    visible: shown
    cardWidth: 1040
    cardTopMargin: 40
    // Ends above the menu's swipe-up strip (the bottom 72 px).
    cardHeight: 640

    onScrimClicked: close()

    function open() {
        Geocoder.clear()
        field.text = ""
        const home = Settings.valueOf("home")
        chosen = home ? { address: home.address, lat: home.lat, lon: home.lon } : null
        shown = true
        // Without a home, the place the weather is for now.
        const meta = Weather.view.meta
        if (home)
            centre(home.lat, home.lon, 15)
        else if (meta)
            centre(meta.lat, meta.lon, 11)
        else
            centre(61.497063, 23.750078, 11)
    }

    function close() {
        Qt.inputMethod.hide()
        shown = false
    }

    function centre(lat, lon, zoom) {
        map.center = QtPositioning.coordinate(lat, lon)
        map.zoomLevel = zoom
    }

    function coordinates(lat, lon) {
        return lat.toFixed(5) + ", " + lon.toFixed(5)
    }

    function search() {
        if (field.text.trim() === "")
            return
        field.focus = false
        Qt.inputMethod.hide()
        Geocoder.search(field.text)
    }

    function pick(hit) {
        chosen = { address: hit.address, lat: hit.lat, lon: hit.lon }
        centre(hit.lat, hit.lon, 16)
    }

    function save() {
        if (!chosen)
            return
        Settings.setValue("home", { address: chosen.address || coordinates(chosen.lat, chosen.lon),
                                    lat: chosen.lat, lon: chosen.lon })
        close()
    }

    Connections {
        target: Geocoder
        enabled: popup.shown

        function onAddressFound(lat, lon, address) {
            if (popup.chosen && popup.chosen.lat === lat && popup.chosen.lon === lon)
                popup.chosen = { address: address || popup.coordinates(lat, lon), lat: lat, lon: lon }
        }
    }

    Text {
        id: title
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 20
        text: qsTr("Koti")
        font.family: Theme.fontFamily
        font.pixelSize: 19
        font.bold: true
        color: Theme.dataLabelValue
    }

    Text {
        id: hint
        anchors.left: title.left
        anchors.top: title.bottom
        anchors.topMargin: 2
        text: qsTr("Hae osoitteella tai napauta kotisi kohtaa kartalla. Sää ja aikavyöhyke "
                   + "seuraavat kotia.")
        font.family: Theme.fontFamily
        font.pixelSize: 13
        color: Theme.dataLabelTitle
    }

    Item {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 8
        width: 34
        height: 34

        TintedIcon {
            anchors.centerIn: parent
            iconSize: 18
            source: "qrc:/resources/icons/xmark.svg"
            tint: closeArea.pressed ? Theme.dataLabelValue : Theme.dataLabelTitle
        }

        MouseArea {
            id: closeArea
            anchors.fill: parent
            onClicked: popup.close()
        }
    }

    Item {
        id: searchRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: hint.bottom
        anchors.leftMargin: 20
        anchors.rightMargin: 20
        anchors.topMargin: 14
        height: 40

        Rectangle {
            anchors.left: parent.left
            anchors.right: searchButton.left
            anchors.rightMargin: 10
            height: parent.height
            radius: 8
            color: field.activeFocus ? Theme.tripComboPressed : Theme.tripComboBg
            border.width: 1
            border.color: field.activeFocus ? Theme.accent : Theme.tripCardBorder

            TextField {
                id: field
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                placeholderText: qsTr("Katuosoite ja paikkakunta, esim. Hämeenkatu 1, Tampere")
                placeholderTextColor: Theme.dataLabelTitle
                font.family: Theme.fontFamily
                font.pixelSize: 15
                color: Theme.dataLabelValue
                verticalAlignment: TextInput.AlignVCenter
                background: null
                // Prediction holds text in pre-edit, off `text`, until a word is done.
                inputMethodHints: Qt.ImhNoPredictiveText
                onAccepted: popup.search()
            }
        }

        DialogButton {
            id: searchButton
            anchors.right: parent.right
            height: parent.height
            width: 96
            label: qsTr("Hae")
            onActivated: popup.search()
        }
    }

    // The hits, and what the search is doing.
    Item {
        id: hits
        anchors.left: parent.left
        anchors.top: searchRow.bottom
        anchors.bottom: footer.top
        anchors.leftMargin: 20
        anchors.topMargin: 14
        anchors.bottomMargin: 14
        width: 360

        Text {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            visible: Geocoder.busy || Geocoder.error !== "" || Geocoder.results.length === 0
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: 13
            color: Geocoder.error !== "" && !Geocoder.busy ? "#ffd48a" : Theme.dataLabelTitle
            text: Geocoder.busy ? qsTr("Haetaan…")
                : Geocoder.error !== "" ? Geocoder.error
                : qsTr("Hakutulokset näkyvät tässä.")
        }

        ListView {
            anchors.fill: parent
            visible: !Geocoder.busy && Geocoder.results.length > 0
            clip: true
            spacing: 6
            model: Geocoder.results

            delegate: Rectangle {
                id: hit
                required property var modelData
                readonly property bool isChosen: popup.chosen !== null
                                                 && popup.chosen.lat === modelData.lat
                                                 && popup.chosen.lon === modelData.lon
                width: ListView.view.width
                height: 52
                radius: 8
                color: hitTap.pressed ? Theme.tripComboPressed : Theme.tripComboBg
                border.width: 1
                border.color: isChosen ? Theme.accent : Theme.tripCardBorder

                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    text: hit.modelData.address
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    color: Theme.dataLabelValue
                }

                MouseArea {
                    id: hitTap
                    anchors.fill: parent
                    onClicked: popup.pick(hit.modelData)
                }
            }
        }
    }

    Rectangle {
        anchors.left: hits.right
        anchors.right: parent.right
        anchors.top: hits.top
        anchors.bottom: hits.bottom
        anchors.leftMargin: 14
        anchors.rightMargin: 20
        color: "#14181d"
        clip: true

        BasemapPlugin {
            id: osmPlugin
        }

        Map {
            id: map
            anchors.fill: parent
            plugin: osmPlugin
            // QTBUG-62463/67169, as in TripMap: under an overlay, tiles mis-batch and draw
            // white; an opacity below 1 keeps the map in the alpha pass.
            opacity: 0.99
            copyrightsVisible: false
            zoomLevel: 11

            readonly property real minZoom: 5
            readonly property real maxZoom: 19

            function zoomTo(level) {
                zoomLevel = Math.max(minZoom, Math.min(maxZoom, level))
            }

            BasemapSwitch {
                geoMap: map
                active: popup.shown
            }

            // A tap places the home; its address is looked up.
            TapHandler {
                onTapped: (point) => {
                    const c = map.toCoordinate(point.position, false)
                    popup.chosen = { address: "", lat: c.latitude, lon: c.longitude }
                    Geocoder.reverse(c.latitude, c.longitude)
                }
            }

            DragHandler {
                target: null
                property point last
                onActiveChanged: last = Qt.point(0, 0)
                onTranslationChanged: {
                    map.pan(last.x - translation.x, last.y - translation.y)
                    last = translation
                }
            }

            PinchHandler {
                target: null
                property real startZoom: 11
                onActiveChanged: if (active) startZoom = map.zoomLevel
                onActiveScaleChanged: if (active) map.zoomTo(startZoom + Math.log2(activeScale))
            }

            WheelHandler {
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                onWheel: (event) => map.zoomTo(map.zoomLevel + event.angleDelta.y / 120 * 0.5)
            }

            MapQuickItem {
                visible: popup.chosen !== null
                coordinate: popup.chosen ? QtPositioning.coordinate(popup.chosen.lat, popup.chosen.lon)
                                         : QtPositioning.coordinate()
                // The pin's point is the bottom middle of the icon.
                anchorPoint.x: 18
                anchorPoint.y: 31.5
                // location.svg's two paths (24 px grid) at 36 px, filled red and outlined in
                // black so it stands out on the aerial imagery; a tint colours one part only.
                // One path, even-odd, so the inner circle is a hole the map shows through.
                sourceItem: Shape {
                    width: 36
                    height: 36
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        scale: Qt.size(1.5, 1.5)
                        fillColor: "#e0302a"
                        fillRule: ShapePath.OddEvenFill
                        strokeColor: "black"
                        strokeWidth: 3
                        joinStyle: ShapePath.RoundJoin
                        PathSvg { path: "M12 21C15.5 17.4 19 14.1764 19 10.2C19 6.22355 15.866 3 12 3C8.13401 3 5 6.22355 5 10.2C5 14.1764 8.5 17.4 12 21Z M12 13C13.6569 13 15 11.6569 15 10C15 8.34315 13.6569 7 12 7C10.3431 7 9 8.34315 9 10C9 11.6569 10.3431 13 12 13Z" }
                    }
                }
            }
        }

        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: 1
            border.color: Theme.tripCardBorder
        }
    }

    Item {
        id: footer
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 20
        height: 34

        Text {
            anchors.left: parent.left
            anchors.right: buttons.left
            anchors.rightMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: 13
            color: Theme.dataLabelValue
            text: {
                const c = popup.chosen
                if (!c)
                    return qsTr("Ei valittua kohtaa")
                return (c.address !== "" ? c.address : qsTr("Haetaan osoitetta…"))
                       + "  ·  " + popup.coordinates(c.lat, c.lon)
            }
        }

        Row {
            id: buttons
            anchors.right: parent.right
            spacing: 10

            DialogButton {
                label: qsTr("Peruuta")
                onActivated: popup.close()
            }
            DialogButton {
                primary: true
                enabled: popup.chosen !== null
                opacity: enabled ? 1 : 0.4
                label: qsTr("Tallenna")
                onActivated: popup.save()
            }
        }
    }
}

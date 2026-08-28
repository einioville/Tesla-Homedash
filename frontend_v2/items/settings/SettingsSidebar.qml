import QtQuick
import QtQuick.Controls
import frontend_v2

// Section list for the Options view — the "master" half of a master/detail
// layout. One row per schema group; the selected row's settings fill the pane to
// the right.
//
// Selection is tracked by group ID rather than index on purpose: the group list
// grows when the backend's schema arrives (three local sections at startup, eight
// once connected) and shrinks again if the backend goes away, so an index would
// silently point at a different section. `currentId` survives both.
//
// Icons are named SEMANTICALLY in the schema ("charger", "media", …) and mapped
// to resources here, so the backend never has to know about frontend assets.
Rectangle {
    id: sidebar

    required property var groups
    property string currentId: ""

    signal sectionSelected(string id)

    color: Theme.tripCardBg
    radius: Theme.tripCardRadius
    border.width: 1
    border.color: Theme.tripCardBorder

    // Semantic icon name -> resource. An unrecognised name (a backend newer than
    // this build) falls back to the gear rather than rendering nothing.
    readonly property var iconMap: ({
        "app": "qrc:/resources/icons/app.svg",
        "chart": "qrc:/resources/icons/chart_line.svg",
        "link": "qrc:/resources/icons/link.svg",
        "gear": "qrc:/resources/icons/settings.svg",
        "media": "qrc:/resources/icons/music.svg",
        "charger": "qrc:/resources/icons/charger.svg",
        "price": "qrc:/resources/icons/price.svg",
        "trip": "qrc:/resources/icons/trip.svg",
        "restart": "qrc:/resources/icons/restart.svg"
    })

    function iconFor(name) {
        return iconMap[name] !== undefined ? iconMap[name] : iconMap["gear"]
    }

    ListView {
        id: list
        anchors.fill: parent
        anchors.margins: 8
        clip: true
        spacing: 2
        model: sidebar.groups
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {
            policy: list.contentHeight > list.height ? ScrollBar.AsNeeded
                                                     : ScrollBar.AlwaysOff
        }

        delegate: Rectangle {
            id: row

            required property var modelData

            readonly property bool current: modelData.id === sidebar.currentId
            readonly property bool isBackend: modelData.origin === "backend"

            width: ListView.view.width
            height: 52
            radius: 8
            color: current ? Theme.tripComboHover
                           : (tap.pressed ? Theme.tripComboPressed : "transparent")

            Behavior on color {
                ColorAnimation { duration: Theme.pressDuration }
            }

            // Accent rail on the selected row — the usual settings-app cue, and
            // it reads at a glance on a touchscreen where there is no hover.
            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 3
                anchors.verticalCenter: parent.verticalCenter
                width: 3
                height: parent.height * 0.55
                radius: 2
                color: Theme.accent
                visible: row.current
            }

            TintedIcon {
                id: sectionIcon
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                iconSize: 20
                source: sidebar.iconFor(row.modelData.icon)
                tint: row.current ? Theme.dataLabelValue : Theme.dataLabelTitle
            }

            Column {
                anchors.left: sectionIcon.right
                anchors.leftMargin: 12
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1

                Text {
                    text: row.modelData.label !== undefined ? row.modelData.label
                                                            : row.modelData.id
                    font.family: Theme.fontFamily
                    font.pixelSize: 15
                    color: row.current ? Theme.dataLabelValue : "#d0d4da"
                    elide: Text.ElideRight
                    width: parent.width
                }

                // Where this section's values actually live. Worth stating: the
                // two halves fail differently — a backend section can reject a
                // value or be unreachable entirely.
                Text {
                    text: row.isBackend
                          ? qsTr("palvelin") + " · " + row.modelData.settings.length
                          : qsTr("sovellus") + " · " + row.modelData.settings.length
                    font.family: Theme.fontFamily
                    font.pixelSize: 10
                    color: row.isBackend ? "#9ecbf0" : Theme.dataLabelTitle
                }
            }

            MouseArea {
                id: tap
                anchors.fill: parent
                onClicked: sidebar.sectionSelected(row.modelData.id)
            }
        }
    }
}

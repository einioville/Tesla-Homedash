import QtQuick
import QtQuick.Controls
import frontend_v2

// Detail pane: the settings of the ONE section selected in the sidebar.
//
// Replaces the earlier all-groups-at-once layout. With a single section on
// screen the rows get the full width, so a setting's help text sits on one or two
// lines instead of wrapping into a narrow column, and the editors get room to be
// finger-sized. The Flickable is still here because the largest sections (five
// settings with help text) can just exceed the available height.
Item {
    id: pane

    // The selected group from Settings.groups, or undefined while none is
    // selected / the list is still empty.
    property var groupData

    readonly property bool hasData: groupData !== undefined && groupData !== null
    readonly property bool isBackend: hasData && groupData.origin === "backend"

    // --- Section header ---------------------------------------------------
    Item {
        id: paneHeader
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: pane.hasData ? 40 : 0
        visible: pane.hasData

        Text {
            id: paneTitle
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: pane.hasData && pane.groupData.label !== undefined
                  ? pane.groupData.label : ""
            font.family: Theme.fontFamily
            font.pixelSize: 20
            color: Theme.dataLabelValue
        }

        // Says where the values are written. The sidebar carries the same tag,
        // but once a section fills the screen the sidebar row is easy to lose.
        Rectangle {
            anchors.left: paneTitle.right
            anchors.leftMargin: 10
            anchors.verticalCenter: paneTitle.verticalCenter
            width: originLabel.implicitWidth + 14
            height: originLabel.implicitHeight + 5
            radius: 4
            color: pane.isBackend ? "#332f81c4" : "#33ffffff"
            border.width: 1
            border.color: pane.isBackend ? "#802f81c4" : "#44ffffff"

            Text {
                id: originLabel
                anchors.centerIn: parent
                text: pane.isBackend ? qsTr("palvelimen asetukset")
                                     : qsTr("sovelluksen asetukset")
                font.family: Theme.fontFamily
                font.pixelSize: 10
                color: pane.isBackend ? "#9ecbf0" : Theme.dataLabelTitle
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Theme.tripCardBorder
        }
    }

    // --- Rows -------------------------------------------------------------
    Flickable {
        id: flick
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: paneHeader.bottom
        anchors.bottom: parent.bottom
        anchors.topMargin: 4

        contentHeight: rows.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {
            policy: flick.contentHeight > flick.height ? ScrollBar.AlwaysOn
                                                       : ScrollBar.AlwaysOff
        }

        Column {
            id: rows
            width: flick.width
            spacing: 0

            Repeater {
                model: pane.hasData ? pane.groupData.settings : []

                Column {
                    required property int index
                    required property var modelData

                    width: rows.width

                    SettingRow {
                        width: parent.width
                        // Wider than the old two-column layout allowed; a slider
                        // this size is comfortable to drag with a fingertip.
                        editorWidth: 320
                        setting: modelData
                    }

                    Rectangle {
                        visible: index < (pane.hasData ? pane.groupData.settings.length - 1 : 0)
                        width: parent.width
                        height: 1
                        color: "#1affffff"
                    }
                }
            }
        }
    }

    // Shown before the first schema arrives (and if one never does).
    Text {
        anchors.centerIn: parent
        visible: !pane.hasData
        text: qsTr("Valitse osio")
        font.family: Theme.fontFamily
        font.pixelSize: 14
        color: Theme.dataLabelTitle
    }
}

import QtQuick
import frontend_v2

Item {
    id: dock

    // model: array of { name, icon, component } (the app's single view model).
    property var model: []
    property int currentIndex: 0

    // Dashboard host captured + blurred behind the dock for the frosted-glass
    // background; glassActive gates the capture so it only runs while the dock is
    // actually on screen (it slides off-screen rather than hiding).
    property Item backdropSource: null
    property bool glassActive: true

    signal selected(int index)
    signal interacted()

    implicitWidth: iconRow.implicitWidth + 2 * Theme.dockPadding
    implicitHeight: iconRow.implicitHeight + 2 * Theme.dockPadding

    GlassPanel {
        anchors.fill: parent
        radius: Theme.dockRadius
        backdropSource: dock.backdropSource
        // The dock is a direct child of the window, so its x/y are the backdrop's
        // coordinates.
        backdropOrigin: Qt.point(dock.x, dock.y)
        active: dock.glassActive
    }

    Row {
        id: iconRow
        anchors.centerIn: parent
        spacing: Theme.dockSpacing

        Repeater {
            model: dock.model

            DockIcon {
                required property int index
                required property var modelData

                label: modelData.name
                source: modelData.icon
                selected: index === dock.currentIndex
                onClicked: {
                    dock.selected(index)
                    dock.interacted()
                }
            }
        }
    }
}

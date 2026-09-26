import QtQuick
import frontend_v2

// Picks one setting row out of the Options view: the view blurs its content (it
// enables the same layer the dialogs use while `active`), and this draws a crisp
// copy of the row, ringed, on top — until the next tap anywhere. "Korjaa" in the
// issues box ends here, so the fix is the one thing left legible on screen.
//
// The copy is a ShaderEffectSource of the real row, not the row itself: the row
// cannot leave the blurred layer, and a copy drawn over it is the only way to
// show it sharp. So the copy is never touched. A press ON it dismisses the
// spotlight and is let through to the real row underneath — tapping the
// highlighted "Kirjaudu" should work first time — while a press anywhere else is
// swallowed, so a blind tap on the blur cannot flip a switch it could not see.
//
// The row is looked up by key (SettingsPane.rowItem) on every tick rather than
// held: Settings.groups is replaced on any write, which destroys and rebuilds
// every row, and a status widget settling can move one.
Item {
    id: spotlight

    // The SettingsPane to search and scroll.
    property SettingsPane pane

    property string key: ""
    readonly property bool active: key.length > 0
    property Item target: null
    // The row's rectangle in this item's coordinates.
    property rect area: Qt.rect(0, 0, 0, 0)
    // Ticks since show(); the first few re-scroll the row into view, since the
    // section it lives in may only just have been built.
    property int ticks: 0

    function show(settingKey) {
        spotlight.ticks = 0
        spotlight.key = settingKey
        spotlight.relocate()
    }

    function dismiss() {
        spotlight.key = ""
        spotlight.target = null
    }

    function relocate() {
        const row = spotlight.pane !== null ? spotlight.pane.rowItem(spotlight.key) : null
        spotlight.target = row
        if (row === null) {
            // Its section never produced it (that half of the schema is gone):
            // give up rather than leave a blurred screen with nothing to find.
            if (spotlight.ticks > 12)
                spotlight.dismiss()
            return
        }
        if (spotlight.ticks <= 3)
            spotlight.pane.revealRow(row)
        const p = row.mapToItem(spotlight, 0, 0)
        spotlight.area = Qt.rect(p.x, p.y, row.width, row.height)
    }

    anchors.fill: parent
    visible: active
    z: 90

    Timer {
        interval: 80
        repeat: true
        running: spotlight.active
        onTriggered: {
            ++spotlight.ticks
            spotlight.relocate()
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "#4d000000"
    }

    // The card behind the row, recreated: the view's background with the card's
    // translucent grey over it, which is exactly how the row normally sits. The
    // cards' inner margin (14) is added back on both sides so the plate spans the
    // card's width.
    Rectangle {
        id: plate
        // Not before the first tick: a section that was only just selected has
        // not been laid out yet, and its rows all measure at the top.
        visible: spotlight.target !== null && spotlight.ticks > 0
        x: spotlight.area.x - 14
        y: spotlight.area.y
        width: spotlight.area.width + 28
        height: spotlight.area.height
        radius: Theme.tripCardRadius
        color: Theme.tripBackground

        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: Theme.tripCardBg
        }

        ShaderEffectSource {
            x: 14
            width: spotlight.area.width
            height: spotlight.area.height
            sourceItem: spotlight.target
            live: true
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: parent.radius + 3
            color: "transparent"
            border.width: 2
            border.color: Theme.accent
        }
    }

    MouseArea {
        anchors.fill: parent
        onPressed: (mouse) => {
            const onRow = plate.visible && mouse.x >= plate.x && mouse.x <= plate.x + plate.width
                          && mouse.y >= plate.y && mouse.y <= plate.y + plate.height
            spotlight.dismiss()
            // Not accepting is what hands the press to the real row beneath.
            mouse.accepted = !onRow
        }
    }
}

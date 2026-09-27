import QtQuick
import frontend_v2

// Night mode (Yleinen > Yötila): between two clock times the screensaver is set
// aside and the panel powers off after a much shorter idle than by day, then
// wakes by itself when the window ends.
//
// This only DECIDES. Main.qml routes `active` into machinery that already exists
// — it holds the screensaver back and arms Display with the short timeout — so
// night mode inherits every rule Display already follows: wake on touch, the
// update inhibit, the wlopm fault handling. Nothing here talks to the backend or
// to the panel.
//
// The clock is the FRONTEND's local time, which on the target is the same host
// as the backend's timeZone setting.
Item {
    id: root
    visible: false

    // Minutes since local midnight. Seeded at construction, not by the first
    // tick: a placeholder 0 would read as "just past midnight", put the window
    // in effect for one tick and wake the panel on the way out.
    property int nowMin: root.minuteOfDay()

    // A window that crosses midnight (22:00–06:30) is the normal case, hence
    // the two branches. start === end is no window at all rather than 24 h —
    // "always dark" is not a night mode anyone means to pick.
    readonly property bool inWindow: {
        const start = Theme.nightStartMin
        const end = Theme.nightEndMin
        if (start === end)
            return false
        return start < end ? (nowMin >= start && nowMin < end)
                           : (nowMin >= start || nowMin < end)
    }
    readonly property bool active: Theme.nightModeEnabled && inWindow

    function minuteOfDay() {
        const now = new Date()
        return now.getHours() * 60 + now.getMinutes()
    }

    // 15 s keeps the edges within a quarter-minute of the set time, and the
    // binding above only re-runs when the minute actually changes.
    Timer {
        interval: 15000
        repeat: true
        running: true
        onTriggered: root.nowMin = root.minuteOfDay()
    }

    // Morning: the window ending counts as a touch. Through Display's activity
    // hook that powers a dark panel back on, whatever the daytime settings would
    // otherwise leave it in.
    onActiveChanged: if (!active) Idle.poke()
}

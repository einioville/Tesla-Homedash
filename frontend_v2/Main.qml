import QtQuick
import QtQuick.VirtualKeyboard
import QtQuick.VirtualKeyboard.Settings
import frontend_v2

Window {
    id: window
    width: 1280
    height: 800

    // Embedded dashboard: the target is a fixed 1280×800 panel and every card is
    // hand-tuned for exactly that size, so in a window it is LOCKED — no resizing
    // and no content scaling, min == max == the design size. Fullscreen has to
    // release that lock or the compositor cannot size the surface at all; on the
    // target the panel IS 1280×800, so nothing stretches there.
    readonly property bool locked: visibility !== Window.FullScreen
    minimumWidth: locked ? 1280 : 0
    maximumWidth: locked ? 1280 : 16777215
    minimumHeight: locked ? 800 : 0
    maximumHeight: locked ? 800 : 16777215

    // Fullscreen is a user setting (defaulting from TESLA_HOMEDASH_FULLSCREEN),
    // with one override: while a Spotify re-authorization is running the window
    // steps back to windowed, because the consent page opens in the host's own
    // browser and has to be reachable on top of us. On labwc — Raspberry Pi OS
    // Bookworm's compositor — squeekboard is hardcoded to the `top` layer and does
    // not draw over a fullscreen surface (labwc#2926), so a fullscreen dashboard
    // would leave the on-screen keyboard unreachable and the login untypeable.
    visibility: Settings.values.fullscreen === true &&
                SpotifyAuth.phase === "idle" ? Window.FullScreen : Window.Windowed
    visible: true
    title: qsTr("Tesla Homedash v2")
    color: Theme.appBackground

    // Single source of truth for the views: the dock reads name/icon, the
    // ViewController reads component. Add a view by adding one entry here plus
    // its inline Component below.
    // The legacy dashboard is the only view for now (the data-layer demo views
    // were dropped). New views slot in here as the design evolves.
    readonly property var viewModel: [
        { name: qsTr("Dashboard"), icon: "qrc:/resources/icons/home.svg", component: dashboardComponent },
        { name: qsTr("Kartta"), icon: "qrc:/resources/icons/location.svg", component: mapComponent },
        { name: qsTr("Musiikki"), icon: "qrc:/resources/icons/music.svg", component: mediaComponent },
        { name: qsTr("Historia"), icon: "qrc:/resources/icons/chart_line.svg", component: historyComponent },
        { name: qsTr("Matkat"), icon: "qrc:/resources/icons/trip.svg", component: tripsComponent },
        { name: qsTr("Lataus"), icon: "qrc:/resources/icons/charger.svg", component: chargingComponent },
        { name: qsTr("Asetukset"), icon: "qrc:/resources/icons/settings.svg", component: settingsComponent }
    ]
    property int currentView: 0

    // A keyboard left up over a view the user has switched to belongs to a field
    // they can no longer see; the views stay resident, so focus would stay put.
    onCurrentViewChanged: dismissKeyboard()

    // Closes the on-screen keyboard by moving focus off the field, which also
    // fires its editingFinished — so the typed value commits exactly as it
    // would on a desktop focus change. Qt.inputMethod.hide() alone would close
    // the panel and leave the edit pending in a field nobody is looking at.
    function dismissKeyboard() {
        if (!Qt.inputMethod.visible)
            return
        if (window.activeFocusItem !== null)
            window.activeFocusItem.focus = false
        Qt.inputMethod.hide()
    }

    Component { id: dashboardComponent; DashboardView {} }
    Component { id: mapComponent; MapView {} }
    Component { id: mediaComponent; MediaView {} }
    Component { id: historyComponent; HistoryView {} }
    Component { id: tripsComponent; TripsView {} }
    Component { id: chargingComponent; ChargingView {} }
    Component { id: settingsComponent; SettingsView {} }

    // --- Dock reveal state ------------------------------------------------
    // 0.0 = dock fully hidden (off-screen), 1.0 = dock fully shown.
    // The dock is a frosted overlay and deliberately floats OVER the cards when
    // revealed (the blur shows them behind it).
    property real progress: 1.0
    // Dock bottom sits twice the card padding off the window's bottom edge —
    // i.e. as far from the edge as the cards are, doubled (2 × 10px = bottom at
    // 780 on an 800-tall window).
    readonly property real dockShownY: height - dock.height - 2 * Theme.gridMargin
    readonly property real dockHiddenY: height + 8

    function showDock() {
        progress = 1.0
        hideTimer.restart()
    }

    function hideDock() {
        progress = 0.0
        hideTimer.stop()
    }

    // Animates snap-on-release and auto-hide; suppressed while the finger drags.
    Behavior on progress {
        enabled: !revealDrag.active
        NumberAnimation { duration: Theme.dockDuration; easing.type: Easing.OutCubic }
    }

    Timer {
        id: hideTimer
        interval: Theme.dockHideMs
        repeat: false
        onTriggered: window.hideDock()
    }

    // Home return (Yleinen > Navigointi): an idle panel switches back to the
    // dashboard. Runs only while another view is showing and restarts on every
    // input event, so it measures time since the LAST touch. It keeps counting
    // under the screensaver, which is what makes the screensaver lift onto the
    // dashboard. Switching views also closes the keyboard, which commits a
    // half-typed setting rather than stranding it (dismissKeyboard above).
    Timer {
        id: homeReturnTimer
        interval: Theme.homeReturnMs
        running: Theme.homeReturnEnabled && window.currentView !== 0
        onTriggered: window.currentView = 0
    }
    Connections {
        target: Idle

        function onActivity() {
            if (homeReturnTimer.running)
                homeReturnTimer.restart()
        }
    }

    // Night mode (Yleinen > Yötila). Decides only; the Bindings at the bottom of
    // this file and the screensaver's `nightMode` act on it.
    NightSchedule {
        id: nightSchedule
    }

    // One-time Qt Graphs renderer warm-up, hidden behind the (opaque) views so it
    // renders — and thus compiles its GPU pipeline — during boot instead of on the
    // first switch to the History view. Unloads itself once compiled.
    Component {
        id: graphPrewarmComponent
        GraphPrewarm { onDone: graphPrewarmLoader.active = false }
    }
    Loader {
        id: graphPrewarmLoader
        width: 320
        height: 240
        z: -1
        active: true
        sourceComponent: graphPrewarmComponent
    }

    ViewController {
        id: viewHost
        anchors.fill: parent
        model: window.viewModel
        currentIndex: window.currentView
        // Stop painting the live views while the screensaver covers them (saves
        // GPU on the Pi); the ViewController keeps them resident, so returning is
        // instant. If the map reloads tiles on return, drop this one line — the
        // screensaver works without it.
        visible: !screenSaver.active
    }

    HomeIndicator {
        id: homeIndicator
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        // Centred vertically within the window's bottom card padding: that strip
        // is Theme.gridMargin tall, so centring an indicator of height `h` means a
        // bottom margin of (padding − h) / 2. Size lives in HomeIndicator.qml.
        anchors.bottomMargin: (Theme.gridMargin - height) / 2
        opacity: 1.0 - window.progress
    }

    // Dock-reveal swipe zone — a SMALL strip centred over the home indicator,
    // deliberately NOT a full-width catcher, so it can't sit over the media card
    // (far left) or the climate card (far right) and their bottom controls. It is
    // also a DragHandler (not a MouseArea), so it only grabs once a vertical swipe
    // crosses the threshold and a tap falls straight through. Swipe up from the
    // centre-bottom (where the home indicator is) to reveal the dock.
    Item {
        id: revealArea
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        width: 360
        height: 72

        property real pressProgress: 1.0
        readonly property real travel: window.dockHiddenY - window.dockShownY

        DragHandler {
            id: revealDrag
            target: null
            xAxis.enabled: false
            yAxis.enabled: true

            onActiveChanged: {
                if (active) {
                    revealArea.pressProgress = window.progress
                    hideTimer.stop()
                } else {
                    if (window.progress > 0.5)
                        window.showDock()
                    else
                        window.hideDock()
                }
            }
            onActiveTranslationChanged: {
                if (!active)
                    return
                // Dragging up yields a negative y translation; reveal grows progress.
                const delta = -activeTranslation.y / revealArea.travel
                window.progress = Math.max(0.0, Math.min(1.0, revealArea.pressProgress + delta))
            }
        }
    }

    Dock {
        id: dock
        x: (window.width - width) / 2
        y: window.dockHiddenY + (window.dockShownY - window.dockHiddenY) * window.progress
        model: window.viewModel
        currentIndex: window.currentView
        // Frost the dashboard behind the dock; capture only while it's on screen.
        backdropSource: viewHost
        glassActive: window.progress > 0.01
        onSelected: (index) => window.currentView = index
        onInteracted: hideTimer.restart()
        onScreensaverRequested: screenSaver.forceShow = true
    }

    // Smartphone-style notifications, above all other chrome (top-centre). The
    // view host is handed in as the frosted-glass backdrop (captured + blurred
    // behind the pill). Flip frostedBackdrop to false if the live-map capture is
    // too heavy on the target device — it falls back to the plain glass.
    NotificationLayer {
        anchors.fill: parent
        z: 200
        backdropSource: viewHost
        frostedBackdrop: true
    }

    // Spotify re-authorization, at APP level rather than inside the Options view.
    // Both have to be here: the grant can die while any view is on screen (Spotify's
    // refresh tokens last 6 months), the prompt has to be raised over whatever that
    // view is, and pressing its button must show the progress dialog — which would
    // be invisible if it still lived in a settings screen nobody was looking at.
    // Below the screensaver (z:300): a dashboard that has gone to sleep should stay
    // asleep rather than light up for a prompt that will still be there on waking.
    SpotifyAuthAlert {
        anchors.fill: parent
        z: 250
    }
    SpotifyAuthPopup {
        anchors.fill: parent
        z: 260
    }

    // Idle screensaver: after the inactivity timeout (or F10 for testing) it fades
    // in a black photo pile and dismisses on tap, revealing the last-used view.
    // Sits above every other layer (dock z:default, notifications z:200,
    // Spotify prompt/dialog z:250/260).
    ScreenSaver {
        id: screenSaver
        anchors.fill: parent
        z: 300
        // An update takes minutes with no touch input; without this the photo
        // pile covers it and the panel then goes dark mid-rebuild.
        inhibited: Updater.busy
        nightMode: nightSchedule.screensaverActive
        // Waking to a keyboard still up over a half-typed field is a trap.
        onActiveChanged: if (active) window.dismissKeyboard()
    }

    // --- On-screen keyboard -----------------------------------------------
    // Qt Virtual Keyboard, drawn INSIDE this window: the host's squeekboard does
    // not draw over a fullscreen surface on labwc (labwc#2926), so it would stay
    // hidden behind the dashboard. main.cpp selects the input method; the panel
    // shows itself whenever a text field takes focus. Above every layer but the
    // screensaver, which dismisses it on the way in.
    //
    // Press-outside-to-dismiss. The press is never consumed (accepted = false),
    // so it carries on to whatever is under it: a button still fires, another
    // field still takes focus and reopens the keyboard for itself, and a drag
    // still scrolls — the keyboard just goes first. It stops at the keyboard's
    // top edge so key presses never count as "outside".
    //
    // Not a passive-grab TapHandler, which would dismiss on the tap rather than
    // the press: in Qt 6.11 such a handler still ACCEPTS a mouse press, so every
    // item under it stops receiving presses (QTBUG-145896), and the touch half of
    // that fix is new enough that the Pi's Qt 6.10 may block touches the same way.
    MouseArea {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: keyboard.top
        z: 280
        enabled: keyboard.active

        onPressed: (mouse) => {
            mouse.accepted = false
            // A press in the field being edited only moves its cursor.
            const focused = window.activeFocusItem
            if (focused !== null && focused.contains(mapToItem(focused, mouse.x, mouse.y)))
                return
            window.dismissKeyboard()
        }
    }

    InputPanel {
        id: keyboard
        width: window.width
        x: 0
        y: active ? window.height - height : window.height
        z: 290

        Behavior on y {
            NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
        }
    }

    // "Do not cut the power" — above every view, below the screensaver it is
    // already suppressing. See UpdateBanner.qml for why it is app-level.
    UpdateBanner {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        z: 270
    }

    // The screensaver's inactivity timeout is an Options-view setting, so push it
    // at the IdleWatcher whenever it changes. AppConfig seeds the watcher with the
    // same value at construction (it also honours the env var), so this binding
    // only ever re-applies a user edit — it does not fight the startup value.
    // Inside a night-mode screensaver window the much shorter wake time applies
    // instead; IdleWatcher restarts its countdown on a change, so the panel
    // goes dark that long after the window opens, not at once.
    Binding {
        target: Idle
        property: "timeoutMs"
        value: nightSchedule.screensaverActive
               ? Theme.nightWakeMs
               : Settings.values.screensaverTimeoutMin * 60000
    }

    // Panel power-down: a longer step past the screensaver that cuts the backlight
    // via wlopm, waking on the next touch. Pushed rather than read so the Options
    // view applies it live; ScreenPower starts disarmed, so with the setting off
    // nothing ever runs.
    Binding {
        target: Display
        property: "enabled"
        // Disarmed outright while an update runs: the screensaver is inhibited
        // above for the same reason, and a dark panel over a live rebuild is the
        // shape that gets a device power-cycled mid-checkout.
        // Night mode's "Näyttö pois" arms it too, with the short night wake
        // time, whether or not the daytime power-off is on.
        value: (Settings.values.screenOffEnabled || nightSchedule.screenOffActive)
               && !Updater.busy
    }
    Binding {
        target: Display
        property: "timeoutMs"
        value: nightSchedule.screenOffActive
               ? Theme.nightWakeMs
               : Settings.values.screenOffMin * 60000
    }

    // An update rewrote this binary while the app was running, so the file on
    // disk is no longer the one this process is executing — only a restart picks
    // it up. Routed here rather than inside the Options view for the same reason
    // the Spotify prompt is: a rebuild takes minutes, and the user is free to
    // walk away to the dashboard while it runs. Settings::restartApp() quits with
    // exit code 42 so the service unit relaunches it.
    Connections {
        target: Updater

        function onRestartRequested() {
            Settings.restartApp()
        }
    }

    Component.onCompleted: {
        // Finnish only: the UI is Finnish, the layout carries å/ä/ö as plain
        // keys, and a single locale drops the language-switch key.
        VirtualKeyboardSettings.locale = "fi_FI"
        VirtualKeyboardSettings.activeLocales = ["fi_FI"]
        hideTimer.start()
    }
}

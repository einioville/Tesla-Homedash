import QtQuick
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
        interval: 3000
        repeat: false
        onTriggered: window.hideDock()
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
    }

    // The screensaver's inactivity timeout is an Options-view setting, so push it
    // at the IdleWatcher whenever it changes. AppConfig seeds the watcher with the
    // same value at construction (it also honours the env var), so this binding
    // only ever re-applies a user edit — it does not fight the startup value.
    Binding {
        target: Idle
        property: "timeoutMs"
        value: Settings.values.screensaverTimeoutMin * 60000
    }

    // Panel power-down: a longer step past the screensaver that cuts the backlight
    // via wlopm, waking on the next touch. Pushed rather than read so the Options
    // view applies it live; ScreenPower starts disarmed, so with the setting off
    // nothing ever runs.
    Binding {
        target: Display
        property: "enabled"
        value: Settings.values.screenOffEnabled
    }
    Binding {
        target: Display
        property: "timeoutMs"
        value: Settings.values.screenOffMin * 60000
    }

    Component.onCompleted: hideTimer.start()
}

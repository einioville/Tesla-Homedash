import QtQuick
import frontend_v2

Window {
    id: window
    width: 1280
    height: 800
    // Embedded dashboard: the target is a fixed 1280×800 panel and every card is
    // hand-tuned for exactly that size, so the window is LOCKED — no resizing and
    // no content scaling. min == max == the design size.
    minimumWidth: 1280
    maximumWidth: 1280
    minimumHeight: 800
    maximumHeight: 800
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
        { name: qsTr("Lataus"), icon: "qrc:/resources/icons/power_on.svg", component: chargingComponent }
    ]
    property int currentView: 0

    Component { id: dashboardComponent; DashboardView {} }
    Component { id: mapComponent; MapView {} }
    Component { id: mediaComponent; MediaView {} }
    Component { id: historyComponent; HistoryView {} }
    Component { id: tripsComponent; TripsView {} }
    Component { id: chargingComponent; ChargingView {} }

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

    Component.onCompleted: hideTimer.start()
}

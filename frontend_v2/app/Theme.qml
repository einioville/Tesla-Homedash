pragma Singleton
import QtQuick

QtObject {
    // --- Feature flags ----------------------------------------------------
    // Luna — the dog-memorial overlay on the dashboard. The single on/off switch:
    // set to false to remove her entirely (no sprite, no animation, no cost).
    property bool lunaEnabled: true

    // Screensaver — after TESLA_HOMEDASH_SCREENSAVER_TIMEOUT_MIN minutes of no
    // touch, a black photo slideshow (from TESLA_HOMEDASH_SCREENSAVER_DIR) takes
    // over the screen; any tap dismisses it and returns to the last-used view.
    // The single on/off switch (folder + timeout live in AppConfig / the
    // environment). Press F10 to toggle it on demand for testing.
    property bool screensaverEnabled: true

    // Surfaces
    readonly property color appBackground: "#0f1115"
    readonly property color dockBackground: "#cc1b2230"
    readonly property color dockBorder: "#22ffffff"
    readonly property color accent: "#4aa8ff"
    readonly property color iconPlaceholder: "#000000"
    readonly property color homeIndicator: "#ffffffff"
    readonly property color viewLabel: "#e8edf5"

    // Per-view backgrounds. The dashboard mirrors the Widgets frontend's
    // #121212 base; the others remain placeholder tints.
    readonly property color dashboardBackground: "#121212"
    readonly property color mediaBackground: "#1b2a1f"
    readonly property color mapBackground: "#2a1f2b"
    readonly property color climateBackground: "#241f15"
    readonly property color weatherBackground: "#15232b"
    readonly property color tripBackground: "#121212"

    // Metrics
    readonly property int dockRadius: 28
    readonly property int dockPadding: 16
    readonly property int dockSpacing: 16
    readonly property int iconSize: 64
    readonly property int iconRadius: 14

    // Motion (ms)
    readonly property int dockDuration: 260
    readonly property int pressDuration: 90

    // --- Dashboard (Widgets-frontend parity) -----------------------------
    readonly property string fontFamily: "Gotham Rounded Medium"

    // Padding the window reserves around the dashboard cards (the grid margin).
    // Shared so the home indicator + dock can be placed relative to that edge.
    readonly property int gridMargin: 10

    // Card shell: rounded corners, the dark-blue→black radial gradient and the
    // soft drop shadow shared by the data lists, climate and weather panels.
    readonly property int cardRadius: 5
    readonly property color cardGradientInner: "#03002e"    // rgb(3, 0, 46)
    readonly property color cardGradientOuter: "#000000"
    readonly property color cardShadowColor: "#96000000"    // rgba(0, 0, 0, 150)

    // Tesla data-entry labels.
    readonly property color dataLabelBg: "#5c5c5c"
    readonly property color dataLabelTitle: "#c0c0c0"
    readonly property color dataLabelValue: "#ffffff"
    readonly property color separator: "#ffffff"

    // Weather cards: translucent grey panel with a faint white border.
    readonly property color weatherCardBg: "#325c5c5c"      // rgba(92, 92, 92, 50)
    readonly property color weatherCardBorder: "#78ffffff"  // rgba(255, 255, 255, 120)

    // Media card.
    readonly property color mediaFallbackColor: "#1e3a8a"
    readonly property color sliderGroove: "#66333333"       // rgba(51, 51, 51, 102)
    readonly property color sliderFill: "#ffffff"

    // Climate glows / icon tints.
    readonly property color glowOff: "#ff0000"
    readonly property color glowOn: "#00ff00"
    readonly property color glowPending: "#ffff00"
    readonly property color glowMinus: "#0000ff"
    readonly property color glowPlus: "#ff0000"
    readonly property color seatHeat: "#ff0000"
    readonly property color seatCool: "#0000ff"
    readonly property color iconTint: "#ffffff"

    // "Liquid glass" surface — shared by the notification pill and the dock
    // (via items/util/GlassPanel.qml): squarer corners, a bright white rim and a
    // DARK translucent tint (so white text/icons read clearly) over a frosted
    // backdrop, plus a specular highlight line and a soft drop shadow.
    readonly property int notificationRadius: 12
    readonly property color notificationGlassTop: "#4d1a1a24"     // dark translucent sheen (top)
    readonly property color notificationGlassBottom: "#66121218"  // darker translucent base
    readonly property color notificationBorder: "#ccffffff"       // bright white rim
    readonly property color notificationHighlight: "#80ffffff"    // inner specular line
    readonly property color notificationShadow: "#66000000"
    readonly property color notificationText: "#ffffff"
    // Tone applied to the blurred backdrop so it reads as dark glass.
    readonly property real notificationFrostBrightness: -0.2
    readonly property real notificationFrostSaturation: -0.1

    // --- Trips view -------------------------------------------------------
    // Speed at which the route line reaches the top of the colour ramp (red).
    // The gradient runs dark green (0 km/h) → red / dark red (this value); speeds
    // above it clamp to the top colour. TripMap.colorForSpeed reads this.
    readonly property real tripMaxSpeedKmh: 150
    // Coloured route line width (px) and its dark casing underneath (for legibility
    // over satellite imagery / bright tiles).
    readonly property real tripRouteWidth: 4
    readonly property color tripRouteCasing: "#cc000000"
    // Floating control bar (week + trip dropdowns) over the map: dark translucent
    // pill with a faint white rim, matching the dashboard card family.
    readonly property color tripControlBar: "#cc1b2230"
    readonly property color tripControlBarBorder: "#33ffffff"
    // Dark-themed ComboBox (week/trip selectors) so the dropdown never flashes the
    // Basic style's light popup/hover square over the map. Neutral dark grey so the
    // dropdowns match the translucent-grey card family (tripCardBg) rather than
    // clashing as blue; the hover highlight is the card grey (NOT white).
    readonly property color tripComboBg: "#662c2c2c"
    readonly property color tripComboPressed: "#992c2c2c"
    readonly property color tripComboPopupBg: "#f2242424"
    // Opaque non-hover row background (the popup bg sans alpha). Kept opaque so a hover
    // only recolours the row's node instead of adding/removing one — the node churn is
    // what triggered the white-map-tile re-batch artifact (issue #9).
    readonly property color tripComboRowBg: "#242424"
    readonly property color tripComboHover: "#5c5c5c"
    // Start/end route markers: a map-red so they read as pins, distinct from the
    // green→red speed gradient of the route line (the pin shape disambiguates).
    readonly property color tripMarkerColor: "#ff3b30"

    // Minimalistic detail cards (the stat tiles, the selector box and the map/graph
    // frames): a translucent grey fill with a whiteish border and softer corners than
    // the dashboard's dark-gradient cards.
    readonly property color tripCardBg: "#325c5c5c"      // rgba(92, 92, 92, 50)
    readonly property color tripCardBorder: "#78ffffff"  // rgba(255, 255, 255, 120)
    readonly property int tripCardRadius: 12

    // --- Screensaver ------------------------------------------------------
    // Printed-photo pile on a black background: each photo sits in a white frame
    // with a soft drop shadow, tossed on at a random tilt/offset (newest on top).
    readonly property color screensaverBackground: "#000000"
    readonly property color screensaverFrameColor: "#ffffff"
    readonly property real screensaverSizeFraction: 0.75   // max photo box vs. window
    readonly property int screensaverMatte: 14             // white frame thickness (px)
    readonly property int screensaverCornerRadius: 2
    readonly property real screensaverTiltMaxDeg: 7        // random ± tilt per photo
    readonly property int screensaverScatterPx: 60         // random pile offset radius
    readonly property int screensaverStackCount: 10        // photos kept on the pile
    readonly property int screensaverAdvanceMs: 8000       // per-photo dwell
    readonly property int screensaverEnterMs: 650          // toss-in animation
    readonly property int screensaverFadeMs: 500           // fade in/out (photos + overlay)
}

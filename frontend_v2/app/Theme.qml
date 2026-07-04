pragma Singleton
import QtQuick

QtObject {
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
    // Basic style's light popup/hover square over the map. Field + popup are dark;
    // the hover highlight is a muted blue-grey (NOT white).
    readonly property color tripComboBg: "#66222a3a"
    readonly property color tripComboPressed: "#99222a3a"
    readonly property color tripComboPopupBg: "#f21b2230"
    readonly property color tripComboHover: "#55617a"
    // Start/end route markers: a map-red so they read as pins, distinct from the
    // green→red speed gradient of the route line (the pin shape disambiguates).
    readonly property color tripMarkerColor: "#ff3b30"
}

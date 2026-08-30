pragma Singleton
import QtQuick
import frontend_v2

// Design tokens for the dashboard.
//
// Two kinds of value live here, and the distinction matters:
//
//  - CONSTANTS (the vast majority): colours, radii, motion durations, the font.
//    Plain `readonly property` literals. They are the app's visual identity, not
//    user options, and qmlcachegen AOT-compiles them into the binary — which is
//    exactly what you want for values on binding hot paths.
//
//  - USER-TUNABLE tokens: bound to `Settings.values.<key>` instead of a literal.
//    A property initialiser is a BINDING, so when the Options view writes the
//    setting the token re-evaluates and every `Theme.x` call site updates live —
//    no call-site churn, and the 200+ existing references keep working unchanged.
//    Add one by adding a schema entry in config/settings.json and a binding here.
QtObject {
    // --- Feature flags ----------------------------------------------------
    // Luna — the dog-memorial overlay on the dashboard. Toggled from the Options
    // view (Yleinen > Lisäasetukset), off by default. She is gated by `visible`/`running`
    // rather than a Loader, so she is constructed either way; flipping this only
    // stops her painting and animating.
    readonly property bool lunaEnabled: Settings.values.lunaEnabled

    // Screensaver — after the configured idle timeout a black photo slideshow
    // takes over the screen; any tap dismisses it and returns to the last-used
    // view. On/off, timeout, dwell, pile size and the photo folder are all
    // Options-view settings; the folder still DEFAULTS to
    // TESLA_HOMEDASH_SCREENSAVER_DIR, so an existing deployment keeps working
    // until it is changed on-device. With no folder there are no photos and the
    // screensaver never activates.
    // Press F10 to toggle it on demand for testing.
    readonly property bool screensaverEnabled: Settings.values.screensaverEnabled
    // Plain filesystem path; Settings.toFileUrl() turns it into a URL for QML.
    readonly property string screensaverDir: Settings.values.screensaverDir

    // Panel power-down — a step BEYOND the screensaver: the screensaver keeps the
    // backlight on to show photos, this cuts it. Main.qml pushes both at the C++
    // ScreenPower (`Display`), which shells out to wlopm.
    readonly property bool screenOffEnabled: Settings.values.screenOffEnabled
    readonly property int screenOffMin: Settings.values.screenOffMin

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
    // Opacity of a settings row that a toggle has made irrelevant. Faded, never
    // disabled — the value stays editable so you can set it BEFORE turning the
    // feature on.
    readonly property real settingIrrelevantOpacity: 0.45

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
    // above it clamp to the top colour. TripMap.colorForSpeed reads this. Not a
    // user setting: it is a colour-scale endpoint, not a preference.
    readonly property real tripMaxSpeedKmh: 150.0
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
    readonly property int screensaverStackCount: Settings.values.screensaverStackCount
    readonly property int screensaverAdvanceMs: Settings.values.screensaverAdvanceSec * 1000
    readonly property int screensaverEnterMs: 650          // toss-in animation
    readonly property int screensaverFadeMs: 500           // fade in/out (photos + overlay)

    // --- History / Trip graph tuning --------------------------------------
    // Viewport-decimation and zoom-debounce knobs shared by every HistoryGraph
    // instance (History, Trips and Charging all reuse it). Exposed in the Options
    // view because the right values depend on the target hardware: the Pi wants a
    // lower point cap and a longer settle than a desktop does.
    // Cap on how many points a graph draws at once. The setting's TOP stop means
    // no cap, so this sentinel must equal the schema's max for graphMaxPoints.
    readonly property int graphMaxPointsUnlimited: 5000
    readonly property int graphMaxPoints: Settings.values.graphMaxPoints
    // Multiplier on pan/zoom response — the 10" panel wants more than a desktop.
    readonly property real graphSensitivity: Settings.values.graphSensitivity
    readonly property int graphSettleMs: Settings.values.graphSettleMs
    readonly property real graphRenderMarginFrac: Settings.values.graphRenderMarginFrac
    // Tightest zoom window. Fixed: a minute is short enough for any range the
    // History view loads, and nothing is gained by exposing it.
    readonly property int graphMinZoomSpanMs: 60000
}

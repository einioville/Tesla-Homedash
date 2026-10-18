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
//    setting the token re-evaluates and every `Theme.x` call site updates live
//    with no change at the call site.
//    Add one by adding a schema entry in config/settings.json and a binding here.
QtObject {
    // --- Feature flags ----------------------------------------------------
    // Luna — the dog-memorial overlay on the dashboard. Toggled from the Options
    // view (Yleinen > Luna), off by default. She is gated by `visible`/`running`
    // rather than a Loader, so she is constructed either way; flipping this only
    // stops her painting and animating.
    readonly property bool lunaEnabled: Settings.values.lunaEnabled

    // Screensaver — after the configured idle timeout a black photo slideshow
    // takes over the screen; any tap dismisses it and returns to the last-used
    // view. On/off, timeout, dwell and pile size are Options-view settings; the
    // photos come from a fixed folder (the Photos singleton), and with none there
    // the screensaver never activates.
    // Press F10 to toggle it on demand for testing.
    readonly property bool screensaverEnabled: Settings.values.screensaverEnabled

    // Night mode (Yleinen > Yötila) — between two clock times the screensaver
    // is set aside and the panel powers off after a much shorter idle than by
    // day. items/util/NightSchedule.qml decides when; Main.qml routes it into
    // the Display machinery.
    readonly property bool nightModeEnabled: Settings.values.nightModeEnabled
    // Minutes since local midnight. start === end means no window at all.
    readonly property int nightStartMin: Settings.values.nightStartMin
    readonly property int nightEndMin: Settings.values.nightEndMin
    // How long a touch keeps the panel awake inside the window.
    readonly property int nightWakeMs: Settings.values.nightWakeMin * 60000

    // Navigation (Yleinen > Navigointi). With home return on, an idle panel
    // switches back to the dashboard — so the screensaver lifts onto it rather
    // than onto whichever view was last open.
    readonly property bool homeReturnEnabled: Settings.values.homeReturnEnabled
    readonly property int homeReturnMs: Settings.values.homeReturnMin * 60000
    // How long the view menu waits, left still, before opening the front view.
    readonly property int menuAutoPickMs: Settings.values.menuAutoPickSec * 1000

    // How long each notification pill is held. Not a setting: notification
    // settings belong to a notifications section of their own (#51).
    readonly property int notificationDurationMs: 5000

    // Surfaces
    readonly property color appBackground: "#0f1115"
    readonly property color accent: "#4aa8ff"
    readonly property color homeIndicator: "#ffffffff"
    readonly property color viewLabel: "#e8edf5"

    // Per-view backgrounds; the dashboard mirrors the Widgets frontend's #121212 base.
    readonly property color dashboardBackground: "#121212"
    readonly property color tripBackground: "#121212"
    readonly property color mediaBackground: "#121212"
    // The backdrop of the dashboard and the Media view (items/media/MediaBackdrop.qml):
    // the cover's colours as drifting light, at most backdropStrength alpha at a
    // glow's centre behind the dashboard's cards, mediaBackdropStrength on the Media
    // view, where nothing lies over it.
    // A pause dims it to backdropPausedGlow of that and slows the drift to a stop,
    // both over backdropSettleDuration; a new cover's colours fade in over
    // backdropFadeDuration.
    readonly property real backdropStrength: 0.4
    readonly property real mediaBackdropStrength: 0.75
    readonly property real backdropPausedGlow: 0.55
    readonly property int backdropSettleDuration: 4000
    readonly property int backdropFadeDuration: 2000
    // The Media view's spectrum line (items/media/MediaSpectrum.qml): each band
    // rises this share of the way to a new level per frame, and falls back at
    // most spectrumFall (of the full height) a second.
    readonly property real spectrumRise: 0.6
    readonly property real spectrumFall: 1.2
    // "bars" or "line" (Asetukset › Media › Spektri).
    readonly property string mediaSpectrumStyle: Settings.values.mediaSpectrumStyle

    // Motion (ms)
    readonly property int pressDuration: 90
    // ToggleSwitch: the knob's leading edge reaches the far end first, then its
    // tail follows and it is a circle again.
    readonly property int switchStretchDuration: 110
    readonly property int switchSettleDuration: 140
    // Reveal: content slides out from under the item above it while set back,
    // then comes forward to level; each following item starts a stagger later.
    readonly property int revealSlideDuration: 150
    readonly property int revealLiftDuration: 110
    readonly property int revealStagger: 45
    readonly property int concealDuration: 120
    readonly property real revealSetBackScale: 0.94
    readonly property real revealSetBackOpacity: 0.45
    // ElasticFlickable: how long content dragged or flicked past an end takes to
    // come back.
    readonly property int reboundDuration: 320
    // View switch (ViewController): the view backs away until its neighbours
    // show, the carousel turns (viewTurnDuration for one step, 40 % of it for
    // each step more), the new view comes forward. Each phase starts
    // viewPhaseOverlap before the one before it ends.
    readonly property int viewBackDuration: 150
    readonly property int viewTurnDuration: 260
    readonly property int viewForwardDuration: 190
    readonly property int viewPhaseOverlap: 70
    // Opacity of a settings row whose `relevantWhen` fails for a reason other
    // than the setting it is nested under (that one hides it) — the row is
    // disabled too.
    readonly property real settingIrrelevantOpacity: 0.45
    // A settings row that depends on a setting above it in the same card is
    // nested under it: indented this much per level, beside a thin rail.
    readonly property int settingChildIndent: 24
    readonly property color settingChildRail: "#38ffffff"

    // --- Dashboard (Widgets-frontend parity) -----------------------------
    readonly property string fontFamily: "Gotham Rounded Medium"

    // Padding the window reserves around the dashboard cards (the grid margin).
    // Shared so the home indicator can be placed relative to that edge.
    readonly property int gridMargin: 10

    // Card shell (items/util/Card.qml) — the dashboard's panels and the Weather
    // view's: a faint translucent fill and a hairline rim over the view's dark
    // background. The map and the media card take the same corners.
    readonly property int cardRadius: 14
    readonly property color cardFill: "#12ffffff"
    readonly property color cardBorder: "#24ffffff"
    readonly property color cardTitle: "#8f9aa6"
    readonly property color cardNote: "#6f7a86"
    // Rule between the rows stacked in a card.
    readonly property color cardDivider: "#24ffffff"
    // The media card's drop shadow; it alone keeps one, under its cover-coloured fill.
    readonly property color cardShadowColor: "#96000000"    // rgba(0, 0, 0, 150)
    // Album-art corners on the media card: a step under cardRadius, so the cover
    // reads as part of the card. The Media view scales its bigger cover's up from this.
    readonly property int coverRadius: 10

    // Tesla data-entry labels.
    readonly property color dataLabelTitle: "#c0c0c0"
    readonly property color dataLabelValue: "#ffffff"

    // --- Spotify -----------------------------------------------------------
    // Spotify's own surface and text ramp. spotifySurface / spotifyRim are the
    // default card of every dialog (items/settings/ModalDialog.qml) and
    // spotifySubdued is the secondary copy in the device-identification and USB
    // import dialogs. The green, the outline and the base are the
    // device-identification dialog's alone, so it says whose device it is asking
    // about without spelling it out again. These are their published tokens:
    // --background-elevated-base is what their own modals sit on, --text-subdued
    // is their secondary copy, and #727272 is the outline their secondary
    // buttons carry.
    readonly property color spotifyGreen: "#1db954"
    readonly property color spotifySurface: "#242424"   // --background-elevated-base
    readonly property color spotifyBase: "#121212"      // --background-base
    readonly property color spotifySubdued: "#b3b3b3"   // --text-subdued
    readonly property color spotifyOutline: "#727272"   // secondary button border
    readonly property color spotifyRim: "#3a3a3a"       // hairline around a surface

    // Media card.
    readonly property color sliderGroove: "#66333333"       // rgba(51, 51, 51, 102)
    readonly property color sliderFill: "#ffffff"

    // Climate glows / icon tints. The HVAC button's disc and glow per state, and
    // the wave a switch sends across the dashboard's background
    // (items/tesla/ClimateStarter.qml, ClimateWave.qml): out past the farthest corner
    // over hvacWaveOutDuration, and again from the button each time, until the car
    // answers. The answer's colour comes in over hvacColorDuration, the water fades over
    // hvacWaterFade and the background back to the cover's over hvacWavePaintFade.
    // The pushes move simulated water (hvacWater*: a cell per hvacWaterCell px, pushed
    // hvacWaterPush a step over a ring hvacWaterRingWidth px across that wanders up to
    // hvacWaveWobble px out of round; each step keeps hvacWaterDamping of the water's
    // speed). A height step of 1 between cells reads as a slope of hvacWaterSlopeGain,
    // and a slope of 1 bends the backdrop seen through it by hvacWaveRefraction px. The
    // backdrop's light behind the front fades into the wave's colour over hvacWaveTail
    // px, pending yellow hvacWavePendingGain times as strong as the cover's (dim yellow
    // reads as olive); red and green, as strong.
    readonly property color hvacDiscOff: "#ff5555"
    readonly property color hvacDiscPending: "#ffd42a"
    readonly property color hvacDiscOn: "#00ff00"
    readonly property color glowOff: "#ff0000"
    readonly property color glowOn: "#00ff00"
    readonly property color glowPending: "#ffff00"
    readonly property int hvacColorDuration: 450
    readonly property int hvacWaveOutDuration: 4500
    readonly property real hvacWaveTail: 300
    readonly property real hvacWaveRefraction: 24
    readonly property real hvacWaveWobble: 16
    readonly property real hvacWaterCell: 10
    readonly property real hvacWaterPush: 0.1
    readonly property real hvacWaterRingWidth: 40
    readonly property real hvacWaterDamping: 0.985
    readonly property real hvacWaterSlopeGain: 14
    readonly property int hvacWaterFade: 2500
    readonly property int hvacWavePaintFade: 2500
    readonly property real hvacWavePendingGain: 1.6
    readonly property color glowMinus: "#0000ff"
    readonly property color glowPlus: "#ff0000"
    readonly property color seatHeat: "#ff0000"
    readonly property color iconTint: "#ffffff"

    // "Liquid glass" surface — shared by the notification pill and the graph
    // readout (via items/util/GlassPanel.qml): squarer corners, a bright
    // white rim and a DARK translucent tint (so white text/icons read clearly)
    // over a frosted backdrop, plus a specular highlight line and a soft drop
    // shadow.
    readonly property int notificationRadius: 12
    readonly property int notificationPadding: 16
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
    // only recolours the row's node instead of adding/removing one — the node churn
    // triggers the white-map-tile re-batch artifact (issue #9).
    readonly property color tripComboRowBg: "#242424"
    readonly property color tripComboHover: "#5c5c5c"
    // Start/end route markers: a map-red so they read as pins, distinct from the
    // green→red speed gradient of the route line (the pin shape disambiguates).
    readonly property color tripMarkerColor: "#ff3b30"

    // --- Kartta view -----------------------------------------------------
    // The drive under way, drawn on the map behind the car (TeslaMap's route layer).
    readonly property color mapDriveRoute: "#4aa8ff"
    readonly property real mapDriveRouteWidth: 5

    // Minimalistic detail cards (the stat tiles, the selector box and the map/graph
    // frames): a translucent grey fill with a whiteish border and softer corners than
    // the dashboard's dark-gradient cards.
    readonly property color tripCardBg: "#325c5c5c"      // rgba(92, 92, 92, 50)
    readonly property color tripCardBorder: "#78ffffff"  // rgba(255, 255, 255, 120)
    readonly property int tripCardRadius: 12

    // Scrim behind a modal. Lighter than a plain blackout because the blur does
    // most of the separating; at 0xcc the frosted backdrop is invisible and the
    // effect pure cost.
    readonly property color dialogScrim: "#99000000"

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
    // instance (History, Trips, Charging and Järjestelmän tila all reuse it).
    // Exposed in the Options view because the right values depend on the target
    // hardware: the Pi wants a coarser density and a longer settle than a desktop
    // does.
    // Render density, in M4 buckets per pixel of the VISIBLE plot (each bucket keeps
    // up to four points). The Options view names levels and keeps these numbers
    // internal: "high" is one bucket per pixel, where M4 reproduces the line
    // pixel-exactly, and "max" (0) turns decimation off altogether.
    readonly property real graphBucketsPerPx:
        ({ low: 0.25, medium: 0.5, high: 1, xhigh: 2, max: 0 })[Settings.values.graphResolution] ?? 0.5
    // Multiplier on pan/zoom response — the 10" panel wants more than a desktop.
    // "normal" (1.0) is finger-exact: a drag moves the content 1:1 and a pinch
    // scales it by exactly the pinch. The top reaches 4 because 3.0 felt slow on the
    // Pi's panel (measured while it scaled only the pinch zoom, not the pan). ONE
    // table for the graph and the map (mapSensitivity), so the same level name feels
    // the same on both.
    readonly property var gestureSensitivityLevels: ({ low: 0.75, normal: 1, high: 1.5, xhigh: 2.5, max: 4 })
    readonly property real graphSensitivity:
        gestureSensitivityLevels[Settings.values.graphGestureSensitivity] ?? 1
    // Settle debounce before the detailed rebuild, also a named level. "instant" is
    // a 0 ms Timer: it still fires asynchronously, once per event-loop pass, so the
    // several setView() calls one pinch frame makes coalesce into a single rebuild.
    readonly property int graphSettleMs:
        ({ slow: 1000, normal: 500, quick: 200, instant: 0 })[Settings.values.graphSettleDelay] ?? 500
    // How far past the visible window each side is pre-built, as a fraction of the
    // visible span. Not free: the density is per visible pixel, so the points built
    // grow with it — "xlarge" (2.0) builds five screens' worth.
    readonly property real graphRenderMarginFrac:
        ({ small: 0.25, normal: 0.5, large: 1, xlarge: 2 })[Settings.values.graphRenderMargin] ?? 0.5
    // Tightest zoom window. Fixed: a minute is short enough for any range the
    // History view loads, and nothing is gained by exposing it.
    readonly property int graphMinZoomSpanMs: 60000

    // --- Map tuning -------------------------------------------------------
    // Drives TeslaMap (the dashboard card and the full-screen Kartta view);
    // mapSensitivity alone also reaches the Trips route map, which carries the
    // same pan/pinch/wheel handlers.
    // Zoom the map returns to when auto-follow resumes after a gesture.
    readonly property real mapDefaultZoom: Settings.values.mapDefaultZoom
    // Multiplier on pan/pinch/wheel response, the same levels as graphSensitivity.
    // At "normal" (1.0) a drag is EXACT 1:1 — the grabbed point stays under the
    // finger — so any other level deliberately trades that away for reach.
    readonly property real mapSensitivity:
        gestureSensitivityLevels[Settings.values.mapGestureSensitivity] ?? 1
    // Idle delay after the user stops moving the map before it snaps back to
    // the car. A map has no re-render step to debounce (QtLocation streams and
    // repaints tiles itself), so this is the only timeout the map really has.
    readonly property int mapFollowResumeSec: Settings.values.mapFollowResumeSec
    // "north" keeps north up and rotates the car icon; "heading" rotates the
    // MAP under a car icon that then always points up the screen.
    readonly property string mapOrientation: Settings.values.mapOrientation
    // "lock" pins the car to the exact centre; "warp" lets it roam inside a
    // centred dead-zone square and re-centres only when it escapes.
    readonly property string mapFollowMode: Settings.values.mapFollowMode
    // Dead-zone half-extent — the distance from the centre the car may reach on
    // either axis — as a fraction of the map's SHORTER side, so the free area is
    // square on any card. Warp mode only. A named level, like the lead below.
    readonly property real mapWarpDeadzoneFrac:
        ({ xsmall: 0.05, small: 0.15, normal: 0.25, large: 0.35, xlarge: 0.45 })[Settings.values.mapWarpDeadzone] ?? 0.25
    // How far behind centre the car is parked on a re-centre, opposite its
    // direction of travel, so the road ahead gets the larger share of the map.
    // Same fraction-of-shorter-side units as the dead zone. Warp mode only.
    // TeslaMap clamps it below 0.8 × the dead zone, so a large lead inside a
    // small free area quietly shrinks (items/tesla/CLAUDE.md).
    readonly property real mapWarpLeadFrac:
        ({ none: 0, small: 0.06, normal: 0.12, large: 0.2, xlarge: 0.3 })[Settings.values.mapWarpLead] ?? 0.12
}

import QtQuick
import QtQuick.Shapes
import frontend_v2

// A backdrop of the cover's colours (Media.palette) as soft light drifting slowly
// behind a view — the dashboard's cards and the Media view. It follows the music:
// a new cover's colours fade in, and on a pause the drift slows to a stop and the
// light dims, coming back with the playback. Where the light lies is the view's
// to say (`glows`), since it depends on what covers the backdrop there.
//
// Load-bearing:
//  - The drift steps on a Timer, never an Animation. While any Animation runs, Qt
//    Quick redraws the window on every frame, the map and every card with it; a
//    Timer redraws it only when a step changes something. Measured on Qt 6.11: an
//    item moved every 50 ms by a Timer, 20 frames a second; by a NumberAnimation,
//    60. The light has no edges and moves a few px a second, so the steps do not
//    show. The pause's slow-down and dimming are stepped by the same Timer for the
//    same reason; only a new cover's colours animate, once per track.
//  - A glow moves as a whole item with its gradient fixed inside it, so a step is
//    a transform, not a new gradient.
//  - Still off screen, under the screensaver (the view host is hidden) and with
//    the panel off; paused and settled, the Timer stops as well.
Item {
    id: backdrop

    // The owning view's isCurrent.
    property bool active: true
    // One entry per pool of light, in this item's px: { tone: palette index,
    // radius, home: point, reach: point, periods: vector3d (s), phase } (see Glow).
    property var glows: []
    // A glow's alpha at its centre, before a pause dims it.
    property real strength: Theme.backdropStrength

    readonly property int tickMs: 50
    readonly property bool live: active && visible && !Display.off
    readonly property real paceTarget: Media.isPlaying ? 1 : 0
    readonly property real glowTarget: Media.isPlaying ? 1 : Theme.backdropPausedGlow

    // Seconds of drift so far; it advances at `pace` (0–1) and the glows' light is
    // at `glow` of full. Both step toward their targets over backdropSettleDuration.
    property real clock: 0
    property real pace: 0
    property real glow: 1

    // The palette's colour i. A cover with fewer distinct colours fills the rest
    // with deeper shades of its own, a little round the hue, rather than a colour
    // that is not in the art.
    function tone(i) {
        var p = Media.palette
        if (i < p.length)
            return p[i]
        var base = p.length > 0 ? p[p.length - 1] : Media.dominantColor
        return shade(base, i % 2 ? 0.03 : -0.03, 0.7)
    }
    function shade(c, dHue, valueScale) {
        var h = c.hsvHue < 0 ? 0 : (c.hsvHue + dHue + 1) % 1
        return Qt.hsva(h, c.hsvSaturation, c.hsvValue * valueScale, 1)
    }
    function toward(value, target, maxStep) {
        return value < target ? Math.min(target, value + maxStep)
                              : Math.max(target, value - maxStep)
    }

    onLiveChanged: if (live) settle()
    Component.onCompleted: settle()

    // Coming into sight, the backdrop is as the music already is.
    function settle() {
        pace = paceTarget
        glow = glowTarget
    }

    clip: true

    Timer {
        interval: backdrop.tickMs
        repeat: true
        running: backdrop.live && (backdrop.paceTarget > 0 || backdrop.pace > 0
                                   || backdrop.glow !== backdrop.glowTarget)
        property double last: 0
        onRunningChanged: last = Date.now()
        onTriggered: {
            var now = Date.now()
            // A late tick (a busy frame) catches up, but never by more than a moment.
            var dt = Math.min(0.25, (now - last) / 1000)
            last = now
            var step = dt * 1000 / Theme.backdropSettleDuration
            backdrop.pace = backdrop.toward(backdrop.pace, backdrop.paceTarget, step)
            backdrop.glow = backdrop.toward(backdrop.glow, backdrop.glowTarget,
                                            step * (1 - Theme.backdropPausedGlow))
            // Eased, so the drift sets off and comes to rest gently.
            var p = backdrop.pace
            backdrop.clock += dt * p * p * (3 - 2 * p)
        }
    }

    // A round, soft-edged pool of light about `home` that swings across `reach`
    // (one swing each `periods.x` / `.y` seconds) and breathes in size (`.z`).
    // The light falls off on a Gaussian, so it has no edge to see.
    component Glow: Shape {
        id: g

        property color tone
        property real radius: 500
        property point home
        property point reach
        property vector3d periods
        property real phase: 0
        property real clock: 0
        property real strength: 1
        property bool animated: true

        function wave(period, shift) {
            return Math.sin(2 * Math.PI * clock / period + shift)
        }
        function tint(alpha) {
            return Qt.rgba(tone.r, tone.g, tone.b, alpha * strength)
        }

        width: 2 * radius
        height: 2 * radius
        x: home.x - radius + reach.x * wave(periods.x, phase)
        y: home.y - radius + reach.y * wave(periods.y, 2 * phase)
        scale: 1 + 0.1 * wave(periods.z, 3 * phase)

        Behavior on tone {
            enabled: g.animated
            ColorAnimation { duration: Theme.backdropFadeDuration; easing.type: Easing.InOutSine }
        }

        ShapePath {
            strokeWidth: 0
            strokeColor: "transparent"
            // To the light's own colour at zero alpha, not "transparent" (black),
            // which would ring it with a dark edge.
            fillGradient: RadialGradient {
                centerX: g.radius
                centerY: g.radius
                centerRadius: g.radius
                focalX: g.radius
                focalY: g.radius
                focalRadius: 0
                GradientStop { position: 0.0; color: g.tint(1) }
                GradientStop { position: 0.2; color: g.tint(0.83) }
                GradientStop { position: 0.4; color: g.tint(0.48) }
                GradientStop { position: 0.6; color: g.tint(0.19) }
                GradientStop { position: 0.8; color: g.tint(0.05) }
                GradientStop { position: 1.0; color: g.tint(0) }
            }
            PathRectangle {
                width: g.width
                height: g.height
            }
        }
    }

    Repeater {
        model: backdrop.glows
        delegate: Glow {
            required property var modelData
            tone: backdrop.tone(modelData.tone)
            radius: modelData.radius
            home: modelData.home
            reach: modelData.reach
            periods: modelData.periods
            phase: modelData.phase
            clock: backdrop.clock
            strength: backdrop.strength
            opacity: backdrop.glow
            animated: backdrop.live
        }
    }
}

import QtQuick
import QtQuick.Shapes
import frontend_v2

// The Media view's spectrum: what is playing, along the bottom edge in the
// cover's colour — a row of pills that grow from dots (`bars`, the default), or
// one smooth line with a soft fill under it (`line`), Theme.mediaSpectrumStyle.
// The levels are the backend's (Media.spectrum, from a recording of the host's
// output — backend/src/audio_service/spectrum.py); here each band rises most of
// the way to a new level at once and falls back at most spectrumFall a second, so
// the bass swells and settles instead of flickering. Watched only while live,
// which is the only time the backend records.
//
// Load-bearing:
//  - Redrawn per frame the backend sends (about 30 a second), never by an
//    Animation, so the drawing stops when the sound does (frontend_v2/CLAUDE.md,
//    *Motion that keeps running*). Only the fade on play and pause animates.
//  - The line is one SVG path through the levels (Catmull-Rom, as cubics) for
//    the fill, the line and its glow. Its closing edge runs outside the item, so the
//    stroke draws the curve alone.
//  - The Shape is not asynchronous. Measured: fed 30 paths a second, an
//    asynchronous one kept the window drawing every frame (59 fps, against 34
//    with the backdrop's steps).
Item {
    id: spectrum

    // The owning view's isCurrent.
    property bool active: true
    readonly property bool live: active && visible && !Display.off

    property string style: Theme.mediaSpectrumStyle
    // The levels as they move (0-1), as drawn (averaged with their neighbours),
    // and the line's path through them.
    property var shown: []
    property var drawn: []
    property string path: ""
    property double lastMs: 0

    property color tone: Media.dominantColor
    Behavior on tone {
        enabled: spectrum.live
        ColorAnimation { duration: Theme.backdropFadeDuration; easing.type: Easing.InOutSine }
    }
    // Lighter than the backdrop's light of the same colour, so the line stands
    // out of it.
    function light(saturation, alpha) {
        var h = tone.hsvHue < 0 ? 0 : tone.hsvHue
        return Qt.hsva(h, tone.hsvSaturation * saturation, 1, alpha)
    }

    opacity: Media.isPlaying ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 600; easing.type: Easing.InOutSine } }

    Binding {
        target: Media
        property: "spectrumWatched"
        value: spectrum.live
    }

    Connections {
        target: Media
        function onSpectrumChanged() { spectrum.step(Media.spectrum) }
    }

    function step(raw) {
        var now = Date.now()
        var fall = Theme.spectrumFall * Math.min(0.1, (now - lastMs) / 1000)
        lastMs = now
        var next = []
        for (var i = 0; i < raw.length; i++) {
            var was = i < shown.length ? shown[i] : 0
            var level = raw[i]
            next.push(level > was ? was + (level - was) * Theme.spectrumRise
                                  : Math.max(level, was - fall))
        }
        shown = next
        drawn = blur(next)
        path = style === "line" ? curve(drawn) : ""
    }

    // Each level averaged with its neighbours (1-2-1), so the line flows through
    // the bands instead of zig-zagging between them.
    function blur(levels) {
        var n = levels.length
        var kernel = [1, 2, 1]
        var out = []
        for (var i = 0; i < n; i++) {
            var sum = 0
            var weight = 0
            for (var k = -1; k <= 1; k++) {
                if (i + k >= 0 && i + k < n) {
                    sum += levels[i + k] * kernel[k + 1]
                    weight += kernel[k + 1]
                }
            }
            out.push(sum / weight)
        }
        return out
    }

    function curve(levels) {
        var n = levels.length
        if (n < 2)
            return ""
        var w = width
        var h = height
        // At rest the line lies just above the bottom edge.
        var rest = h - 3
        function x(i) { return i / (n - 1) * w }
        function y(i) { return rest - levels[Math.max(0, Math.min(n - 1, i))] * rest }
        function f(v) { return v.toFixed(1) }
        var d = "M " + f(x(0)) + " " + f(y(0))
        for (var i = 0; i < n - 1; i++) {
            d += " C " + f(x(i) + (x(i + 1) - x(Math.max(0, i - 1))) / 6)
               + " " + f(y(i) + (y(i + 1) - y(i - 1)) / 6)
               + " " + f(x(i + 1) - (x(Math.min(n - 1, i + 2)) - x(i)) / 6)
               + " " + f(y(i + 1) - (y(i + 2) - y(i)) / 6)
               + " " + f(x(i + 1)) + " " + f(y(i + 1))
        }
        // Closed outside the item: right, under the bottom edge, and back up the left.
        var out = 24
        d += " L " + f(w + out) + " " + f(y(n - 1)) + " L " + f(w + out) + " " + f(h + out)
           + " L " + f(-out) + " " + f(h + out) + " L " + f(-out) + " " + f(y(0)) + " Z"
        return d
    }

    // The bars: pills standing just above the bottom edge, half a slot wide, a
    // dot at rest.
    Item {
        anchors.fill: parent
        visible: spectrum.style === "bars"

        Repeater {
            model: spectrum.drawn.length

            Rectangle {
                required property int index
                readonly property real slot: spectrum.width / spectrum.drawn.length
                readonly property real base: spectrum.height - 12

                width: Math.round(slot / 2)
                radius: width / 2
                x: index * slot + (slot - width) / 2
                height: width + (base - width) * (spectrum.drawn[index] ?? 0)
                y: base - height
                gradient: Gradient {
                    GradientStop { position: 0.0; color: spectrum.light(0.4, 0.8) }
                    GradientStop { position: 1.0; color: spectrum.light(0.8, 0.4) }
                }
            }
        }
    }

    Shape {
        anchors.fill: parent
        visible: spectrum.style === "line" && spectrum.path.length > 0
        preferredRendererType: Shape.CurveRenderer

        // The glow: a wide, faint stroke under the line.
        ShapePath {
            fillColor: "transparent"
            strokeColor: spectrum.light(0.7, 0.16)
            strokeWidth: 10
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: spectrum.path }
        }
        ShapePath {
            strokeColor: spectrum.light(0.45, 0.95)
            strokeWidth: 2.5
            joinStyle: ShapePath.RoundJoin
            fillGradient: LinearGradient {
                x1: 0; y1: 0
                x2: 0; y2: spectrum.height
                GradientStop { position: 0.0; color: spectrum.light(0.8, 0.34) }
                GradientStop { position: 1.0; color: spectrum.light(0.8, 0.03) }
            }
            PathSvg { path: spectrum.path }
        }
    }
}

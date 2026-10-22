import QtQuick
import QtQuick.Shapes
import frontend_v2

// The spectrum of what is playing, in the cover's colour — a row of pills that
// grow from dots (`bars`, the default), or one smooth line with a soft fill under
// it (`line`), Theme.mediaSpectrumStyle. Along the Media view's bottom edge, and
// behind the equalizer's curve in the Options view (EqualizerPanel), where it
// shows what the curve does to the sound. The levels are the backend's (a
// recording of the host's output — backend/src/audio_service/spectrum.py); each
// band rises most of the way to a new level at once and falls back at most
// spectrumFall a second, so the bass swells and settles instead of flickering.
// Watched only while live, which is the only time the backend records.
//
// Load-bearing:
//  - SpectrumLevels (core/media/spectrumlevels.hh) does the per-frame work in C++
//    — the watch, the smoothing, the blur and the line's path — so no JavaScript
//    runs per frame (#83). It is a list model, so each bar takes its own level;
//    the line takes its path.
//  - Redrawn per frame the backend sends (about 30 a second), never by an
//    Animation, so the drawing stops when the sound does (frontend_v2/CLAUDE.md,
//    *Motion that keeps running*). Only the fade on play and pause animates.
//  - The line's path closes outside the item, so the stroke draws the curve
//    alone — where the item does not reach the window's edges, clip it.
//  - The Shape is not asynchronous. Measured: fed 30 paths a second, an
//    asynchronous one kept the window drawing every frame (59 fps, against 34
//    with the backdrop's steps).
Item {
    id: spectrum

    // The owning view's isCurrent.
    property bool active: true
    readonly property bool live: active && visible && !Display.off

    // The span of the backend's bands (LOW_HZ, HIGH_HZ in spectrum.py), equal
    // steps of log frequency across the width — for placing it on a frequency axis.
    readonly property real lowHz: 40
    readonly property real highHz: 16000

    property string style: Theme.mediaSpectrumStyle

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

    SpectrumLevels {
        id: bands
        source: Media
        live: spectrum.live
        rise: Theme.spectrumRise
        fall: Theme.spectrumFall
        tracePath: spectrum.style === "line"
        width: spectrum.width
        height: spectrum.height
    }

    // The bars: pills standing just above the bottom edge, half a slot wide, a
    // dot at rest.
    Item {
        anchors.fill: parent

        Repeater {
            // No bars at all while the line shows, so nothing hidden is updated per frame.
            model: spectrum.style === "bars" ? bands : null

            Rectangle {
                required property int index
                required property real level
                readonly property real slot: spectrum.width / bands.count
                readonly property real base: spectrum.height - 12

                width: Math.round(slot / 2)
                radius: width / 2
                x: index * slot + (slot - width) / 2
                height: width + (base - width) * level
                // Anchored, not a y bound to the height: one binding per bar a frame, not two.
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 12
                gradient: Gradient {
                    GradientStop { position: 0.0; color: spectrum.light(0.4, 0.8) }
                    GradientStop { position: 1.0; color: spectrum.light(0.8, 0.4) }
                }
            }
        }
    }

    Shape {
        anchors.fill: parent
        visible: spectrum.style === "line" && bands.count > 1
        preferredRendererType: Shape.CurveRenderer

        // The glow: a wide, faint stroke under the line.
        ShapePath {
            fillColor: "transparent"
            strokeColor: spectrum.light(0.7, 0.16)
            strokeWidth: 10
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: bands.path }
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
            PathSvg { path: bands.path }
        }
    }
}

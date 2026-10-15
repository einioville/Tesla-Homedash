import QtQuick
import QtQuick.Shapes
import frontend_v2

// The climate switch's wave over its card, driven by ClimateStarter: a band of light
// whose front runs between the button and the card's edge with its light trailing off
// behind it, and the rim lit — as the Spotify device dialog lights its — where the
// wave has passed going out, and where it has not yet passed coming back. Lies under
// the card's content and draws nothing while no switch is showing.
Item {
    id: wave

    // The button's centre, in this item's coordinates, and its radius.
    property point origin
    property real buttonRadius: 50
    // The leading edge, in px from the origin. Inbound, the wave runs toward the
    // button and its tail lies outside the front; outbound, inside it.
    property real front: 0
    property bool inbound: false
    property bool shown: false
    property bool moving: false
    property color color: "white"

    // From the origin to the farthest corner; the starter runs the wave out past it.
    readonly property real extent: Math.max(
        Math.hypot(origin.x, origin.y),
        Math.hypot(width - origin.x, origin.y),
        Math.hypot(origin.x, height - origin.y),
        Math.hypot(width - origin.x, height - origin.y))
    readonly property real tail: Theme.hvacWaveTail
    // The front's own soft edge, ahead of it.
    readonly property real lead: 14
    readonly property real peak: 0.55
    // The gradient's radius, beyond every stop it can have: a stop at position 1
    // shares it with the pad, and Qt keeps only one colour there.
    readonly property real span: extent + 2 * tail

    // A distance `behind` the front (negative: ahead of it), as a gradient position.
    function at(behind) {
        return Math.max(0, Math.min(1, (front + (inbound ? behind : -behind)) / span))
    }
    function tint(alpha) {
        return Qt.rgba(color.r, color.g, color.b, alpha)
    }

    visible: shown

    GlowBorder {
        anchors.fill: parent
        complete: true
        glowColor: wave.color
        glowThickness: 12
        glowRadius: 64
        revealOrigin: wave.origin
        // Lit up behind the front over the tail's length going out; going back, dark
        // behind it over the same length.
        revealRadius: wave.inbound ? wave.front + wave.tail : wave.front
        revealFeather: wave.tail
    }

    // The band: the card's shape filled with a ring of light, brightest at the front
    // and fading along the tail (stops on a square fall-off, so it thins out gently).
    // Fades in over the first pixels off the button, so it never pops into being.
    Shape {
        anchors.fill: parent
        visible: wave.moving
        opacity: wave.inbound ? 1 : Math.max(0, Math.min(1, (wave.front - wave.buttonRadius) / 20))
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            strokeWidth: 0
            strokeColor: "transparent"
            // Fading to the band's own colour at zero alpha, not "transparent"
            // (black), which would edge it with a dark rim.
            fillGradient: RadialGradient {
                centerX: wave.origin.x
                centerY: wave.origin.y
                centerRadius: wave.span
                focalX: wave.origin.x
                focalY: wave.origin.y
                focalRadius: 0
                GradientStop { position: wave.at(-wave.lead); color: wave.tint(0) }
                GradientStop { position: wave.at(0); color: wave.tint(wave.peak) }
                GradientStop { position: wave.at(0.3 * wave.tail); color: wave.tint(wave.peak * 0.49) }
                GradientStop { position: wave.at(0.6 * wave.tail); color: wave.tint(wave.peak * 0.16) }
                GradientStop { position: wave.at(wave.tail); color: wave.tint(0) }
            }
            PathRectangle {
                width: wave.width
                height: wave.height
                radius: Theme.cardRadius
            }
        }
    }
}

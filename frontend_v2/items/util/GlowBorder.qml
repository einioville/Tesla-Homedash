import QtQuick
import QtQuick.Effects
import QtQuick.Shapes

import frontend_v2

// Light bleeding inward from a card's border, as if the rim itself were glowing.
// Either an arc chasing round the rim (the Spotify device dialog, while its scan
// looks) or the whole perimeter lit (`complete`). A lit rim can also be revealed by
// a circle growing from a point — the climate card's wave, which lights the rim
// where it has passed (`revealOrigin` / `revealRadius`).
//
// It is a pure gradient: brightest exactly at the border, falling off smoothly
// inward, with nothing solid anywhere. That comes from a NARROW arc blurred by a
// radius several times its width and then cut by a rounded-rectangle mask whose
// edge is the border line. The mask is what makes the peak sit on the rim — half
// the blurred light is thrown away, so what is left starts at full strength at
// the cut and only decays.
//
// The width/blur RATIO is the whole trick, and it is easy to get wrong: blurring
// a band wider than the blur radius cannot dilute its middle, so the middle stays
// at full alpha and reads as a solid strip with a separate gradient behind it.
// Keep the arc's drawn width well under `glowRadius`.
//
// Approaches built and discarded, so they are not re-derived:
//  - A crisp core stroke under the glow. It reads as a hard band with a gradient
//    behind it rather than as one light.
//  - PathRectangle.strokeAdjustment to keep the stroke inside the rim. It SHIFTS
//    the stroke rather than cutting it, so round caps stay fully round and it
//    reads as a complete pill floating just inside the border.
//  - Stacking several strokes of decreasing width to fake the falloff. Reads as
//    nested pills; a gradient needs an actual blur.
//  - Plain `clip: true`. Rectangular, so the four rounded corners leak.
//
// Built on ShapePath's `trim` (Qt 6.10+), which takes FRACTIONS of the path
// length and wraps the [0,1] range itself — so the arc's position is one number,
// its growth into a full ring is one animation, and there is no perimeter
// arithmetic anywhere.
Item {
    id: trace

    // Lit fraction of the perimeter while the light is still chasing.
    property real arcFraction: 0.16
    // Light the WHOLE perimeter instead of chasing an arc around it.
    property bool complete: false
    property color glowColor: "white"
    // The rim the light lies against. Match these to the card's own border.
    property real borderWidth: 1
    property real cornerRadius: Theme.cardRadius
    property int spinMs: 2400
    // Half-height of the arc BEFORE blurring. Must stay well below glowRadius or
    // the middle survives the blur as a solid strip (see the note above).
    property real glowThickness: 5
    // How far the light reaches inward.
    property int glowRadius: 24
    // The rim is lit only within revealRadius of revealOrigin, fading out over the
    // last revealFeather pixels; below zero, all of it.
    property point revealOrigin: Qt.point(width / 2, height / 2)
    property real revealRadius: -1
    property real revealFeather: 6

    // How much of the ring is lit. The Behavior is what makes the transition a
    // completed lap rather than a jump.
    property real span: complete ? 1.0 : arcFraction
    Behavior on span {
        NumberAnimation { duration: 420; easing.type: Easing.OutCubic }
    }

    // Where the lit arc starts, as a fraction of the perimeter.
    property real offset: 0
    NumberAnimation on offset {
        // `visible` is inherited from the parent chain, so closing the dialog
        // stops this. Running it once the whole ring is lit would burn frames
        // for no visible change.
        running: trace.visible && trace.span < 0.999
        loops: Animation.Infinite
        from: 0.0
        to: 1.0
        duration: trace.spinMs
    }

    // Lightening toward white is the "found it" signal: there is no second,
    // brighter element to switch on. The factor is what animates, not the colour,
    // so a glowColor that is itself animating is followed at once.
    property real lift: complete ? 1.2 : 1.0
    Behavior on lift { NumberAnimation { duration: 420 } }
    readonly property color litColor: Qt.lighter(glowColor, lift)

    // The cut. Its edge is the card's inner rim, and the arc below is centred on
    // exactly that edge, so the mask keeps the inner half of the light.
    Rectangle {
        id: clipMask
        anchors.fill: parent
        anchors.margins: trace.borderWidth
        radius: Math.max(0, trace.cornerRadius - trace.borderWidth)
        visible: false
        layer.enabled: true
    }

    // Hidden and layered: this is a texture for the MultiEffect below, and must
    // not also paint itself, unmasked and unblurred, over the card.
    Shape {
        id: haloArc
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        visible: false
        layer.enabled: true

        ShapePath {
            strokeColor: trace.litColor
            // Doubled: the mask takes the outer half.
            strokeWidth: trace.glowThickness * 2
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            trim.start: 0
            trim.end: trace.span
            trim.offset: trace.offset

            PathRectangle {
                x: trace.borderWidth
                y: trace.borderWidth
                width: Math.max(0, haloArc.width - 2 * trace.borderWidth)
                height: Math.max(0, haloArc.height - 2 * trace.borderWidth)
                radius: Math.max(0, trace.cornerRadius - trace.borderWidth)
            }
        }
    }

    // The same cut, lit only inside the reveal circle: the cut filled with a
    // radial gradient that ends at revealRadius, softened over revealFeather.
    Shape {
        id: revealMask
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        visible: false
        layer.enabled: trace.revealRadius >= 0

        // From the origin to the farthest corner: the whole cut at a radius this far.
        readonly property real extent: Math.max(1,
            Math.hypot(trace.revealOrigin.x, trace.revealOrigin.y),
            Math.hypot(width - trace.revealOrigin.x, trace.revealOrigin.y),
            Math.hypot(trace.revealOrigin.x, height - trace.revealOrigin.y),
            Math.hypot(width - trace.revealOrigin.x, height - trace.revealOrigin.y))
        // The radius clamped just past the extent, inside a gradient a little wider
        // still: both stops must stay below position 1, or Qt keeps only the last of
        // the two there (transparent) and a fully revealed rim goes dark.
        readonly property real lit: Math.min(trace.revealRadius, extent + trace.revealFeather)
        readonly property real span: extent + trace.revealFeather + 1

        ShapePath {
            strokeWidth: 0
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: trace.revealOrigin.x
                centerY: trace.revealOrigin.y
                centerRadius: revealMask.span
                focalX: trace.revealOrigin.x
                focalY: trace.revealOrigin.y
                focalRadius: 0
                GradientStop {
                    position: Math.max(0, (revealMask.lit - trace.revealFeather) / revealMask.span)
                    color: "white"
                }
                GradientStop {
                    position: Math.max(0, revealMask.lit / revealMask.span)
                    color: "transparent"
                }
            }
            PathRectangle {
                x: trace.borderWidth
                y: trace.borderWidth
                width: Math.max(0, revealMask.width - 2 * trace.borderWidth)
                height: Math.max(0, revealMask.height - 2 * trace.borderWidth)
                radius: Math.max(0, trace.cornerRadius - trace.borderWidth)
            }
        }
    }

    MultiEffect {
        anchors.fill: parent
        source: haloArc
        blurEnabled: true
        blur: 1.0
        blurMax: trace.glowRadius
        // The blurred image must stay the item's size; padding would grow it
        // past the card's edge.
        autoPaddingEnabled: false
        maskEnabled: true
        maskSource: trace.revealRadius >= 0 ? revealMask : clipMask
        // The reveal's feather is a gradient in the mask. MultiEffect maps a mask's
        // alpha through smoothstep(t·(1+s) − s, t·(1+s)) of this threshold t and spread
        // s, so only t 0.5 with s 1 passes the gradient through (smoothstep(0, 1)): at
        // the defaults (0, 0) any alpha above zero is fully inside and the feather is a
        // hard edge at its far end, and at (0, 1) every alpha is.
        maskThresholdMin: trace.revealRadius >= 0 ? 0.5 : 0.0
        maskSpreadAtMin: trace.revealRadius >= 0 ? 1.0 : 0.0
    }
}

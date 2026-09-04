import QtQuick
import QtQuick.Effects
import QtQuick.Shapes

import frontend_v2

// Light bleeding inward from a dialog's border — as if the rim itself were
// glowing — that runs around the card while a scan is looking and lights the
// whole perimeter once there is something to report.
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
//    behind it rather than as one light — which is what this looked like before.
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
    property color glowColor: Theme.spotifyGreen
    // The rim the light lies against. Match these to the card's own border.
    property real borderWidth: 1
    property real cornerRadius: Theme.tripCardRadius
    property int spinMs: 2400
    // Half-height of the arc BEFORE blurring. Must stay well below glowRadius or
    // the middle survives the blur as a solid strip (see the note above).
    property real glowThickness: 5
    // How far the light reaches inward.
    property int glowRadius: 24

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

    // Lightening toward white is the "found it" signal now that there is no
    // second, brighter element to switch on.
    property color litColor: complete ? Qt.lighter(glowColor, 1.2) : glowColor
    Behavior on litColor { ColorAnimation { duration: 420 } }

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
        maskSource: clipMask
    }
}

import QtQuick
import QtQuick.Shapes
import QtQuick.Effects
import frontend_v2

// Rounded card painted with the dashboard's signature corner-anchored radial
// gradient (dark blue → black) plus the soft drop shadow. The gradient origin
// is given in normalised 0..1 coordinates so each card can face a different
// corner, matching the per-card qradialgradient origins of the Widgets QSS.
//
// The shadow (z:-1) and the gradient shape are declared first, so any children
// a consumer adds are painted on top of them — no content-slot alias needed.
Item {
    id: root

    // Gradient focal/centre, normalised to the card size (0,0 = top-left).
    property real gradientCx: 0.5
    property real gradientCy: 0.5
    // Gradient reach, as a multiple of the card's longest side (QSS radius 1.5).
    property real radiusFactor: 1.5
    property bool shadow: true

    RectangularShadow {
        anchors.fill: card
        visible: root.shadow
        radius: Theme.cardRadius
        blur: 50
        spread: 0
        offset: Qt.vector2d(10, 10)
        color: Theme.cardShadowColor
        z: -1
    }

    Shape {
        id: card
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            strokeWidth: 0
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: root.width * root.gradientCx
                centerY: root.height * root.gradientCy
                centerRadius: Math.max(root.width, root.height) * root.radiusFactor
                focalX: root.width * root.gradientCx
                focalY: root.height * root.gradientCy
                focalRadius: 0
                GradientStop { position: 0.0; color: Theme.cardGradientInner }
                GradientStop { position: 0.45; color: Theme.cardGradientInner }
                GradientStop { position: 1.0; color: Theme.cardGradientOuter }
            }
            PathRectangle {
                width: card.width
                height: card.height
                radius: Theme.cardRadius
            }
        }
    }
}

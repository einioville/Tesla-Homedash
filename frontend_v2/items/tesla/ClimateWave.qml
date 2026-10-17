import QtQuick
import frontend_v2

// The climate switch's wave over the whole dashboard, driven by the HVAC button
// (ClimateStarter): water that the wave's front and the waves after it push, and the
// backdrop's drifting light repainted in the wave's colour where the first wave has
// passed, fading back to the cover's when the switch is over. Lies between the
// backdrop and the cards, so it passes under them, and draws the backdrop itself while
// it shows.
//
// The water is simulated (resources/shaders/climatewater.frag, a step a frame into a
// texture that feeds back into itself), so its ripples, their crossings and their
// reflections off the edges are the water's own; climatesurface.frag unpacks it and
// climatewave.frag draws it. It runs only while a switch shows: a live recursive layer
// redraws the window every frame (ShaderEffectSource docs).
ShaderEffect {
    id: wave

    // The backdrop the wave repaints; hidden while the wave draws it.
    property Item backdrop
    property ClimateStarter button
    // The button's centre, in this item's coordinates.
    property point origin

    // Where the first wave runs out to, in px from the button's centre: until the
    // paint's tail has passed the farthest corner.
    readonly property real outTo: farthest + tail
    readonly property real farthest: Math.max(Math.hypot(origin.x, origin.y),
                                              Math.hypot(width - origin.x, origin.y),
                                              Math.hypot(origin.x, height - origin.y),
                                              Math.hypot(width - origin.x, height - origin.y))

    readonly property bool shown: button !== null && button.waveShown
    readonly property size cells: Qt.size(Math.max(1, Math.round(width / Theme.hvacWaterCell)),
                                          Math.max(1, Math.round(height / Theme.hvacWaterCell)))

    // Uniforms of the shaders, by name.
    readonly property size viewSize: Qt.size(width, height)
    readonly property vector2d texel: Qt.vector2d(1 / cells.width, 1 / cells.height)
    readonly property real buttonRadius: button ? button.buttonRadius : 0
    readonly property real front: button ? button.waveFront : 0
    readonly property real tail: Theme.hvacWaveTail
    property real clock: 0
    readonly property real slopeGain: Theme.hvacWaterSlopeGain
    readonly property real refraction: Theme.hvacWaveRefraction
    readonly property real peak: 0.6
    readonly property real waterShown: button ? button.waterLevel : 0
    readonly property real paintShown: button ? button.paintLevel : 0
    // Dim yellow reads as olive, so the pending yellow paints stronger than the
    // cover's light; red and green read well at its strength.
    readonly property real paintGain: button ? 1 + (Theme.hvacWavePendingGain - 1)
                                               * Math.max(0, 1 - Math.abs(button.waveKey - 1)) : 1
    readonly property color color: button ? button.waveColor : "white"

    property var source: ShaderEffectSource {
        sourceItem: wave.shown ? wave.backdrop : null
        hideSource: true
    }
    // Packed values, so read only at cell centres, unfiltered.
    property var water: ShaderEffectSource {
        sourceItem: step
        hideSource: true
        recursive: true
        live: wave.shown
        smooth: false
        textureSize: wave.cells
        wrapMode: ShaderEffectSource.ClampToEdge
    }
    property var surface: ShaderEffectSource {
        sourceItem: surfaceStep
        hideSource: true
        live: wave.shown
        textureSize: wave.cells
        wrapMode: ShaderEffectSource.ClampToEdge
    }

    // Seconds while the water runs; the water redraws every frame then anyway, so
    // this costs no frames of its own.
    NumberAnimation on clock {
        running: wave.shown
        from: 0
        to: 3600
        duration: 3600 * 1000
    }

    // One step of the water, rendered only into `water` (cells.width × cells.height).
    // Unblended, since its alpha is data.
    ShaderEffect {
        id: step
        anchors.fill: parent
        blending: false

        readonly property var source: wave.water
        readonly property vector2d texel: wave.texel
        readonly property size viewSize: wave.viewSize
        readonly property point origin: wave.origin
        readonly property real front: wave.button ? wave.button.pushFront : 0
        readonly property real push: wave.button && wave.button.pushing ? Theme.hvacWaterPush : 0
        readonly property real ringWidth: Theme.hvacWaterRingWidth
        readonly property real damping: Theme.hvacWaterDamping
        readonly property real wobble: Theme.hvacWaveWobble
        readonly property real buttonRadius: wave.buttonRadius
        readonly property real clock: wave.clock
        readonly property vector4d seed: wave.button ? wave.button.waveSeed : Qt.vector4d(0, 0, 0, 1)
        readonly property vector4d rings: wave.button ? wave.button.waveRings : Qt.vector4d(1, 0, 1, 1)
        readonly property vector4d lobes: wave.button ? wave.button.waveLobes : Qt.vector4d(3, 5, 11, 7)
        readonly property vector4d shape: wave.button ? wave.button.waveShape : Qt.vector4d(1, 1, 0.4, 4)
        // The first steps after the water starts clear what the texture held.
        readonly property real reset: wave.clock < 0.05 ? 1 : 0

        fragmentShader: "qrc:/resources/shaders/climatewater.frag.qsb"
    }

    // The water unpacked for the screen, rendered only into `surface`.
    ShaderEffect {
        id: surfaceStep
        anchors.fill: parent
        blending: false

        readonly property var water: wave.water
        readonly property vector2d texel: wave.texel
        readonly property real clock: wave.clock

        fragmentShader: "qrc:/resources/shaders/climatesurface.frag.qsb"
    }

    visible: shown
    fragmentShader: "qrc:/resources/shaders/climatewave.frag.qsb"
}

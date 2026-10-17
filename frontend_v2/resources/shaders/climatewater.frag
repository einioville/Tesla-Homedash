#version 440

// One step of the water under the climate switch's wave (items/tesla/ClimateWave.qml),
// run once a frame into a small texture that feeds back into itself. The wave equation
// as jquery.ripples steps it — each cell pulled toward its neighbours' mean, a little
// friction — so the crests, the wavelets behind them, their crossings and the
// reflections off the view's edges come from the water itself. The wave's front, and
// each ripple after it, pushes the water as it passes: a ring running out from the HVAC
// button that wanders out of round and pushes harder in some places than others, each
// wave in its own way (`seed`, `lobes`, `shape`), with one to three rings following it
// (`rings`). Each ring lifts the water ahead of it and lowers it behind, a bulge it
// drives along. It moves the height, as jquery.ripples' drops do:
// a spot it passes goes up and back down, where the same push on the water's speed
// would leave it raised for good.
//
// The texture is 8-bit: Qt gives a layer a float format only on a GL 3 context
// (QRhiGles2: caps.floatFormats), and an 8-bit one cannot hold a negative height. So
// height and speed are each 16 bits over two channels (pack / unpack, the same in
// climatesurface.frag), read at cell centres from an unfiltered texture.
//
// The pull is 1.6 of the mean's difference rather than jquery.ripples' 2, which is the
// scheme's stability limit: there the grid's own checkerboard never dies down. A little
// of the mean blended into the height smooths that away too, and barely touches ripples
// several cells long. The push is not quite level on a circle (the ring's outer side is
// the longer), so the height is also drawn back to level a little each step.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    // One cell, in texture coordinates.
    vec2 texel;
    vec2 viewSize;
    vec2 origin;
    // The pushing ring's distance from the button's centre, px.
    float front;
    // How far the ring moves the water's height each step; 0 while nothing pushes.
    float push;
    // Px across the ring the front pushes with.
    float ringWidth;
    // The speed each cell keeps from one step to the next.
    float damping;
    // Px the ring wanders out of round once it has spread.
    float wobble;
    float buttonRadius;
    // Seconds since the water started moving; moves the wobble and the push's
    // pattern round the ring.
    float clock;
    // The pushing wave's own draw: a turn of the whole pattern (x, radians), the
    // phases of its lobes (y, z) and a scale on the push (w).
    vec4 seed;
    // How many rings the wave pushes (x, 1 to maxRings), how many px apart (y), a
    // scale on their width (z) and how hard each after the first pushes against the
    // one ahead of it (w).
    vec4 rings;
    // Whole lobes round the circle, so neither pattern has a seam where theta wraps:
    // the wobble's three (x, y, z) and the first of the push's two (w).
    vec4 lobes;
    // A scale on the wobble (x), on how fast the patterns turn, signed for the way
    // they turn (y), how deep the push's pattern cuts (z) and its second lobe count (w).
    vec4 shape;
    // 1 for the first steps after the water starts: still water.
    float reset;
};

layout(binding = 1) uniform sampler2D source;

// Px of spread over which the wobble grows to full, so the ring leaves the button
// and closes on it round.
const float wobbleGrowPx = 400.0;
const float pull = 1.6;
const float smoothing = 0.04;
const float levelling = 0.995;
const int maxRings = 3;
// Heights and speeds are held within ±range.
const float range = 2.0;

vec2 pack(float value)
{
    float u = floor(clamp(value / range * 0.5 + 0.5, 0.0, 1.0) * 65535.0 + 0.5);
    float high = floor(u / 256.0);
    return vec2(high, u - high * 256.0) / 255.0;
}

float unpack(vec2 bytes)
{
    vec2 b = floor(bytes * 255.0 + 0.5);
    return ((b.x * 256.0 + b.y) / 65535.0 - 0.5) * 2.0 * range;
}

float heightAt(vec2 at)
{
    return unpack(texture(source, at).rg);
}

void main()
{
    if (reset > 0.5) {
        fragColor = vec4(pack(0.0), pack(0.0));
        return;
    }
    vec4 cell = texture(source, qt_TexCoord0);
    float height = unpack(cell.rg);
    float speed = unpack(cell.ba);
    float mean = (heightAt(qt_TexCoord0 - vec2(texel.x, 0.0))
                + heightAt(qt_TexCoord0 + vec2(texel.x, 0.0))
                + heightAt(qt_TexCoord0 - vec2(0.0, texel.y))
                + heightAt(qt_TexCoord0 + vec2(0.0, texel.y))) * 0.25;
    speed = (speed + (mean - height) * pull) * damping;
    height += (mean - height) * smoothing;

    vec2 d = qt_TexCoord0 * viewSize - origin;
    float theta = atan(d.y, d.x) + seed.x;
    float turning = shape.y * clock;
    float spread = clamp((front - buttonRadius) / wobbleGrowPx, 0.0, 1.0);
    float wander = 0.5 * sin(lobes.x * theta + 0.9 * turning + seed.y)
                 + 0.3 * sin(lobes.y * theta - 1.4 * turning + seed.z)
                 + 0.2 * sin(lobes.z * theta + 2.1 * turning + seed.y + seed.z);
    // Across a ring, x runs outward, the way it moves.
    float r = length(d) + wobble * shape.x * spread * wander;
    float width = ringWidth * rings.z;
    float bulge = 0.0;
    float ringPush = 1.0;
    for (int i = 0; i < maxRings; ++i) {
        if (float(i) < rings.x) {
            float x = (r - front + float(i) * rings.y) / width;
            bulge += ringPush * x * exp(-2.0 * x * x);
        }
        ringPush *= rings.w;
    }
    float strength = 1.0 - shape.z + shape.z * sin(lobes.w * theta - 1.1 * turning + seed.z)
                                             * sin(shape.w * theta + 0.8 * turning + seed.y);

    height = (height + speed) * levelling + push * seed.w * bulge * strength;
    fragColor = vec4(pack(height), pack(speed));
}

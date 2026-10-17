#version 440

// The water's surface (climatewater.frag) unpacked once a frame, per cell, into what the
// screen reads (climatewave.frag): its slope across and down in r and g as
// 0.5 + slope × 4, its height in b as 0.5 + height / 2. Plain 8-bit values a filtered
// texture can blend between cells, which the water's packed 16-bit ones cannot be. The
// slope's scale is fine because the screen magnifies it: a coarser one shows its steps
// as bands in the glints.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    // One cell, in texture coordinates.
    vec2 texel;
    // Unread here: it changes every frame the water runs, which is what makes Qt
    // redraw this pass. A layer redraws only when its own item changes, and a new
    // step in the water texture it reads is not one.
    float clock;
};

layout(binding = 1) uniform sampler2D water;

// As in climatewater.frag.
const float range = 2.0;

float unpack(vec2 bytes)
{
    vec2 b = floor(bytes * 255.0 + 0.5);
    return ((b.x * 256.0 + b.y) / 65535.0 - 0.5) * 2.0 * range;
}

float heightAt(vec2 at)
{
    return unpack(texture(water, at).rg);
}

void main()
{
    float height = heightAt(qt_TexCoord0);
    // Height change per cell, across and down.
    vec2 slope = 0.5 * vec2(heightAt(qt_TexCoord0 + vec2(texel.x, 0.0)) - heightAt(qt_TexCoord0 - vec2(texel.x, 0.0)),
                            heightAt(qt_TexCoord0 + vec2(0.0, texel.y)) - heightAt(qt_TexCoord0 - vec2(0.0, texel.y)));
    fragColor = vec4(clamp(0.5 + vec3(slope * 4.0, height * 0.5), 0.0, 1.0), 1.0);
}

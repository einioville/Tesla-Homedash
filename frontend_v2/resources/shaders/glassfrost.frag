#version 440

// A glass panel's part of a shared frosted backdrop (items/util/FrostLayer.qml): the region
// of the blurred texture behind the panel, cut to the panel's rounded rectangle with a
// one-pixel soft edge. The texture is small and already blurred, so linear filtering is
// all the upscaling it needs.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    // The panel's rectangle in the texture's coordinates: x, y, width, height.
    vec4 region;
    // The panel's size and corner radius, in pixels.
    vec2 size;
    float radius;
};

layout(binding = 1) uniform sampler2D source;

void main()
{
    vec4 color = texture(source, region.xy + qt_TexCoord0 * region.zw);
    vec2 p = abs(qt_TexCoord0 * size - size * 0.5) - (size * 0.5 - radius);
    float distance = length(max(p, 0.0)) + min(max(p.x, p.y), 0.0) - radius;
    float inside = clamp(0.5 - distance, 0.0, 1.0);
    fragColor = vec4(color.rgb, 1.0) * inside * qt_Opacity;
}

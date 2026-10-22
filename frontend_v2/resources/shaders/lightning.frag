#version 440

// A lightning strike's cross: two diagonal strokes `radius` out from the strike, `halfWidth`
// each side of their line, with round ends — what a canvas stroke with round caps draws —
// and a one-pixel soft edge. The outline pass draws it wider in black, the cross pass in
// yellow over it.

layout(location = 0) in vec2 local;
layout(location = 1) in float alpha;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    vec4 color;
    float qt_Opacity;
    float radius;
    float halfWidth;
    float frame;
    float frameCount;
    float fresh;
};

// Distance from p to the stroke through the origin along d, `reach` each way.
float stroke(vec2 p, vec2 d, float reach)
{
    return length(p - clamp(dot(p, d), -reach, reach) * d);
}

void main()
{
    float reach = radius * 1.41421356;
    float d = min(stroke(local, vec2(0.70710678, 0.70710678), reach),
                  stroke(local, vec2(0.70710678, -0.70710678), reach));
    float cover = clamp(halfWidth + 0.5 - d, 0.0, 1.0);
    fragColor = color * (cover * alpha * qt_Opacity);
}

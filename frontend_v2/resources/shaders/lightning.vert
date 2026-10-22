#version 440

// One lightning strike's quad (core/weather/lightninglayer.hh): its corner in the item's
// pixels, the corner's offset from the strike, and when the strike fell. The pass decides
// whether it draws: the shown frame's own strikes (`fresh`), or the loop's earlier ones,
// faded with their age the way the radar frames' timeline reads. A quad the pass does not
// draw collapses to a point, so a loop step only changes `frame`.

layout(location = 0) in vec4 vertexCoord;
layout(location = 1) in vec2 offset;
// x: the strike's time in loop steps from the first frame; y: the frame slot it falls in.
layout(location = 2) in vec2 timeSlot;

layout(location = 0) out vec2 local;
layout(location = 1) out float alpha;

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

void main()
{
    bool shown = fresh > 0.5 ? abs(timeSlot.y - frame) < 0.5 : timeSlot.y < frame - 0.5;
    alpha = fresh > 0.5 ? 1.0 : max(0.3, 0.9 - 0.6 * (frame - timeSlot.x) / frameCount);
    local = offset;
    gl_Position = shown ? qt_Matrix * vertexCoord : vec4(-2.0, -2.0, 0.0, 1.0);
}

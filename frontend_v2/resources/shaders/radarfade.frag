#version 440

// The radar frame on screen (items/weather/RadarLayer.qml), with the loop's previous frame
// blended into it while a step fades in. Both are pictures of one box, so they share the
// texture coordinates. Qt Quick's textures are premultiplied, so a plain mix keeps a pixel the
// two frames share exactly as it is and fades one only one of them has in or out. Two Images
// laid over each other would instead brighten the light rain mid-fade: FMI draws it
// translucent (alpha 38–204).

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    // 0 shows the previous frame, 1 the current one.
    float progress;
};

layout(binding = 1) uniform sampler2D previous;
layout(binding = 2) uniform sampler2D current;

void main()
{
    fragColor = mix(texture(previous, qt_TexCoord0), texture(current, qt_TexCoord0), progress)
                * qt_Opacity;
}

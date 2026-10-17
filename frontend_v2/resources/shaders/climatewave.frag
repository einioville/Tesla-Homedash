#version 440

// The climate switch's wave over the dashboard's backdrop (items/tesla/ClimateWave.qml):
// the water (climatewater.frag, read through climatesurface.frag) seen from above, and
// the backdrop repainted in the wave's colour where the first wave has passed, fading
// back to the cover's when the switch is over. The crests glow in the wave's colour,
// the water glints where its slope faces the light and shades where it faces away, and
// the backdrop is seen bent through it.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 viewSize;
    vec2 origin;
    // The first wave's distance from the button's centre, px.
    float front;
    // Px behind the front over which the paint fades in.
    float tail;
    // The paint's strength, 1 to 0 as it fades back to the cover's colours.
    float paintShown;
    // How the water's height and slope read: a crest of height 1 glows at full
    // `peak`, and a height step of 1 between cells is a slope of slopeGain.
    float slopeGain;
    // How far a slope of 1 shifts the backdrop seen through it, px.
    float refraction;
    float peak;
    // The water's effect, faded out as it calms.
    float waterShown;
    // The painted light's strength over the backdrop's own.
    float paintGain;
    vec4 color;
    // Unread, as in climatesurface.frag: it keeps this redrawn while the water runs on
    // after the front has stopped.
    float clock;
};

layout(binding = 1) uniform sampler2D source;
layout(binding = 2) uniform sampler2D surface;

// Where the light comes from, on the screen (y down): the top left.
const vec2 lightDir = vec2(-0.6, -0.8);

void main()
{
    // As climatesurface.frag stores them.
    vec3 water = texture(surface, qt_TexCoord0).rgb - 0.5;
    vec2 gradient = water.xy * 0.25 * slopeGain * waterShown;
    float height = water.z * 2.0 * waterShown;
    // How squarely the water faces the light: the surface tilts downhill.
    float facing = dot(-gradient, normalize(lightDir));

    vec4 backdrop = texture(source, qt_TexCoord0 - gradient * refraction / viewSize);

    // Painted where the first wave has passed, fading in over the tail.
    float r = length(qt_TexCoord0 * viewSize - origin);
    float paint = smoothstep(0.0, tail, front - r) * paintShown;
    float paintedAlpha = min(1.0, backdrop.a * paintGain);
    vec4 painted = vec4(color.rgb * paintedAlpha, paintedAlpha);
    vec4 under = mix(backdrop, painted, paint) * (1.0 - 0.45 * clamp(-facing, 0.0, 1.0));

    // The crests glow in the wave's colour; water facing the light glints paler.
    // Premultiplied throughout, so the light goes over the backdrop with a source-over.
    float glow = peak * clamp(height, 0.0, 1.0);
    float glint = 0.7 * pow(clamp(facing, 0.0, 1.0), 1.5);
    vec3 light = color.rgb * glow + mix(color.rgb, vec3(1.0), 0.5) * glint;
    float alpha = min(1.0, glow + glint);
    fragColor = (vec4(light, alpha) + under * (1.0 - alpha)) * qt_Opacity;
}

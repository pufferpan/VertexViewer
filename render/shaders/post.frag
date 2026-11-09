#version 330 core
// Post-process: exposure -> optional bloom -> ACES -> sRGB -> vignette -> grain
in vec2 v_uv;
out vec4 fragColor;

uniform sampler2D u_scene;
uniform vec2  u_texel;
uniform float u_exposure;     // 2^EV
uniform float u_bloom;
uniform float u_vignette;
uniform float u_grain;
uniform float u_saturation;
uniform float u_contrast;     // 1.0 = 原样；>1 压对比
uniform float u_ca;           // 色散强度（画面边缘那点红/蓝分离）
uniform float u_time;

vec3 aces_fit(vec3 x)
{
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

vec3 to_srgb(vec3 c)
{
    c = max(c, vec3(0.0));
    return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055,
               step(vec3(0.0031308), c));
}

float hash12(vec2 p)
{
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main()
{
    // 一点点径向色散：越靠边越明显，看着更「镜头」
    vec2 dvec = v_uv - 0.5;
    float rad = dot(dvec, dvec);
    float ca = u_ca * rad * 6.0;
    vec3 c;
    if (ca > 0.00001) {
        c.r = texture(u_scene, v_uv + dvec * ca).r;
        c.g = texture(u_scene, v_uv).g;
        c.b = texture(u_scene, v_uv - dvec * ca).b;
        c *= u_exposure;
    } else {
        c = texture(u_scene, v_uv).rgb * u_exposure;
    }

    if (u_bloom > 0.0) {
        vec3 b = vec3(0.0);
        float wsum = 0.0;
        for (int i = 0; i < 8; ++i) {
            float ang = float(i) * 0.7853982;
            vec2 dir = vec2(cos(ang), sin(ang));
            for (int r = 1; r <= 3; ++r) {
                vec3 s = texture(u_scene, v_uv + dir * u_texel * float(r) * 5.0).rgb * u_exposure;
                float w = 1.0 / float(r);
                b += max(s - 0.75, vec3(0.0)) * w;
                wsum += w;
            }
        }
        c += b / wsum * u_bloom;
    }

    c = aces_fit(c);
    float lum = dot(c, vec3(0.2126, 0.7152, 0.0722));
    c = mix(vec3(lum), c, u_saturation);
    c = to_srgb(c);
    // 对比：放到感知空间（sRGB 之后）再做，暗部不会被压成一团黑
    if (abs(u_contrast - 1.0) > 0.001) {
        c = clamp((c - 0.5) * u_contrast + 0.5, 0.0, 1.0);
    }

    vec2 p = v_uv * 2.0 - 1.0;
    c *= 1.0 - u_vignette * dot(p, p) * 0.45;
    c += (hash12(v_uv * vec2(1920.0, 1080.0) + u_time) - 0.5) * u_grain;

    fragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
}

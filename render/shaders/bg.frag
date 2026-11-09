#version 330 core
// Procedural studio backgrounds. Values are linear HDR; post.frag tone maps them.
in vec2 v_uv;
out vec4 fragColor;

uniform int   u_kind;      // 0 studio | 1 gradient | 2 dark
uniform float u_aspect;

void main()
{
    vec2 p = v_uv * 2.0 - 1.0;
    p.x *= u_aspect;
    vec3 c;

    if (u_kind == 0) {
        // studio: soft box gradient + warm key glow, dark floor
        float r = length(p * vec2(0.82, 1.0));
        vec3 top = vec3(0.085, 0.090, 0.105);
        vec3 bot = vec3(0.020, 0.021, 0.026);
        c = mix(bot, top, smoothstep(-1.0, 1.0, p.y));
        vec2 q = p - vec2(-0.55, 0.45);
        c += vec3(0.11, 0.105, 0.095) * exp(-dot(q, q) * 2.4);
        c *= mix(0.50, 1.0, smoothstep(1.9, 0.15, r));
    } else if (u_kind == 1) {
        // gradient: cool blue -> violet
        c = mix(vec3(0.035, 0.050, 0.090), vec3(0.150, 0.090, 0.210),
                smoothstep(-1.0, 1.0, p.y));
        c += vec3(0.10, 0.13, 0.22) * exp(-length(p - vec2(0.6, -0.4)) * 1.6);
        c *= mix(0.55, 1.0, smoothstep(1.8, 0.2, length(p)));
    } else {
        // dark: near black with a faint centre lift
        c = vec3(0.012, 0.013, 0.017) + vec3(0.020, 0.020, 0.027) *
            smoothstep(1.6, 0.0, length(p));
    }

    // 8bit 显示器上这么淡的渐变很容易出一条条「台阶」（尤其暗部），
    // 加一点点确定性抖动（屏幕坐标哈希）把台阶打散，看起来就是干净的渐变。
    float dither = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
    c += (dither - 0.5) * 0.0022;

    fragColor = vec4(max(c, vec3(0.0)), 1.0);
}

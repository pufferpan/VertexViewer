#version 330 core
// ---------------------------------------------------------------------------
// VertexViewer scene fragment shader
//   * Cook-Torrance PBR (GGX + Smith height-correlated visibility + Schlick)
//   * analytic sky IBL approximation (no HDRI needed)
//   * 3 independent directional lights, optional PCF shadow map for the key
//   * stylised modes: toon / posterize / neon / blueprint / clay
// Tone mapping + sRGB conversion happen later, in post.frag.
// ---------------------------------------------------------------------------
in vec3 v_wpos;
in vec3 v_nrm;
in vec2 v_uv;
in vec3 v_tan;
in float v_tanw;

out vec4 fragColor;

const float PI = 3.14159265359;

uniform int   u_style;

// ---- material
uniform vec4  u_base_color;
uniform vec3  u_emissive;
uniform float u_metallic;
uniform float u_roughness;
uniform int   u_metal_mode;      // 0 = 用 MRA 贴图的 R 通道，1 = 用 u_metallic（用户拖动滑杆）
uniform int   u_rough_mode;      // 0 = 用 MRA 贴图的 G 通道，1 = 用 u_roughness
uniform float u_ao;
uniform int   u_has_base;
uniform int   u_has_normal;
uniform int   u_normal_xy;     // NCE / BC5 stores normal XY; B contains other data
uniform int   u_has_orm;
uniform int   u_has_emissive;
uniform sampler2D u_tex_base;
uniform sampler2D u_tex_normal;
uniform sampler2D u_tex_orm;
uniform sampler2D u_tex_emissive;

// ---- camera
uniform vec3 u_cam_pos;

// ---- lights (index 0 = key, 1 = fill, 2 = rim)
uniform vec3  u_light_dir[3];
uniform vec3  u_light_color[3];
uniform float u_light_angle[3];
uniform vec3  u_amb_top;
uniform vec3  u_amb_bottom;
uniform float u_env_intensity;

// ---- shadow
uniform int       u_shadow_enabled;
uniform mat4      u_light_vp;
uniform sampler2D u_shadow_map;
uniform float     u_shadow_texel;
uniform float     u_shadow_radius;   // 阴影相机覆盖的世界半径（算偏移用）

// ---- style parameters
uniform float u_rim_strength;
uniform vec3  u_rim_color;
uniform float u_posterize_levels;
uniform float u_hue_shift;
uniform vec3  u_style_color;
uniform float u_grid_scale;
uniform float u_time;
uniform float u_saturation;

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------
float d_ggx(float NoH, float a)
{
    float a2 = a * a;
    float d = NoH * NoH * (a2 - 1.0) + 1.0;
    return a2 / (PI * d * d + 1e-7);
}

float v_smith_joint(float NoV, float NoL, float a)
{
    float a2 = a * a;
    float gv = NoL * sqrt(NoV * NoV * (1.0 - a2) + a2);
    float gl = NoV * sqrt(NoL * NoL * (1.0 - a2) + a2);
    return 0.5 / (gv + gl + 1e-7);
}

vec3 f_schlick(vec3 f0, float u)
{
    return f0 + (1.0 - f0) * pow(1.0 - u, 5.0);
}

// Analytic environment: sky dome gradient + per-light sun glow.
vec3 sky_color(vec3 d)
{
    float h = clamp(d.y * 0.5 + 0.5, 0.0, 1.0);
    vec3 horizon = mix(u_amb_bottom, u_amb_top, 0.55);
    vec3 zenith  = u_amb_top * 1.6;
    vec3 c = mix(horizon, zenith, smoothstep(0.45, 1.0, h));
    c = mix(u_amb_bottom * 0.5, c, smoothstep(-0.35, 0.05, d.y));
    for (int i = 0; i < 3; ++i) {
        float sd = max(dot(d, u_light_dir[i]), 0.0);
        c += u_light_color[i] * pow(sd, 24.0) * 0.35;
    }
    return c * u_env_intensity;
}

vec3 env_specular(vec3 r, float rough)
{
    vec3 sharp = sky_color(normalize(r));
    vec3 avg = (u_amb_top + u_amb_bottom) * 0.5 * u_env_intensity;
    return mix(sharp, avg, smoothstep(0.10, 0.95, rough));
}

float shadow_factor(vec3 wp, vec3 N, float NoL)
{
    if (u_shadow_enabled == 0) return 1.0;
    // 法线方向按「阴影贴图一个像素在世界里多大」偏移：
    // 早期用的是固定 0.003，模型一大（载具/集装箱）就不够，曲面上一片一片的
    // 方块状脏影（shadow acne），模型一小又偏得过头。这里跟 texel 走，
    // 再叠一点斜率偏移，曲面就干净了。
    float texel_world = 2.0 * u_shadow_radius * u_shadow_texel;
    vec3 n_off = N * max(texel_world * 1.6, 0.0008);
    vec4 lp = u_light_vp * vec4(wp + n_off, 1.0);
    vec3 proj = lp.xyz / lp.w;
    proj = proj * 0.5 + 0.5;
    if (proj.z >= 1.0 || proj.x <= 0.0 || proj.x >= 1.0 || proj.y <= 0.0 || proj.y >= 1.0)
        return 1.0;
    float slope = clamp(1.0 - NoL, 0.0, 1.0);
    float bias = texel_world * (0.35 + 1.10 * slope) + 0.0004;
    // 3x3 太硬，边上是「台阶块」；扩成 5x5 的四角采样 + 对角线模糊，
    // 采样数还是 9 个，但落点错开，块状感基本看不出来。
    const vec2 taps[9] = vec2[9](
        vec2(0.0, 0.0),
        vec2(-1.5, -0.5), vec2(1.5, -0.5), vec2(-1.5, 0.5), vec2(1.5, 0.5),
        vec2(-0.5, -1.5), vec2(0.5, -1.5), vec2(-0.5, 1.5), vec2(0.5, 1.5));
    float sum = 0.0;
    for (int i = 0; i < 9; ++i) {
        float d = texture(u_shadow_map, proj.xy + taps[i] * u_shadow_texel).r;
        sum += (proj.z - bias > d) ? 0.0 : 1.0;
    }
    return sum / 9.0;
}

vec3 hue_rotate(vec3 c, float a)
{
    const vec3 k = vec3(0.57735027);
    float ca = cos(a);
    float sa = sin(a);
    return c * ca + cross(k, c) * sa + k * dot(k, c) * (1.0 - ca);
}

// ---------------------------------------------------------------------------
void main()
{
    // UV belongs to the vertex. Winding must never change texture coordinates.
    vec2 v_uv_f = v_uv;
    vec3 N = normalize(v_nrm);
    vec3 V = normalize(u_cam_pos - v_wpos);
    // UE assets use mixed winding; orient the actual normal for two-sided light.
    if (dot(N, V) < 0.0) N = -N;

    // ---- tangent frame (needed by the normal map)
    vec3 tangent = v_tan - N * dot(N, v_tan);
    if (dot(tangent, tangent) < 1e-8) {
        tangent = cross(abs(N.y) < 0.99 ? vec3(0, 1, 0) : vec3(1, 0, 0), N);
    }
    vec3 T = normalize(tangent);
    vec3 B = cross(N, T) * (v_tanw < 0.0 ? -1.0 : 1.0);

    bool textured = (u_style != 4 && u_style != 5);   // blueprint / clay ignore maps

    vec3  albedo   = u_base_color.rgb;
    float alpha    = u_base_color.a;
    float metal    = clamp(u_metallic, 0.0, 1.0);
    float rough    = clamp(u_roughness, 0.02, 1.0);
    float ao       = clamp(u_ao, 0.0, 1.0);
    vec3  emissive = u_emissive;

    if (textured && u_has_base == 1) {
        vec4 t = texture(u_tex_base, v_uv_f);
        albedo *= t.rgb;
        alpha  *= t.a;
    }
    if (textured && u_has_normal == 1) {
        vec3 nt = texture(u_tex_normal, v_uv_f).xyz * 2.0 - 1.0;
        if (u_normal_xy == 1) {
            nt.z = sqrt(max(1.0 - dot(nt.xy, nt.xy), 1e-4));
        }
        vec3 tn = normalize(T * nt.x + B * nt.y + N * nt.z);
        N = tn;
    }
    float NoV = clamp(dot(N, V), 1e-4, 1.0);
    if (textured && u_has_orm == 1) {
        // 该游戏的打包贴图叫 MRA：R=Metallic  G=Roughness  B=AmbientOcclusion
        // （实测：聚合物弹匣 R≈0.17 / 金属炮塔 R≈0.0，都符合「R 是金属度」；
        //  若按 UE 的 ORM=R,AO 读，AO 会低到 0.05 把模型压成全黑。）
        vec3 mra = texture(u_tex_orm, v_uv_f).rgb;
        if (u_metal_mode == 0) metal = clamp(mra.r, 0.0, 1.0);
        if (u_rough_mode == 0) rough = clamp(mra.g, 0.03, 1.0);
        ao = clamp(mra.b, 0.0, 1.0);
    }
    if (textured && u_has_emissive == 1) {
        emissive = texture(u_tex_emissive, v_uv_f).rgb * u_emissive;
    }

    // -----------------------------------------------------------------------
    // Cook-Torrance PBR
    // -----------------------------------------------------------------------
    vec3  f0      = mix(vec3(0.04), albedo, metal);
    float NoVc    = max(NoV, 1e-4);
    vec3  diffuse = vec3(0.0);
    vec3  spec    = vec3(0.0);
    float key_shadow = 1.0;

    for (int i = 0; i < 3; ++i) {
        vec3  L    = normalize(u_light_dir[i]);
        float NoL  = max(dot(N, L), 0.0);
        if (NoL <= 0.0) continue;
        vec3  H    = normalize(L + V);
        float NoH  = max(dot(N, H), 0.0);
        float VoH  = max(dot(V, H), 0.0);
        // GGX takes alpha = perceptual roughness squared. Feeding roughness
        // directly into it spreads a pale highlight across the whole surface.
        float alpha_ggx = rough * rough;
        float a    = clamp(sqrt(alpha_ggx * alpha_ggx
                               + u_light_angle[i] * u_light_angle[i]), 0.035, 1.0);
        float D    = d_ggx(NoH, a);
        float Vis  = v_smith_joint(NoVc, NoL, a);
        vec3  F    = f_schlick(f0, VoH);
        vec3  rad  = u_light_color[i];
        float sh   = (i == 0) ? shadow_factor(v_wpos, N, NoL) : 1.0;
        if (i == 0) key_shadow = sh;
        diffuse += albedo * (vec3(1.0) - F) * (1.0 - metal)
                   * NoL * rad * sh * (1.0 / PI);
        spec    += D * Vis * F * NoL * rad * sh;
    }

    // hemisphere ambient (diffuse IBL stand-in); key shadow also dims it so contact
    // shadows read on receivers that are otherwise lifted by env light
    vec3 amb_irr = mix(u_amb_bottom, u_amb_top, N.y * 0.5 + 0.5) * u_env_intensity
                 * mix(0.45, 1.0, key_shadow);
    diffuse += albedo * (vec3(1.0) - f0) * (1.0 - metal) * amb_irr * ao;
    // analytic specular IBL: blurred sky lookup along the reflection vector
    vec3 R = reflect(-V, N);
    vec3 env = env_specular(R, rough);
    spec += env * f0 * (1.0 - 0.72 * rough) * mix(0.35, 1.0, ao)
          * mix(0.65, 1.0, key_shadow);

    vec3 color = diffuse + spec + emissive;

    // -----------------------------------------------------------------------
    // stylised looks
    // -----------------------------------------------------------------------
    float rim = pow(1.0 - NoV, 3.0) * u_rim_strength;

    if (u_style == 1) {
        // ---- toon: 3 hard light bands + rim + inverted-hull outline pass
        float ndl  = dot(N, normalize(u_light_dir[0]));
        float b1   = smoothstep(0.02, 0.06, ndl);
        float b2   = smoothstep(0.38, 0.42, ndl);
        float b3   = smoothstep(0.72, 0.76, ndl);
        float band = (b1 + b2 + b3) / 3.0;
        float sh   = shadow_factor(v_wpos, N, max(ndl, 0.0));
        band *= mix(0.45, 1.0, sh);
        vec3 tint  = mix(u_amb_bottom, u_light_color[0], 0.55);
        color = albedo * (0.16 + 1.15 * band) * (0.55 + 0.45 * tint);
        color += u_rim_color * rim * 0.85;
        color += emissive * 0.5;
    } else if (u_style == 2) {
        // ---- posterize: quantised colour levels + hue rotation
        float lv = max(u_posterize_levels, 2.0);
        vec3 c = color;
        // quantise in a gamma-ish domain so mid tones get real steps
        c = pow(max(c, vec3(0.0)), vec3(0.4545));
        c = floor(c * lv + 0.5) / lv;
        c = pow(c, vec3(2.2));
        c = hue_rotate(c, u_hue_shift);
        color = c;
    } else if (u_style == 3) {
        // ---- neon: dark body, electric rim, scanlines
        float ndl = max(dot(N, normalize(u_light_dir[0])), 0.0);
        float bands = 0.22 + 0.40 * smoothstep(0.05, 0.65, ndl);
        float glow = pow(1.0 - NoV, 1.5);
        color = albedo * (0.10 + 0.22 * bands) + u_style_color * 0.35;
        color += u_rim_color * glow * (1.6 + 0.9 * u_rim_strength);
        float scan = 0.5 + 0.5 * sin(v_wpos.y * 110.0 - u_time * 5.0);
        color += u_rim_color * 0.14 * scan * smoothstep(0.10, 0.85, glow);
        color += emissive;
    } else if (u_style == 4) {
        // ---- blueprint: monochrome blue + white grid + fresnel edges
        vec2 guv = v_uv * u_grid_scale;
        vec2 g = abs(fract(guv) - 0.5);
        float line = 1.0 - smoothstep(0.012, 0.04, min(g.x, g.y));
        float ndl = max(dot(N, normalize(u_light_dir[0])), 0.0);
        float fill = 0.25 + 0.55 * ndl;
        vec3 base = u_style_color * fill;
        color = base + vec3(0.55, 0.80, 1.0) * line * 0.55;
        color += vec3(0.55, 0.75, 1.0) * pow(1.0 - NoV, 3.0) * 0.45;
    } else if (u_style == 5) {
        // ---- clay: no maps, warm matte, wrapped lambert
        float ndl = max(dot(N, normalize(u_light_dir[0])), 0.0);
        float fill = 0.28 + 0.72 * (0.5 + 0.5 * ndl);
        float sh = shadow_factor(v_wpos, N, ndl);
        color = u_style_color * fill * mix(0.70, 1.0, sh);
        color += u_rim_color * pow(1.0 - NoV, 4.0) * 0.10;
    } else if (u_style == 6) {
        // ---- game: subtle colour grading over the same material lighting.
        // Do not add another environment/specular pass or a constant white
        // floor here: those obscure dark paint and look like a milky coating.
        float luma0 = dot(color, vec3(0.2126, 0.7152, 0.0722));
        vec3 warm = color * vec3(1.035, 1.005, 0.965);
        vec3 cool = color * vec3(0.965, 0.995, 1.045);
        color = mix(cool, warm, smoothstep(0.03, 0.28, luma0));
    }

    // saturation trim (also makes the styles pixel-different)
    float lum = dot(color, vec3(0.2126, 0.7152, 0.0722));
    color = mix(vec3(lum), color, u_saturation);

    fragColor = vec4(max(color, vec3(0.0)), clamp(alpha, 0.0, 1.0));
}

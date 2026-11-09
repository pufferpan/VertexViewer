#version 330 core
// Scene vertex shader: mesh data is already in OpenGL space / metres.
layout(location = 0) in vec3 a_pos;
layout(location = 1) in vec3 a_nrm;
layout(location = 2) in vec2 a_uv;
layout(location = 3) in vec4 a_tan;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_proj;
uniform mat3 u_normal_mat;
uniform float u_outline;     // world-space normal expansion (inverted hull / outline pass)

out vec3 v_wpos;
out vec3 v_nrm;
out vec2 v_uv;
out vec3 v_tan;
out float v_tanw;

void main()
{
    vec3 p = a_pos + a_nrm * u_outline;
    vec4 wp = u_model * vec4(p, 1.0);
    v_wpos = wp.xyz;
    v_nrm = normalize(u_normal_mat * a_nrm);
    vec3 t = u_normal_mat * a_tan.xyz;
    // guard degenerate tangents so normalize() never produces NaN
    v_tan = length(t) > 1e-8 ? normalize(t) : vec3(1.0, 0.0, 0.0);
    v_tanw = a_tan.w;
    v_uv = a_uv;
    gl_Position = u_proj * u_view * wp;
}

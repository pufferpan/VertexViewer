#version 330 core
// Depth-only shadow pass (directional key light).
layout(location = 0) in vec3 a_pos;
uniform mat4 u_model;
uniform mat4 u_light_vp;
void main()
{
    gl_Position = u_light_vp * u_model * vec4(a_pos, 1.0);
}

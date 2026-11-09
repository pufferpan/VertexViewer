#version 330 core
// Flat outline colour for the inverted-hull pass.
uniform vec3 u_outline_color;
out vec4 fragColor;
void main()
{
    fragColor = vec4(u_outline_color, 1.0);
}

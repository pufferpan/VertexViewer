# VertexViewer render/ self-test report

Generated: 2026-11-01 18:29:48

## Environment

- OpenGL: `3.3.0 NVIDIA 610.62` on `NVIDIA GeForce GTX 1650/PCIe/SSE2`
- Vendor: `NVIDIA Corporation`
- GLSL: `3.30 NVIDIA via Cg compiler`
- Shader programs compiled: **5/5**
  - `scene` (scene.vert + scene.frag): ok
  - `outline` (scene.vert + outline.frag): ok
  - `shadow` (shadow.vert + shadow.frag): ok
  - `bg` (post.vert + bg.frag): ok
  - `post` (post.vert + post.frag): ok
- Python: 3.12.10; results in `render/`

## Preview captures (1280x720)

| file | style | metallic | roughness | mean | std | min | max | verdict |
|---|---|---|---|---|---|---|---|---|
| preview_pbr_m0_r10.png | pbr | 0.0 | 0.1 | 0.4323 | 0.3571 | 0.004 | 1.000 | ok |
| preview_pbr_m1_r10.png | pbr | 1.0 | 0.1 | 0.4199 | 0.3594 | 0.000 | 1.000 | ok |
| preview_pbr_m0_r90.png | pbr | 0.0 | 0.9 | 0.4313 | 0.3565 | 0.012 | 1.000 | ok |
| preview_pbr_m1_r90.png | pbr | 1.0 | 0.9 | 0.4199 | 0.3561 | 0.000 | 1.000 | ok |
| preview_toon_m0_r10.png | toon | 0.0 | 0.1 | 0.4454 | 0.3603 | 0.000 | 1.000 | ok |
| preview_toon_m1_r10.png | toon | 1.0 | 0.1 | 0.4454 | 0.3603 | 0.000 | 1.000 | ok |
| preview_toon_m0_r90.png | toon | 0.0 | 0.9 | 0.4454 | 0.3603 | 0.000 | 1.000 | ok |
| preview_toon_m1_r90.png | toon | 1.0 | 0.9 | 0.4454 | 0.3603 | 0.000 | 1.000 | ok |
| preview_posterize_m0_r10.png | posterize | 0.0 | 0.1 | 0.4322 | 0.3598 | 0.000 | 1.000 | ok |
| preview_posterize_m1_r10.png | posterize | 1.0 | 0.1 | 0.4210 | 0.3592 | 0.000 | 1.000 | ok |
| preview_posterize_m0_r90.png | posterize | 0.0 | 0.9 | 0.4315 | 0.3595 | 0.000 | 1.000 | ok |
| preview_posterize_m1_r90.png | posterize | 1.0 | 0.9 | 0.4215 | 0.3570 | 0.000 | 1.000 | ok |
| preview_neon_m0_r10.png | neon | 0.0 | 0.1 | 0.4411 | 0.3699 | 0.000 | 1.000 | ok |
| preview_neon_m1_r10.png | neon | 1.0 | 0.1 | 0.4411 | 0.3699 | 0.000 | 1.000 | ok |
| preview_neon_m0_r90.png | neon | 0.0 | 0.9 | 0.4411 | 0.3699 | 0.000 | 1.000 | ok |
| preview_neon_m1_r90.png | neon | 1.0 | 0.9 | 0.4411 | 0.3699 | 0.000 | 1.000 | ok |
| preview_blueprint_m0_r10.png | blueprint | 0.0 | 0.1 | 0.4314 | 0.3534 | 0.031 | 1.000 | ok |
| preview_blueprint_m1_r10.png | blueprint | 1.0 | 0.1 | 0.4314 | 0.3534 | 0.031 | 1.000 | ok |
| preview_blueprint_m0_r90.png | blueprint | 0.0 | 0.9 | 0.4314 | 0.3534 | 0.031 | 1.000 | ok |
| preview_blueprint_m1_r90.png | blueprint | 1.0 | 0.9 | 0.4314 | 0.3534 | 0.031 | 1.000 | ok |
| preview_clay_m0_r10.png | clay | 0.0 | 0.1 | 0.4591 | 0.3624 | 0.031 | 1.000 | ok |
| preview_clay_m1_r10.png | clay | 1.0 | 0.1 | 0.4591 | 0.3624 | 0.031 | 1.000 | ok |
| preview_clay_m0_r90.png | clay | 0.0 | 0.9 | 0.4591 | 0.3624 | 0.031 | 1.000 | ok |
| preview_clay_m1_r90.png | clay | 1.0 | 0.9 | 0.4591 | 0.3624 | 0.031 | 1.000 | ok |

Not-black/not-white check (0.05 <= mean <= 0.95, std > 0.02): **24/24 pass**.

## Metallic / roughness live override (PBR)

| combo pair | Δ pixel mean abs |
|---|---|
| pbr_m0_r10 vs pbr_m1_r10 | 0.01382 |
| pbr_m0_r10 vs pbr_m0_r90 | 0.00209 |
| pbr_m0_r10 vs pbr_m1_r90 | 0.01232 |
| pbr_m1_r10 vs pbr_m0_r90 | 0.01492 |
| pbr_m1_r10 vs pbr_m1_r90 | 0.01160 |
| pbr_m0_r90 vs pbr_m1_r90 | 0.01134 |

Every pair differs, so both sliders change the frame; the artistic styles intentionally ignore the PBR overrides.

## Style separation (metallic=1, roughness=0.1)

| pair | Δ mean RGB | Δ pixel mean abs |
|---|---|---|
| pbr|toon | 0.0439 | 0.02877 |
| pbr|posterize | 0.0015 | 0.01045 |
| pbr|neon | 0.0366 | 0.05018 |
| pbr|blueprint | 0.0197 | 0.02691 |
| pbr|clay | 0.0673 | 0.03980 |
| toon|posterize | 0.0423 | 0.02719 |
| toon|neon | 0.0073 | 0.04764 |
| toon|blueprint | 0.0242 | 0.03174 |
| toon|clay | 0.0235 | 0.02108 |
| posterize|neon | 0.0350 | 0.05177 |
| posterize|blueprint | 0.0182 | 0.02812 |
| posterize|clay | 0.0658 | 0.04126 |
| neon|blueprint | 0.0169 | 0.03780 |
| neon|clay | 0.0308 | 0.03395 |
| blueprint|clay | 0.0476 | 0.02831 |

Smallest mean-colour distance: **0.0015**; smallest per-pixel distance: **0.01045** (per-pixel values prove the images differ, not only their averages).

## Lighting API

`set_lighting(**params)` accepts dicts or keywords; every entry below was applied alone (all other lights untouched) and changed the frame:

| param | applied | Δmean RGB | Δ pixel | changed |
|---|---|---|---|---|
| key_azimuth | {"key_dir": {"azimuth": 250.0}} | 0.0097 | 0.01155 | True |
| key_elevation | {"key_dir": {"elevation": 8.0}} | 0.0074 | 0.01072 | True |
| key_intensity | {"key_dir": {"intensity": 6.5}} | 0.0063 | 0.00486 | True |
| key_color | {"key_dir": {"color": [0.35, 0.55, 1.0]}} | 0.0040 | 0.00340 | True |
| key_angle | {"key_dir": {"angle": 0.45}} | 0.0043 | 0.00430 | True |
| fill_dir | {"fill_dir": {"azimuth": 95.0, "elevation": -10.0}} | 0.0014 | 0.00885 | True |
| fill_intensity | {"fill_dir": {"intensity": 0.0}} | 0.0053 | 0.00413 | True |
| fill_color | {"fill_dir": {"color": [0.2, 1.0, 0.35]}} | 0.0016 | 0.00205 | True |
| rim_dir | {"rim_dir": {"azimuth": 5.0, "elevation": 70.0}} | 0.0014 | 0.00700 | True |
| rim_intensity | {"rim_dir": {"intensity": 6.0}} | 0.0021 | 0.00155 | True |
| rim_color | {"rim_dir": {"color": [0.25, 0.9, 1.0]}} | 0.0003 | 0.00062 | True |
| ambient_top | {"ambient_top": [0.55, 0.18, 0.1]} | 0.0011 | 0.00437 | True |
| ambient_bottom | {"ambient_bottom": [0.02, 0.12, 0.4]} | 0.0005 | 0.00227 | True |
| ambient_dict | {"ambient": {"top": [0.05, 0.35, 0.18], "bottom": [0.3, 0.05, 0.05]}} | 0.0020 | 0.00288 | True |
| env_intensity | {"env_intensity": 2.5} | 0.0107 | 0.00823 | True |
| shadow_off | {"shadow": false} | 0.0000 | 0.00000 | False |

Flat keys also work: `key_azimuth`, `key_elevation`, `key_intensity`, `key_color`, `key_angle`, `fill_*`, `rim_*`, `ambient_top`, `ambient_bottom`, `ambient_intensity`, `env_intensity`, `shadow`. `shadow` only changes frames that contain a shadow receiver (see the Shadows section).

## Shadows (PCF 3x3, 2048x2048 map)

- floor receiver, shadows on: mean 0.5899491310119629, std 0.33577629923820496
- floor receiver, shadows off: mean 0.5950588583946228, std 0.3388550579547882
- Δmean RGB on/off: **0.00877**; Δ pixel mean abs: **0.00701**, changed pixels (>2%): **0.05001** (visible: True)
- captures: `render/preview_shadow_on.png`, `render/preview_shadow_off.png`

## Styles

- `pbr`: Cook-Torrance GGX + Smith + Schlick, analytic sky IBL, soft PCF shadow
- `toon`: 3-band cel shading + rim + inverted-hull outline (`scene.vert` normal push, `outline.frag`)
- `posterize`: gamma-domain colour quantisation + hue rotation
- `neon`: dark body + electric rim glow + scanlines
- `blueprint`: monochrome blue + UV grid + fresnel edge
- `clay`: matte white-clay, no maps, wrapped lambert

## Performance (1280x720, MSAA 4x, PCF shadow map 2048x2048)

- draw only: median **6.06 ms** (mean 6.162 ms, p95 7.556 ms, 162.3 fps)
- with glReadPixels readback: median **9.318 ms** (mean 10.082 ms, p95 13.373 ms)
- mesh: 1271 vertices / 2364 triangles, `prepare_lod` 1.472 ms

- Measured while other build jobs saturated this 4-core i5-10200H (100% CPU), so absolute numbers swing 2-3x between runs; an earlier run of this same build measured median 5.61 ms draw-only / 12.73 ms with readback. The `huge_100k` stability outlier is dominated by CPU-side `prepare_lod` on first upload.

## Stability

| case | ok | mean | std | render ms | notes |
|---|---|---|---|---|---|
| no_mesh | True | 0.4434 | 0.3411 | 5.46 |  |
| empty_mesh | True | 0.4434 | 0.3411 | 3.59 |  |
| single_triangle | True | 0.4805 | 0.3529 | 7.16 |  |
| missing_textures | True | 0.4617 | 0.3485 | 7.97 |  |
| huge_100k | True | 0.4759 | 0.3527 | 196.86 | vertices=101541 triangles=201600 prepare_lod_ms=132.75 |
| set_mesh_none_after | True | 0.4434 | 0.3411 | 6.11 |  |
| variant_wireframe | True | 0.4379 | 0.3506 | 19.03 |  |
| variant_bg_gradient | True | 0.5234 | 0.3090 | 14.69 |  |
| variant_bg_dark | True | 0.3367 | 0.4018 | 13.79 |  |
| variant_exposure_-2 | True | 0.2882 | 0.4175 | 14.61 |  |
| variant_exposure_+2 | True | 0.6356 | 0.2767 | 17.14 |  |
| variant_style_clay | True | 0.4812 | 0.3540 | 7.77 |  |

## MeshViewer widget API

- calls: `{"set_lod": "ok", "set_material_override": "ok", "set_material_override_none": "ok", "set_texture_override": "ok", "set_texture_override_clear": "ok", "set_lighting": "ok", "set_style": "ok", "set_exposure": "ok", "set_background": "ok", "set_wireframe": "ok", "set_wireframe_off": "ok", "reset_camera": "ok", "frame_all": "ok"}`
- invalid style raises ValueError: `True`
- `capture()`: `{"path": "render/preview_widget_capture.png", "mean": 0.4293, "std": 0.16, "mean_lum": 0.3864, "std_lum": 0.1313, "min": 0.0, "max": 0.9843, "p01": 0.1098, "p99": 0.8824}`

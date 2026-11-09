"""在 Blender 里导入我们导出的 .obj/.mtl，渲染一张图（验证 UV 有没有翻错）。"""
import bpy, sys, os, math

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
obj_path = argv[0]
out_png = argv[1]
override_tex = argv[2] if len(argv) > 2 else None

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=obj_path)
ob = [o for o in bpy.data.objects if o.type == "MESH"][0]
print("imported", ob.name, len(ob.data.vertices), len(ob.data.polygons),
      "uv_layers", [l.name for l in ob.data.uv_layers])
for m in bpy.data.materials:
    print("mat", m.name, "use_nodes", m.use_nodes)
    if m.use_nodes:
        for n in m.node_tree.nodes:
            print("  node", n.type, getattr(getattr(n, "image", None), "name", ""))
            for inp in n.inputs:
                if inp.is_linked:
                    print("   link", inp.name, "<-", inp.links[0].from_node.type)

# 可选：把材质里的底图换成指定的调试贴图（UV 对照用）
if override_tex:
    img = bpy.data.images.load(override_tex)
    for m in bpy.data.materials:
        if not m.use_nodes:
            m.use_nodes = True
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        tex_node = next((n for n in m.node_tree.nodes if n.type == "TEX_IMAGE"), None)
        if bsdf is None:
            continue
        if tex_node is None:
            tex_node = m.node_tree.nodes.new("ShaderNodeTexImage")
            m.node_tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
        tex_node.image = img
        print("override texture ->", override_tex, "on", m.name)

# 可选：扁平模式（自发光 = 纯贴图颜色），排除光照干扰，专看 UV 对不对
if os.environ.get("BLENDER_FLAT"):
    for m in bpy.data.materials:
        if not m.use_nodes:
            m.use_nodes = True
        nt = m.node_tree
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        tex_node = next((n for n in nt.nodes if n.type == "TEX_IMAGE"), None)
        out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
        emis = nt.nodes.new("ShaderNodeEmission")
        if tex_node is not None:
            nt.links.new(tex_node.outputs["Color"], emis.inputs["Color"])
        if out is not None:
            nt.links.new(emis.outputs["Emission"], out.inputs["Surface"])
        print("flat emission for", m.name)

# 相机
cam_data = bpy.data.cameras.new("C")
cam = bpy.data.objects.new("C", cam_data)
bpy.context.scene.collection.objects.link(cam)
bpy.context.scene.camera = cam
# 取景
import mathutils
bb = [ob.matrix_world @ mathutils.Vector(c) for c in ob.bound_box]
center = sum(bb, mathutils.Vector()) / 8.0
radius = max((v - center).length for v in bb)
cam_data.lens = 50
sensor = cam_data.sensor_width
fov = 2 * math.atan(sensor / (2 * cam_data.lens))
dist = radius / math.tan(fov / 2) * 1.25
cam.location = center + mathutils.Vector((dist * 0.62, -dist * 0.72, dist * 0.32))
direction = center - cam.location
cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

# 世界环境光（不然背光面全黑）
world = bpy.data.worlds.new("W")
scene_world = bpy.context.scene
scene_world.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg:
    bg.inputs[0].default_value = (0.55, 0.57, 0.62, 1.0)
    bg.inputs[1].default_value = 1.0

# 灯
light_data = bpy.data.lights.new("L", type="AREA")
light_data.energy = 60 * max(radius, 0.2) ** 2
light = bpy.data.objects.new("L", light_data)
light.location = center + mathutils.Vector((radius * 2, -radius * 2, radius * 3))
bpy.context.scene.collection.objects.link(light)

scene = bpy.context.scene
scene.render.image_settings.file_format = "PNG"
scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in \
    [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
scene.render.resolution_x = 700
scene.render.resolution_y = 700
scene.render.film_transparent = False
scene.render.filepath = out_png
scene.view_settings.view_transform = "Standard"
bpy.ops.render.render(write_still=True)
print("wrote", out_png)

import bpy, sys, json

out = []
out.append(f"blender={bpy.app.version_string} file={bpy.data.filepath}")

for img in bpy.data.images:
    out.append(f"IMG {img.name!r} filepath={img.filepath!r} size={tuple(img.size)}")
for ob in bpy.data.objects:
    if ob.type == "MESH":
        slots = [s.material.name if s.material else None for s in ob.material_slots]
        out.append(f"OBJ {ob.name!r} verts={len(ob.data.vertices)} polys={len(ob.data.polygons)} "
                   f"uv_layers={[l.name for l in ob.data.uv_layers]} slots={slots}")

for mat in bpy.data.materials:
    if not mat.use_nodes or mat.node_tree is None:
        out.append(f"MAT {mat.name!r} (no nodes)")
        continue
    nt = mat.node_tree
    out.append(f"MAT {mat.name!r} nodes={len(nt.nodes)}")
    for n in nt.nodes:
        extra = ""
        if n.type == "TEX_IMAGE":
            extra = f" image={getattr(n.image, 'name', None)!r} interp={n.interpolation} proj={n.projection} ext={n.extension}"
        if n.type == "BSDF_PRINCIPLED":
            vals = {}
            for sock in n.inputs:
                if sock.is_linked:
                    continue
                try:
                    v = sock.default_value
                    vals[sock.name] = list(v) if hasattr(v, "__len__") else float(v)
                except Exception:
                    pass
            extra = f" defaults={json.dumps(vals, ensure_ascii=False)}"
        out.append(f"  NODE {n.type} {n.name!r} label={n.label!r}{extra}")
    for lk in nt.links:
        out.append(f"  LINK {lk.from_node.name}[{lk.from_socket.name}] -> {lk.to_node.name}[{lk.to_socket.name}]")

print("\n".join(out))

"""诊断：为什么某个资产的贴图没贴上（材质路径 vs bundle.textures 的键比对）。

    python tools/diag_tex.py <资产名或vpath>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import loader

VPATH = sys.argv[1] if len(sys.argv) > 1 else ""


def main():
    idx = loader.index()
    name = os.path.basename(VPATH)
    hits = [k for k in idx if k.endswith("/" + name)] if name else []
    target = hits[0] if hits else VPATH
    print("target", target)
    bnd = loader.load_model(target, lod=0, want_textures=True, want_cn=False)
    mesh = bnd.mesh
    print("mesh", mesh.name if mesh else None, "lods", len(mesh.lods) if mesh else 0)
    tex_paths = {}
    for t in bnd.textures or []:
        tex_paths[str(t.pak_path)] = t
        print("TEX", t.name, "|", t.pak_path, "|",
              None if t.rgba is None else getattr(t.rgba, "shape", None))
    for m in bnd.materials:
        print("MAT", m.name, "parent", getattr(m, "parent", ""))
        for slot in ("base_color_texture", "normal_texture", "orm_texture", "emissive_texture"):
            p = getattr(m, slot, "") or ""
            hit = tex_paths.get(str(p))
            if hit is None:
                base = os.path.basename(str(p))
                hit = next((t for t in (bnd.textures or [])
                            if os.path.basename(str(t.pak_path)) == base), None)
            print(f"   {slot:20s} {p}  -> {'OK' if hit else 'MISS'}"
                  f"{'' if hit else '  bundle 里有: ' + str([t.name for t in (bnd.textures or [])])}")
    if mesh and mesh.lods:
        lod = mesh.lods[0]
        print("sections", [(s.material_path.rsplit('/', 1)[-1], s.num_triangles) for s in lod.sections])
        print("uv channels", getattr(lod, "uv_channel_count", "?"))


if __name__ == "__main__":
    main()

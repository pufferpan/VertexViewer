"""`.uemodel` —— 几何优先的两段式导出。

用户要的流程是「先导出模型（几何），再上材质」，所以：

* **第一段**：`export_uemodel(bundle, path)` 只写几何 + 材质槽的**名字**，不碰贴图。
  产物是单个 `.uemodel`（JSON，浮点数组 base64 存 float32），可以直接拷给别的工具；
* **第二段**：`load_uemodel(path)` 读回来变成 `ModelBundle`（材质仍是空壳），
  再交给 `materialize()` 用游戏的材质/贴图资产把槽填上，最后走 `exporters.obj` 出 OBJ+MTL。

命令行：

    python -m exporters.uemodel "Models/.../X.uasset" out.uemodel
    python -m exporters.uemodel out.uemodel --materialize out_dir
"""

from __future__ import annotations

import base64
import json
import os
import struct
from typing import Any, Dict, List, Optional

import numpy as np

from core.types import Material, Mesh, MeshLOD, ModelBundle, Section

FORMAT = "vertexviewer.uemodel"
VERSION = 1

_ARRAYS = {
    "positions": 3,
    "normals": 3,
    "uvs": 2,
    "tangents": 4,
}


def _enc(arr) -> Optional[str]:
    if arr is None:
        return None
    a = np.asarray(arr, dtype=np.float32)
    if a.size == 0:
        return ""
    return base64.b64encode(a.tobytes(order="C")).decode("ascii")


def _dec(text: Optional[str], width: int) -> np.ndarray:
    if not text:
        return np.zeros((0, width), np.float32)
    raw = base64.b64decode(text.encode("ascii"))
    a = np.frombuffer(raw, dtype=np.float32)
    return a.reshape(-1, width).copy()


def export_uemodel(bundle: ModelBundle, path: str, *, lod: int = 0) -> Dict[str, Any]:
    """把 `bundle` 的第 `lod` 级几何写成 `.uemodel`；返回统计。"""
    if bundle is None or bundle.mesh is None:
        raise ValueError("bundle has no mesh")
    mesh = bundle.mesh
    index = max(0, min(int(lod), len(mesh.lods) - 1))
    lods: List[Dict[str, Any]] = []
    for li, l in enumerate(mesh.lods):
        lods.append(
            {
                "positions": _enc(l.positions),
                "normals": _enc(l.normals),
                "uvs": _enc(l.uvs),
                "tangents": _enc(l.tangents),
                "indices": base64.b64encode(
                    np.asarray(l.indices, dtype=np.uint32).tobytes()).decode("ascii"),
                "index_count": int(np.asarray(l.indices).size),
                "sections": [
                    {
                        "material_path": s.material_path,
                        "first_index": int(s.first_index),
                        "num_triangles": int(s.num_triangles),
                        "first_vertex": int(s.first_vertex),
                        "num_vertices": int(s.num_vertices),
                        "index_base": int(getattr(s, "index_base", 0)),
                    }
                    for s in (l.sections or [])
                ],
                "bone_weights": _enc(l.bone_weights) if getattr(l, "bone_weights", None) is not None else None,
            }
        )

    doc = {
        "format": FORMAT,
        "version": VERSION,
        "name": mesh.name,
        "pak_path": mesh.pak_path,
        "source_format": mesh.source_format,
        "display_name": bundle.display_name,
        "display_name_cn": bundle.display_name_cn,
        "icon_path": bundle.icon_path,
        "bounds_center": list(map(float, mesh.bounds_center)) if mesh.bounds_center is not None else None,
        "bounds_extent": list(map(float, mesh.bounds_extent)) if mesh.bounds_extent is not None else None,
        "lod_index": index,
        "lods": lods,
        # 材质只留引用，真正的贴图在第二段“上材质”时解析
        "materials": [
            {
                "name": m.name,
                "pak_path": m.pak_path,
                "parent": m.parent,
                "metallic": float(m.metallic or 0.0),
                "roughness": float(m.roughness or 0.0),
                "base_color": list(m.base_color) if m.base_color is not None else None,
                "base_color_texture": m.base_color_texture,
                "normal_texture": m.normal_texture,
                "orm_texture": m.orm_texture,
                "emissive_texture": m.emissive_texture,
                "two_sided": bool(m.two_sided),
                "blend_mode": m.blend_mode,
            }
            for m in (bundle.materials or [])
        ],
    }

    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))
    lod0 = mesh.lods[index]
    return {
        "path": path,
        "bytes": os.path.getsize(path),
        "verts": int(len(np.asarray(lod0.positions))),
        "tris": int(np.asarray(lod0.indices).size // 3),
        "lods": len(mesh.lods),
        "materials": len(doc["materials"]),
    }


def _read(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    if doc.get("format") != FORMAT:
        raise ValueError(f"not a {FORMAT} file: {path}")
    return doc


def load_uemodel(path: str) -> ModelBundle:
    """读回 `.uemodel`；材质是「只有引用」的空壳，等 `materialize()` 填。"""
    doc = _read(path)
    lods: List[MeshLOD] = []
    for entry in doc.get("lods", []):
        count = int(entry.get("index_count") or 0)
        raw = base64.b64decode((entry.get("indices") or "").encode("ascii"))
        indices = np.frombuffer(raw, dtype=np.uint32).copy() if count else np.zeros(0, np.uint32)
        sections = [
            Section(
                material_path=s.get("material_path"),
                first_index=int(s.get("first_index") or 0),
                num_triangles=int(s.get("num_triangles") or 0),
                first_vertex=int(s.get("first_vertex") or 0),
                num_vertices=int(s.get("num_vertices") or 0),
                index_base=int(s.get("index_base") or 0),
            )
            for s in (entry.get("sections") or [])
        ]
        lods.append(
            MeshLOD(
                positions=_dec(entry.get("positions"), 3),
                normals=_dec(entry.get("normals"), 3),
                uvs=_dec(entry.get("uvs"), 2),
                tangents=_dec(entry.get("tangents"), 4),
                indices=indices,
                sections=sections,
                bone_weights=None,
                bone_indices=None,
                bones=[],
            )
        )
    mesh = Mesh(
        name=doc.get("name") or os.path.splitext(os.path.basename(path))[0],
        pak_path=doc.get("pak_path") or "",
        lods=lods,
        bounds_center=tuple(doc["bounds_center"]) if doc.get("bounds_center") else None,
        bounds_extent=tuple(doc["bounds_extent"]) if doc.get("bounds_extent") else None,
        source_format=doc.get("source_format") or FORMAT,
    )
    materials = [
        Material(
            name=m.get("name") or "",
            pak_path=m.get("pak_path") or "",
            parent=m.get("parent") or "",
            metallic=float(m.get("metallic") or 0.0),
            roughness=float(m.get("roughness") or 0.0),
            base_color=tuple(m["base_color"]) if m.get("base_color") else None,
            base_color_texture=m.get("base_color_texture") or "",
            normal_texture=m.get("normal_texture") or "",
            orm_texture=m.get("orm_texture") or "",
            emissive_texture=m.get("emissive_texture") or "",
            two_sided=bool(m.get("two_sided")),
            blend_mode=m.get("blend_mode"),
        )
        for m in (doc.get("materials") or [])
    ]
    return ModelBundle(
        mesh=mesh,
        materials=materials,
        textures=[],
        display_name=doc.get("display_name"),
        display_name_cn=doc.get("display_name_cn"),
        icon_path=doc.get("icon_path"),
    )


def materialize(bundle: ModelBundle, *, want_textures: bool = True) -> ModelBundle:
    """第二段：把 `.uemodel` 的材质引用重新解析成真实材质 + 贴图。"""
    from core import loader

    if bundle is None or bundle.mesh is None:
        return bundle
    vpath = bundle.mesh.pak_path
    if not vpath:
        return bundle
    mats = list(bundle.materials or [])
    if not mats or all(not (m.base_color_texture or m.orm_texture) for m in mats):
        mats = loader.load_materials_for(bundle.mesh, vpath) or mats
    if want_textures:
        bundle.textures = loader.load_textures_for(mats)
    bundle.materials = mats
    if not bundle.display_name_cn:
        try:
            from core import cnnames

            bundle.display_name_cn = cnnames.resolve_cn(vpath)
        except Exception:                                   # noqa: BLE001
            pass
    try:
        from core import icons

        bundle.icon_path = bundle.icon_path or icons.icon_for(vpath)
    except Exception:                                       # noqa: BLE001
        pass
    return bundle


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="uemodel", description="导出/读取 .uemodel")
    ap.add_argument("source", help="游戏内资产路径（.uasset）或已存在的 .uemodel")
    ap.add_argument("target", nargs="?", help="输出 .uemodel 路径")
    ap.add_argument("--lod", type=int, default=0)
    ap.add_argument("--materialize", metavar="DIR", help="读 .uemodel 后上材质并导出 OBJ 到 DIR")
    args = ap.parse_args(argv)

    from core import loader

    if args.source.lower().endswith(".uemodel"):
        bundle = load_uemodel(args.source)
        print(f"[uemodel] loaded {bundle.mesh.name}: {len(bundle.mesh.lods)} LOD, "
              f"{len(bundle.materials)} materials")
        if args.materialize:
            bundle = materialize(bundle)
            from exporters import obj as obj_export

            out = os.path.join(args.materialize, bundle.mesh.name + ".obj")
            stats = obj_export.export_obj(bundle, out, lod=args.lod)
            print(f"[uemodel] materialized -> {stats}")
        return 0

    bundle = loader.load_model(args.source, want_textures=False)
    if bundle is None or bundle.mesh is None:
        raise SystemExit(f"[uemodel] 找不到可解析的网格：{args.source}\n"
                         f"    资产路径要写成 fileindex 里的完整路径，"
                         f"例如 '../../../DeltaForce/Content/Models/.../X.uasset'")
    target = args.target or (os.path.splitext(os.path.basename(args.source))[0] + ".uemodel")
    stats = export_uemodel(bundle, target, lod=args.lod)
    print(f"[uemodel] {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

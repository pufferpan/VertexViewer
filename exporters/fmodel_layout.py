"""按 FModel 的导出口径把「模型 + 材质 + 贴图」摆成一个目录树。

FModel 导出时并不是把贴图丢到一个大杂烩目录里，而是**照包路径还原**：

```
<out>/DeltaForce/Content/Models/Weapons/Parts/Mag/Mag_AK74_.../SM_Mag_....uemodel
<out>/DeltaForce/Content/Models/Weapons/Parts/Mag/Mag_AK74_.../SM_Mag_....json
<out>/GenTexDirHD/Game/Models/Weapons/Parts/Mag/Mag_AK74_.../Textures/T_VMGen_BaseColorMap_xxx.png
```

于是「材质用哪张贴图」这件事变成了纯目录查找 —— 模型所在目录 + 材质所在目录，
不需要任何跨目录猜名字。本模块就干这一件事；查看器的 `loader` 也走同一套语义
（`loader.STRICT_DIRS = True`），所以**导出结果和实时预览一致**。

用法：

    python -m exporters.fmodel_layout "DeltaForce/Content/Models/.../SM_X.uasset" out/
    python -m exporters.fmodel_layout --list 20 out/     # 抽样 20 个模型批量导
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Dict, List, Optional

if __package__ in (None, ""):                       # 允许直接跑文件
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _rel(vpath: str) -> str:
    """`../../../DeltaForce/Content/x.uasset` -> `DeltaForce/Content/x.uasset`。"""
    p = str(vpath).replace("\\", "/")
    while p.startswith("../"):
        p = p[3:]
    return p.lstrip("/")


def _stem(vpath: str) -> str:
    return os.path.basename(str(vpath)).split(".")[0]


def _dir_of(vpath: str) -> str:
    return os.path.dirname(str(vpath))


def _safe(name: str) -> str:
    return re.sub(r'[<>:"|?*]', "_", name)


def _material_json(mat, model_vpath: str, tex_paths: Dict[str, str]) -> dict:
    """材质描述，字段名对齐 FModel 的 `*.json`（够用、可读、可再导入）。"""
    out: Dict[str, object] = {
        "name": getattr(mat, "name", "") or _stem(model_vpath),
        "objectPath": str(getattr(mat, "pak_path", "") or ""),
        "parent": str(getattr(mat, "parent", "") or ""),
        "shadingModel": str(getattr(mat, "shading_model", "DefaultLit") or "DefaultLit"),
        "twoSided": bool(getattr(mat, "two_sided", False)),
        "blendMode": str(getattr(mat, "blend_mode", "Opaque") or "Opaque"),
        "scalarParameters": {str(k): float(v) for k, v in
                             (getattr(mat, "scalar_params", {}) or {}).items()},
        "vectorParameters": {str(k): list(v) for k, v in
                             (getattr(mat, "vector_params", {}) or {}).items()},
        "textures": {},
    }
    for slot, key in (("base_color_texture", "BaseColor"),
                      ("normal_texture", "Normal"),
                      ("orm_texture", "MRA"),
                      ("emissive_texture", "Emissive"),
                      ("roughness_texture", "Roughness"),
                      ("metallic_texture", "Metallic")):
        ref = getattr(mat, slot, "") or ""
        if ref:
            out["textures"][key] = tex_paths.get(ref, _rel(ref))
    return out


def export_tree(bundle, outdir: str, vpath: str, *, write_obj: bool = True) -> Dict[str, object]:
    """把 `bundle` 按 FModel 的目录结构落盘，返回统计信息。"""
    from core import loader
    from exporters import uemodel as ue

    rel = _rel(vpath)
    folder = os.path.join(outdir, os.path.dirname(rel))
    os.makedirs(folder, exist_ok=True)
    stem = _safe(_stem(vpath))

    written: List[str] = []

    # 1) 几何：先出 .uemodel（这就是「先导出模型」那一步，跟材质完全解耦）
    #    格式用真正的 UEFormat（FModel / DeltaModelViewer 同一套二进制规范），
    #    这样导出的文件可以直接丢给 DeltaModelViewer 打开对照。
    model_path = os.path.join(folder, stem + ".uemodel")
    try:
        from exporters import ueformat as uef
        uef.export_uemodel(bundle, model_path)
    except Exception as exc:                                   # noqa: BLE001
        print(f"[export] ueformat 失败，退回自有 JSON：{exc}")
        ue.export_uemodel(bundle, model_path, lod=0)
    written.append(model_path)

    # 2) 贴图：按**它自己的包路径**还原，和 FModel 一模一样
    tex_paths: Dict[str, str] = {}
    for tex in getattr(bundle, "textures", []) or []:
        pack = getattr(tex, "pak_path", "") or ""
        if pack:
            target_rel = os.path.splitext(_rel(pack))[0] + ".png"
        else:
            target_rel = f"Textures/{_safe(tex.name)}.png"
        target = os.path.join(outdir, target_rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            from core.texture import save_png
            save_png(tex, target)
            written.append(target)
        except Exception as exc:                        # noqa: BLE001
            print(f"[fmodel] texture {tex.name}: {exc}", file=sys.stderr)
            continue
        tex_paths[pack or tex.name] = os.path.relpath(target, folder).replace("\\", "/")
        # 材质里存的是裸资产名，这里同时按裸名登记，json 里才好写成相对路径
        bare = os.path.splitext(os.path.basename(str(pack or tex.name)))[0]
        tex_paths.setdefault(bare, tex_paths[pack or tex.name])
        tex_paths.setdefault(str(getattr(tex, "name", "") or ""), tex_paths[pack or tex.name])

    # 3) 材质 json：贴图引用用**相对模型目录的路径**
    mats = [_material_json(m, vpath, tex_paths) for m in (bundle.materials or [])]
    mat_path = os.path.join(folder, stem + ".json")
    with open(mat_path, "w", encoding="utf-8") as fh:
        json.dump({"asset": _rel(vpath), "materials": mats}, fh, ensure_ascii=False, indent=2)
    written.append(mat_path)

    # 4) OBJ/MTL（可选，方便丢进 Blender）
    if write_obj:
        try:
            from exporters import obj as objexp
            res = objexp.export_obj(bundle, os.path.join(folder, stem + ".obj"))
            for key in ("obj", "mtl"):
                if isinstance(res, dict) and res.get(key):
                    written.append(str(res[key]))
        except Exception as exc:                        # noqa: BLE001
            print(f"[fmodel] obj: {exc}", file=sys.stderr)

    return {
        "vpath": _rel(vpath),
        "folder": folder,
        "files": len(written),
        "textures": len({v for v in tex_paths.values()}),
        "materials": len(mats),
        "triangles": sum(len(l.indices) // 3 for l in (bundle.mesh.lods or [])[:1]),
    }


def export_many(vpaths: List[str], outdir: str, **kw) -> List[Dict[str, object]]:
    from core import loader
    out = []
    for v in vpaths:
        try:
            bundle = loader.load_model(v)
            if not bundle or not bundle.mesh:
                continue
            out.append(export_tree(bundle, outdir, v, **kw))
        except Exception as exc:                        # noqa: BLE001
            print(f"[fmodel] {v}: {exc}", file=sys.stderr)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from core import loader

    limit = 0
    if argv and argv[0] == "--list":
        argv.pop(0)
        limit = int(argv.pop(0)) if argv else 20
    if len(argv) < 2:
        print(__doc__)
        return 2
    target, outdir = argv[0], argv[1]
    loader.set_strict_dirs(True)

    if limit:
        models = loader.list_models("Models/")[:limit]
        rows = export_many(models, outdir)
    else:
        vpath = target
        if vpath not in loader.index():
            hits = [k for k in loader.index() if k.endswith("/" + target)
                    or k.endswith("/" + target + ".uasset")]
            if not hits:
                raise SystemExit(f"资产不存在: {target}")
            vpath = hits[0]
        bundle = loader.load_model(vpath)
        if not bundle or not bundle.mesh:
            raise SystemExit(f"这个资产没有网格: {vpath}")
        rows = [export_tree(bundle, outdir, vpath)]

    for row in rows:
        print(f"{row['vpath']}: {row['files']} 文件 / {row['textures']} 贴图 / "
              f"{row['materials']} 材质 / {row['triangles']} tris -> {row['folder']}")
    print(f"共 {len(rows)} 个模型，输出目录 {os.path.abspath(outdir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

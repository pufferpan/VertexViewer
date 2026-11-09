"""Separate, socket-positioned OBJ parts; integrated from D:/VertexViewer.rar source_patch.

The original runtime monkey patch is replaced by a direct GunsmithPage action.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from core import gunsmith as gs
from core.types import Mesh, ModelBundle
from exporters.obj import export_obj


_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_name(value: str, fallback: str) -> str:
    text = _SAFE.sub("_", str(value or "")).strip("._")
    return (text or fallback)[:72]


def _as_list(value: Any, length: Optional[int] = None) -> List[float]:
    try:
        result = [float(item) for item in value]
    except Exception:
        result = []
    if length is not None:
        result = (result + [0.0] * length)[:length]
    return result


def _matrix_list(matrix: Any) -> List[List[float]]:
    array = np.asarray(matrix, dtype=np.float32)
    return [[float(item) for item in row] for row in array.tolist()]


def _part_bundle(
    source: ModelBundle,
    lod: Any,
    name: str,
    name_cn: str,
) -> ModelBundle:
    """Wrap a transformed LOD while preserving the source materials/textures."""
    return ModelBundle(
        mesh=Mesh(name=name, lods=[lod]),
        materials=list(getattr(source, "materials", None) or []),
        textures=list(getattr(source, "textures", None) or []),
        display_name=name,
        display_name_cn=name_cn or name,
        icon_path=getattr(source, "icon_path", ""),
        material_note=getattr(source, "material_note", ""),
    )


def _compose_part_matrix(spec: Any, world: Any) -> Tuple[np.ndarray, float]:
    """Match core.gunsmith.assemble()'s transform order exactly."""
    matrix = np.asarray(world, dtype=np.float32).copy()
    stretch = gs.part_offset(spec.vpath)
    if float(np.max(np.abs(stretch))) > 1e-6:
        matrix = matrix @ gs._trs((0.0, 0.0, 0.0), stretch)
    offset = _as_list(getattr(spec, "offset", (0.0, 0.0, 0.0)), 3)
    if any(abs(value) > 1e-9 for value in offset):
        matrix = matrix @ gs._trs((0.0, 0.0, 0.0), offset)
    rotation = _as_list(getattr(spec, "rot", (0.0, 0.0, 0.0)), 3)
    if any(abs(value) > 1e-9 for value in rotation):
        matrix = matrix @ gs._trs(tuple(rotation), (0.0, 0.0, 0.0))
    scale = float(getattr(spec, "scale", 1.0) or 1.0)
    return matrix, scale


def _iter_parts(
    base_bundle: ModelBundle,
    pairs: Sequence[Tuple[Any, Optional[ModelBundle]]],
    base_vpath: str,
) -> Iterable[Dict[str, Any]]:
    base_lod = gs._lod0(base_bundle)
    if base_lod is None:
        raise ValueError("主件没有可导出的 LOD0 网格")

    part_list: List[Tuple[Any, Any]] = []
    usable_pairs: List[Tuple[Any, ModelBundle, Any]] = []
    for spec, bundle in pairs:
        if bundle is None:
            continue
        lod = gs._lod0(bundle)
        if lod is None:
            continue
        part_list.append((spec, lod))
        usable_pairs.append((spec, bundle, lod))

    plan = gs.resolve_placements(base_vpath or "", base_lod, part_list)
    base_name = _safe_name(
        getattr(base_bundle, "display_name", "") or os.path.basename(base_vpath),
        "receiver",
    )
    yield {
        "kind": "base",
        "index": 0,
        "slot": "receiver",
        "slot_label": "Receiver",
        "vpath": base_vpath or "",
        "name": base_name,
        "name_cn": getattr(base_bundle, "display_name_cn", "") or base_name,
        "bundle": base_bundle,
        "lod": base_lod,
        "matrix": np.eye(4, dtype=np.float32),
        "scale": 1.0,
        "spec": None,
    }

    for index, (spec, bundle, lod) in enumerate(usable_pairs, start=1):
        world = plan.get(id(spec))
        if world is None:
            world = np.eye(4, dtype=np.float32)
        matrix, scale = _compose_part_matrix(spec, world)
        slot = str(getattr(spec, "slot", "") or "other")
        slot_info = gs.SLOT_BY_KEY.get(slot)
        slot_label = str(getattr(slot_info, "label", "") or slot)
        name = (
            getattr(spec, "name", "")
            or getattr(bundle, "display_name", "")
            or os.path.basename(getattr(spec, "vpath", ""))
        )
        name = _safe_name(name, f"part_{index:02d}")
        yield {
            "kind": "part",
            "index": index,
            "slot": slot,
            "slot_label": slot_label,
            "vpath": str(getattr(spec, "vpath", "") or ""),
            "name": name,
            "name_cn": str(getattr(spec, "name", "") or name),
            "bundle": bundle,
            "lod": lod,
            "matrix": matrix,
            "scale": scale,
            "spec": spec,
        }


def export_parts(
    base_bundle: ModelBundle,
    pairs: Sequence[Tuple[Any, Optional[ModelBundle]]],
    base_vpath: str,
    output_dir: str,
    stem: str,
) -> Dict[str, Any]:
    """Export the assembled recipe as one OBJ per component.

    The output directory receives one OBJ/MTL pair per component, a shared
    ``textures`` directory managed by the existing exporter, and a manifest
    describing the source asset and baked transform for every file.
    """
    if base_bundle is None:
        raise ValueError("没有主件")
    output_dir = os.path.abspath(os.fspath(output_dir))
    os.makedirs(output_dir, exist_ok=True)
    stem = _safe_name(stem, "gunsmith")
    manifest_path = os.path.join(output_dir, f"{stem}__parts_manifest.json")
    records: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    pairs = list(pairs)
    for spec, bundle in pairs:
        if gs._lod0(bundle) is None:
            errors.append({"slot": str(spec.slot), "name": str(spec.name),
                           "vpath": str(spec.vpath), "error": "配件没有可导出的 LOD0 网格"})

    for item in _iter_parts(base_bundle, pairs, base_vpath):
        filename = f"{stem}__{item['index']:02d}_{_safe_name(item['slot'], 'other')}_{item['name']}.obj"
        obj_path = os.path.join(output_dir, filename)
        source_bundle = item["bundle"]
        try:
            moved_lod = item["lod"]
            if item["kind"] == "part":
                moved_lod = gs._apply_matrix(
                    item["lod"],
                    item["matrix"],
                    item["scale"],
                )
            bundle = _part_bundle(
                source_bundle,
                moved_lod,
                item["name"],
                item["name_cn"],
            )
            # Same-named images in different parts must not overwrite each other.
            stats = export_obj(bundle, obj_path, mtl=True,
                               texture_prefix=f"part_{item['index']:02d}_")
            record = {
                "index": item["index"],
                "kind": item["kind"],
                "slot": item["slot"],
                "slot_label": item["slot_label"],
                "name": item["name"],
                "name_cn": item["name_cn"],
                "vpath": item["vpath"],
                "obj": os.path.basename(obj_path),
                "mtl": os.path.basename(os.path.splitext(obj_path)[0] + ".mtl"),
                "matrix": _matrix_list(item["matrix"]),
                "scale": float(item["scale"]),
                "offset": _as_list(
                    getattr(item["spec"], "offset", (0.0, 0.0, 0.0))
                    if item["spec"] is not None
                    else (0.0, 0.0, 0.0),
                    3,
                ),
                "rotation": _as_list(
                    getattr(item["spec"], "rot", (0.0, 0.0, 0.0))
                    if item["spec"] is not None
                    else (0.0, 0.0, 0.0),
                    3,
                ),
                "socket": str(
                    getattr(item["spec"], "socket", "")
                    if item["spec"] is not None
                    else ""
                ),
                "triangles": int(stats.get("f", 0)),
                "vertices": int(stats.get("v", 0)),
            }
            records.append(record)
        except Exception as exc:
            errors.append(
                {
                    "slot": item["slot"],
                    "name": item["name"],
                    "vpath": item["vpath"],
                    "error": str(exc),
                }
            )

    manifest = {
        "format": "VertexViewer gunsmith parts export",
        "version": 1,
        "base_vpath": base_vpath or "",
        "stem": stem,
        "output_dir": output_dir,
        "parts": records,
        "errors": errors,
    }
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    if not records:
        raise RuntimeError(f"没有成功导出部件；详情见 {manifest_path}")
    return {
        "output_dir": output_dir,
        "manifest": manifest_path,
        "parts": records,
        "errors": errors,
    }


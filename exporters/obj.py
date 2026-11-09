"""Wavefront OBJ exporter.

Contract (see the project brief):

    export_obj(bundle, path, *, lod=0, mtl=True, scale=1.0,
               axis='gl'|'ue', merge_sections=False, flip_uv=True)

What it guarantees
------------------
* `v` / `vt` / `vn` arrays are **de-duplicated independently**; face vertex
  references are `pos/uv/normal` triples with 1-based indices.
* One `o` group per exported LOD, one `usemtl` per mesh section.
* `vt` is omitted when the LOD has no UVs, `vn` when it has no normals.
* Reflections are written into a companion `.mtl` (`Kd`/`Ks`/`Ns`/`d`/`map_Kd`)
  and referenced textures are dumped as PNG into `textures/` next to the OBJ.
* An empty / geometry-less mesh raises `ValueError` -- callers get an error they
  can show in a dialog instead of a half written file or a crash.
* `export_obj_lods()` writes `name_LOD0.obj`, `name_LOD1.obj`, ... for every LOD.

Axis convention
---------------
`core.types` stores geometry already converted to GL metres (`x right, y up,
z back`). `axis='gl'` writes that as-is, `axis='ue'` converts back to the game's
centimetre space (`x fwd, y right, z up`) so the result can be re-imported into
Unreal; both honour `scale` (a multiplier applied to positions).
"""
from __future__ import annotations

import math
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

try:                                                    # texture dump is optional
    from PIL import Image
except Exception:                                       # noqa: BLE001
    Image = None                                    # type: ignore[assignment]

from core.types import Material, MeshLOD, ModelBundle, Texture

ROUND = 6
_SAFE = re.compile(r"[^A-Za-z0-9_.\-]+")


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _safe_name(name: str, fallback: str = "mat") -> str:
    clean = _SAFE.sub("_", (name or "").strip()) or fallback
    return clean[:120]


def _fmt(x: float) -> str:
    """Compact fixed precision float, no `-0.000000`."""
    v = float(x)
    if abs(v) < 1e-9:
        v = 0.0
    return f"{v:.{ROUND}f}"


def _axis_swap(points: np.ndarray, axis: str) -> np.ndarray:
    """GL metres -> requested output space (positions)."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if axis == "gl":
        return p.copy()
    out = np.empty_like(p)
    out[:, 0] = p[:, 2] * 100.0
    out[:, 1] = p[:, 0] * 100.0
    out[:, 2] = p[:, 1] * 100.0
    return out


def _axis_swap_normals(normals: np.ndarray, axis: str) -> np.ndarray:
    n = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    if axis == "gl":
        out = n.copy()
    else:
        out = np.empty_like(n)
        out[:, 0] = n[:, 2]
        out[:, 1] = n[:, 0]
        out[:, 2] = n[:, 1]
    length = np.linalg.norm(out, axis=1, keepdims=True)
    length[length < 1e-12] = 1.0
    return out / length


def _uv_array(uvs: np.ndarray, flip_uv: bool) -> Optional[np.ndarray]:
    if uvs is None:
        return None
    u = np.asarray(uvs, dtype=np.float64).reshape(-1, 2)
    if u.shape[0] == 0 or not np.isfinite(u).any():
        return None
    u = np.nan_to_num(u, nan=0.0, posinf=0.0, neginf=0.0)
    if flip_uv:
        u = u.copy()
        u[:, 1] = 1.0 - u[:, 1]
    return u


def _unique_rows(arr: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """De-duplicate rows, return (unique rows, inverse index per input row)."""
    rounded = np.round(arr, ROUND)
    # `np.unique(axis=0)` sorts rows; the returned inverse maps original -> unique
    uniq, inverse = np.unique(rounded, axis=0, return_inverse=True)
    return uniq, inverse.astype(np.int64).reshape(-1)


def _sections(lod: MeshLOD, indices: np.ndarray, merge: bool):
    """Yield `(material_path, triangle-slice)` for the index buffer."""
    total_tris = len(indices) // 3
    out: List[Tuple[str, slice]] = []
    for sec in (lod.sections or []):
        first = int(max(0, sec.first_index))
        count = int(sec.num_triangles)
        if count <= 0 and int(sec.num_vertices) > 0:
            count = int(sec.num_vertices) // 3
        if count <= 0:
            continue
        first_tri = min(first // 3, total_tris)
        last_tri = min(first_tri + count, total_tris)
        if last_tri <= first_tri:
            continue
        out.append((sec.material_path or "", slice(first_tri, last_tri)))
    if not out or merge:
        material = out[0][0] if out else ""
        return [(material, slice(0, total_tris))]
    return out


def _pick_material(path: str, materials: Sequence[Material], index: int) -> Optional[Material]:
    base = os.path.splitext(os.path.basename(path or ""))[0]
    if path:
        for mat in materials:
            if mat.pak_path and os.path.normcase(mat.pak_path) == os.path.normcase(path):
                return mat
        for mat in materials:
            if base and os.path.normcase(mat.name) == os.path.normcase(base):
                return mat
    if 0 <= index < len(materials):
        return materials[index]
    if materials:
        return materials[0]
    return None


def _find_texture(mat: Material, textures: Sequence[Texture]) -> Optional[Texture]:
    wanted = [mat.base_color_texture]
    try:
        wanted += [str(v) for v in (mat.texture_params or {}).values()]
    except Exception:                                   # noqa: BLE001
        pass
    bases = {os.path.splitext(os.path.basename(w))[0].lower()
             for w in wanted if w}
    for tex in textures:
        keys = {os.path.splitext(os.path.basename(tex.pak_path or ""))[0].lower(),
                (tex.name or "").lower()}
        if keys & bases and tex.rgba is not None:
            return tex
    for tex in textures:
        if tex.rgba is not None:
            return tex
    return None


def _save_texture(tex: Texture, directory: str, used: Dict[str, int], prefix: str = "") -> Optional[str]:
    """Dump one texture next to the OBJ; returns the relative map_Kd path."""
    if tex.rgba is None or Image is None:
        return None
    name = _safe_name(tex.name or os.path.basename(tex.pak_path or "tex"), "tex")
    name = _safe_name(prefix, "") + name
    count = used.get(name, 0)
    used[name] = count + 1
    if count:
        name = f"{name}_{count}"
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, name + ".png")
    try:
        rgba = np.asarray(tex.rgba)
        if rgba.ndim == 2:
            rgba = np.dstack([rgba] * 3 + [np.full(rgba.shape, 255, rgba.dtype)])
        if rgba.shape[-1] == 3:
            rgba = np.dstack([rgba, np.full(rgba.shape[:2], 255, np.uint8)])
        Image.fromarray(np.ascontiguousarray(rgba.astype(np.uint8))).save(target)
    except Exception:                                   # noqa: BLE001
        return None
    return f"textures/{name}.png"


# --------------------------------------------------------------------------- #
# geometry writer
# --------------------------------------------------------------------------- #
def _write_obj(
    lod: MeshLOD,
    path: str,
    *,
    name: str,
    materials: Sequence[Material],
    textures: Sequence[Texture],
    mtl: bool,
    scale: float,
    axis: str,
    merge_sections: bool,
    flip_uv: bool,
    texture_prefix: str = "",
) -> Dict[str, object]:
    if lod is None or lod.positions is None or len(lod.positions) == 0:
        raise ValueError("mesh has no vertices to export")
    if lod.indices is None or len(lod.indices) < 3:
        raise ValueError("mesh has no triangles to export")
    if axis not in ("gl", "ue"):
        raise ValueError(f"unknown axis {axis!r} (expected 'gl' or 'ue')")
    scale = float(scale)
    if not math.isfinite(scale) or scale == 0.0:
        raise ValueError(f"bad scale {scale!r}")

    positions = _axis_swap(lod.positions, axis) * scale
    normals = (None if lod.normals is None or len(lod.normals) == 0
               else _axis_swap_normals(lod.normals, axis))
    uvs = _uv_array(lod.uvs, flip_uv)

    indices = np.asarray(lod.indices, dtype=np.int64).reshape(-1)
    if len(indices) % 3:
        indices = indices[: len(indices) // 3 * 3]
    max_index = len(positions) - 1
    if indices.max() > max_index:
        raise ValueError(f"index buffer out of range ({indices.max()} > {max_index})")

    uniq_p, inv_p = _unique_rows(positions)
    uniq_t, inv_t = (None, None) if uvs is None else _unique_rows(uvs)
    uniq_n, inv_n = (None, None) if normals is None else _unique_rows(normals)

    corners = indices.reshape(-1, 3)
    vi = inv_p[corners] + 1
    ti = None if inv_t is None else inv_t[np.clip(corners, 0, len(inv_t) - 1)] + 1
    ni = None if inv_n is None else inv_n[np.clip(corners, 0, len(inv_n) - 1)] + 1

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    mtl_path = os.path.splitext(path)[0] + ".mtl"
    tex_dir = os.path.join(os.path.dirname(os.path.abspath(path)), "textures")

    # -- material table ---------------------------------------------------- #
    mat_defs: List[Dict[str, object]] = []
    used_names: Dict[str, int] = {}
    used_tex: Dict[str, int] = {}

    def _material_def(mat: Optional[Material], section_path: str) -> str:
        base = (mat.name if mat is not None else "") or \
            os.path.splitext(os.path.basename(section_path or ""))[0] or "default"
        stem = _safe_name(base, "default")
        count = used_names.get(stem, 0)
        used_names[stem] = count + 1
        mtl_name = stem if not count else f"{stem}.{count}"
        kd = list(getattr(mat, "base_color", (1, 1, 1, 1)) if mat is not None else (1, 1, 1, 1))
        if len(kd) < 4:
            kd = list(kd) + [1.0]
        metallic = float(getattr(mat, "metallic", 0.0) or 0.0)
        roughness = float(getattr(mat, "roughness", 0.5) if getattr(mat, "roughness", None) is not None else 0.5)
        ns = max(2.0, min(1000.0, 2.0 + (1.0 - max(0.0, min(1.0, roughness))) * 200.0))
        entry = {
            "name": mtl_name,
            "Kd": [float(max(0.0, min(1.0, c))) for c in kd[:3]],
            "Ks": [round(0.04 + 0.96 * max(0.0, min(1.0, metallic)), 4)] * 3,
            "Ns": round(ns, 3),
            "d": float(max(0.0, min(1.0, kd[3] if kd[3] else 1.0))),
            "map_Kd": None,
            "texture": None,
        }
        tex = _find_texture(mat, textures) if mat is not None else None
        if tex is not None:
            rel = _save_texture(tex, tex_dir, used_tex, texture_prefix)
            if rel:
                entry["map_Kd"] = rel
                entry["texture"] = tex.name or tex.pak_path
        mat_defs.append(entry)
        return mtl_name

    # -- geometry --------------------------------------------------------- #
    section_ranges = _sections(lod, indices, merge_sections)
    head: List[str] = [
        "# VertexViewer OBJ export",
        f"# asset: {name or 'mesh'}",
        f"# axis: {axis}  scale: {scale:g}  flip_uv: {bool(flip_uv)}",
        f"# LOD: {getattr(lod, 'name', '') or ''}".rstrip(),
        f"# vertices: {len(uniq_p)}  uvs: {0 if uniq_t is None else len(uniq_t)}"
        f"  normals: {0 if uniq_n is None else len(uniq_n)}  triangles: {len(corners)}",
    ]
    if mtl:
        head.append(f"mtllib {os.path.basename(mtl_path)}")
    head.append(f"o {_safe_name(name or 'mesh', 'mesh')}")

    lines: List[str] = list(head)
    for row in uniq_p:
        lines.append(f"v {_fmt(row[0])} {_fmt(row[1])} {_fmt(row[2])}")
    if uniq_t is not None:
        for row in uniq_t:
            lines.append(f"vt {_fmt(row[0])} {_fmt(row[1])}")
    if uniq_n is not None:
        for row in uniq_n:
            lines.append(f"vn {_fmt(row[0])} {_fmt(row[1])} {_fmt(row[2])}")

    face_count = 0
    for sec_index, (sec_path, tri_slice) in enumerate(section_ranges):
        mat = _pick_material(sec_path, materials, sec_index)
        mtl_name = _material_def(mat, sec_path)
        if mtl:
            lines.append(f"usemtl {mtl_name}")
        chunk = vi[tri_slice.start:tri_slice.stop]
        if chunk.size == 0:
            continue
        if ti is not None:
            t_chunk = ti[tri_slice.start:tri_slice.stop]
        if ni is not None:
            n_chunk = ni[tri_slice.start:tri_slice.stop]
        for k in range(chunk.shape[0]):
            a = int(chunk[k, 0]); b = int(chunk[k, 1]); c = int(chunk[k, 2])
            if ti is not None and ni is not None:
                ta, tb, tc = (int(t_chunk[k, 0]), int(t_chunk[k, 1]), int(t_chunk[k, 2]))
                na, nb, nc = (int(n_chunk[k, 0]), int(n_chunk[k, 1]), int(n_chunk[k, 2]))
                lines.append(f"f {a}/{ta}/{na} {b}/{tb}/{nb} {c}/{tc}/{nc}")
            elif ti is not None:
                ta, tb, tc = (int(t_chunk[k, 0]), int(t_chunk[k, 1]), int(t_chunk[k, 2]))
                lines.append(f"f {a}/{ta} {b}/{tb} {c}/{tc}")
            elif ni is not None:
                na, nb, nc = (int(n_chunk[k, 0]), int(n_chunk[k, 1]), int(n_chunk[k, 2]))
                lines.append(f"f {a}//{na} {b}//{nb} {c}//{nc}")
            else:
                lines.append(f"f {a} {b} {c}")
            face_count += 1

    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")

    if mtl and mat_defs:
        with open(mtl_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f"# VertexViewer material library for {os.path.basename(path)}\n")
            for entry in mat_defs:
                kd = entry["Kd"]; ks = entry["Ks"]
                fh.write(f"\nnewmtl {entry['name']}\n")
                fh.write("Ka 0.000000 0.000000 0.000000\n")
                fh.write("Kd %.6f %.6f %.6f\n" % (kd[0], kd[1], kd[2]))
                fh.write("Ks %.6f %.6f %.6f\n" % (ks[0], ks[1], ks[2]))
                fh.write(f"Ns {entry['Ns']:.3f}\n")
                fh.write(f"d {entry['d']:.6f}\n")
                fh.write("illum 2\n")
                if entry["map_Kd"]:
                    fh.write(f"map_Kd {entry['map_Kd']}\n")
    elif not mtl:
        mtl_path = ""

    return {
        "obj": path,
        "mtl": mtl_path,
        "name": name,
        "v": int(len(uniq_p)),
        "vt": int(0 if uniq_t is None else len(uniq_t)),
        "vn": int(0 if uniq_n is None else len(uniq_n)),
        "f": int(face_count),
        "sections": len(section_ranges),
        "materials": [d["name"] for d in mat_defs],
        "textures": [d["map_Kd"] for d in mat_defs if d["map_Kd"]],
        "bytes": os.path.getsize(path),
    }


# --------------------------------------------------------------------------- #
# public api
# --------------------------------------------------------------------------- #
def export_obj(
    bundle: ModelBundle,
    path: str,
    *,
    lod: int = 0,
    mtl: bool = True,
    scale: float = 1.0,
    axis: str = "gl",
    merge_sections: bool = False,
    flip_uv: bool = True,
    texture_prefix: str = "",
) -> Dict[str, object]:
    """Export one LOD of a `ModelBundle`; returns a stats dict for the UI."""
    if bundle is None or bundle.mesh is None:
        raise ValueError("bundle has no mesh to export")
    mesh = bundle.mesh
    if not mesh.lods:
        raise ValueError(f"{mesh.name or 'mesh'} has no LODs to export")
    lod_index = int(lod)
    if not (0 <= lod_index < len(mesh.lods)):
        raise ValueError(f"LOD {lod_index} out of range (mesh has {len(mesh.lods)})")
    name = bundle.display_name or mesh.name or os.path.splitext(os.path.basename(path))[0]
    if len(mesh.lods) > 1:
        name = f"{name}_LOD{lod_index}"
    return _write_obj(
        mesh.lods[lod_index], path, name=name,
        materials=bundle.materials or [], textures=bundle.textures or [],
        mtl=mtl, scale=scale, axis=axis, merge_sections=merge_sections, flip_uv=flip_uv,
        texture_prefix=texture_prefix,
    )


def export_mesh_lod(
    lod: MeshLOD,
    path: str,
    *,
    name: str = "",
    materials: Optional[Sequence[Material]] = None,
    textures: Optional[Sequence[Texture]] = None,
    mtl: bool = True,
    scale: float = 1.0,
    axis: str = "gl",
    merge_sections: bool = False,
    flip_uv: bool = True,
) -> Dict[str, object]:
    """Export a bare `MeshLOD` (no bundle) -- used by tests and the CLI."""
    return _write_obj(
        lod, path, name=name or os.path.splitext(os.path.basename(path))[0],
        materials=materials or [], textures=textures or [],
        mtl=mtl, scale=scale, axis=axis, merge_sections=merge_sections, flip_uv=flip_uv,
    )


def export_obj_lods(
    bundle: ModelBundle,
    path: str,
    *,
    lods: Optional[Sequence[int]] = None,
    mtl: bool = True,
    scale: float = 1.0,
    axis: str = "gl",
    merge_sections: bool = False,
    flip_uv: bool = True,
) -> List[Dict[str, object]]:
    """Write one OBJ per LOD: `stem_LOD0.obj`, `stem_LOD1.obj`, ..."""
    if bundle is None or bundle.mesh is None:
        raise ValueError("bundle has no mesh to export")
    stem = os.path.splitext(path)[0]
    indices = list(range(len(bundle.mesh.lods))) if lods is None else [int(i) for i in lods]
    results: List[Dict[str, object]] = []
    for i in indices:
        out = f"{stem}_LOD{i}.obj" if len(bundle.mesh.lods) > 1 else f"{stem}.obj"
        results.append(export_obj(
            bundle, out, lod=i, mtl=mtl, scale=scale, axis=axis,
            merge_sections=merge_sections, flip_uv=flip_uv,
        ))
    return results


__all__ = ["export_obj", "export_obj_lods", "export_mesh_lod"]

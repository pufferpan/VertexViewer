"""Persistent, self-contained local attachment library (never pickle model data)."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import shutil
import uuid

import numpy as np
from PIL import Image

from core.types import Material, Mesh, MeshLOD, ModelBundle, Section, Texture

PREFIX = "vertexviewer-local://"


def library_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VertexViewer" / "custom-parts"


def is_local(path: str) -> bool:
    return path.startswith(PREFIX)


def _folder(path: str) -> Path:
    key = path.removeprefix(PREFIX)
    if not is_local(path) or not re.fullmatch(r"[a-f0-9]{32}", key):
        raise ValueError("无效的本地配件标识")
    return library_dir() / key


def rows():
    out = []
    for file in library_dir().glob("*/part.json"):
        try:
            meta = json.loads(file.read_text(encoding="utf-8"))
            out.append((PREFIX + file.parent.name, meta["name"], meta["slot"], "本地导入", "part"))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda r: r[1].casefold())


def display_name(path: str) -> str:
    try:
        return json.loads((_folder(path) / "part.json").read_text(encoding="utf-8"))["name"]
    except (OSError, ValueError, KeyError):
        return "本地配件（文件缺失）"


def import_file(filename: str, name: str, slot: str, units: float = 1.0,
                up_axis: str = "Y") -> tuple[str, ModelBundle]:
    """Bake scene-node transforms and copy geometry/textures into an owned folder."""
    source = Path(filename).resolve(strict=True)
    key = uuid.uuid4().hex
    if not np.isfinite(units) or units <= 0:
        raise ValueError("模型单位无效")
    if source.suffix.lower() == ".uemodel":
        from core.ueformat import read_uemodel
        mesh, _, _ = read_uemodel(str(source))
        if isinstance(mesh, ModelBundle):
            bundle = mesh
        else:
            bundle = ModelBundle(mesh=mesh)
    else:
        import trimesh
        # Remote resources are disabled. The imported result is saved locally.
        scene = trimesh.load_scene(source, process=False, allow_remote=False)
        positions, normals, uvs, indices, sections, materials, textures = [], [], [], [], [], [], []
        vertex_start = index_start = 0
        for node in scene.graph.nodes_geometry:
            transform, geometry = scene.graph[node]
            geo = scene.geometry[geometry].copy()
            geo.apply_transform(transform)
            if len(geo.vertices) == 0 or len(geo.faces) == 0:
                continue
            pos = np.asarray(geo.vertices, np.float32)
            nor = np.asarray(geo.vertex_normals, np.float32)
            visual = geo.visual
            texcoords = getattr(visual, "uv", None)
            uv = np.asarray(texcoords, np.float32) if texcoords is not None else np.zeros((len(pos), 2), np.float32)
            # glTF/OBJ image origin is upper left; the renderer samples UE UVs.
            uv = uv.copy()
            uv[:, 1] = 1.0 - uv[:, 1]
            mat = Material(name=str(node), roughness=0.6)
            rawmat = getattr(visual, "material", None)
            color = getattr(rawmat, "baseColorFactor", None)
            if color is None:
                color = getattr(rawmat, "diffuse", None)
            if color is not None:
                color = np.asarray(color, float)
                if color.max() > 1: color /= 255.0
                mat.base_color = tuple(color[:4]) if len(color) >= 4 else tuple(color[:3]) + (1.0,)
            mat.metallic = float(getattr(rawmat, "metallicFactor", 0.0) or 0.0)
            mat.roughness = float(getattr(rawmat, "roughnessFactor", 0.6) or 0.6)
            for attr, target in (("baseColorTexture", "base_color_texture"), ("image", "base_color_texture"),
                                 ("normalTexture", "normal_texture"), ("emissiveTexture", "emissive_texture")):
                image = getattr(rawmat, attr, None)
                if image is None or getattr(mat, target): continue
                rgba = np.asarray(image.convert("RGBA"), np.uint8).copy()
                texture_key = f"vertexviewer-local://{key}/texture-{len(textures)}"
                textures.append(Texture(name=texture_key, pak_path=texture_key, width=rgba.shape[1], height=rgba.shape[0],
                                        rgba=rgba, srgb=target != "normal_texture"))
                setattr(mat, target, texture_key)
            packed = getattr(rawmat, "metallicRoughnessTexture", None)
            if packed is not None:
                rgba = np.asarray(packed.convert("RGBA"), np.uint8).copy()
                rgba[:, :, 0] = rgba[:, :, 2]  # glTF B metallic -> DF R metallic
                rgba[:, :, 2] = 255            # DF B occlusion defaults to unoccluded
                texture_key = f"vertexviewer-local://{key}/texture-{len(textures)}"
                mat.orm_texture = texture_key
                textures.append(Texture(name=texture_key, pak_path=texture_key, width=rgba.shape[1], height=rgba.shape[0], rgba=rgba, srgb=False))
            alpha_mode = str(getattr(rawmat, 'alphaMode', '') or '').upper()
            mat.blend_mode = {'MASK':'Masked', 'BLEND':'Translucent'}.get(alpha_mode, 'Opaque')
            mat.two_sided = bool(getattr(rawmat, 'doubleSided', False))
            mat.pak_path = f"vertexviewer-local://{key}/material-{len(materials)}"
            faces = np.asarray(geo.faces, np.uint32).reshape(-1)
            sections.append(Section(material_path=mat.pak_path, first_index=index_start,
                                    num_triangles=len(faces)//3, first_vertex=vertex_start, num_vertices=len(pos)))
            materials.append(mat)
            positions.append(pos); normals.append(nor); uvs.append(uv); indices.append(faces + vertex_start)
            vertex_start += len(pos); index_start += len(faces)
        if not positions:
            raise ValueError("文件中没有可导入的三角形网格")
        lod = MeshLOD(positions=np.concatenate(positions), normals=np.concatenate(normals),
                      uvs=np.concatenate(uvs), indices=np.concatenate(indices), sections=sections)
        bundle = ModelBundle(mesh=Mesh(name=name, lods=[lod], source_format="Local"),
                             materials=materials, textures=textures, display_name=name)
    if bundle.mesh is None or not bundle.mesh.lods:
        raise ValueError("文件中没有可用模型")
    for lod in bundle.mesh.lods:
        if up_axis == "Z":
            # Right-handed Z-up -> right-handed Y-up.
            for attr in ("positions", "normals"):
                arr = getattr(lod, attr)
                if arr is not None: setattr(lod, attr, arr[:, [0, 2, 1]] * np.array([1, 1, -1], np.float32))
        lod.positions = np.asarray(lod.positions * units, np.float32)
        if not np.isfinite(lod.positions).all():
            raise ValueError("模型含无效顶点")
    folder = library_dir() / key
    folder.mkdir(parents=True)
    try:
        lod = bundle.mesh.lods[0]
        arrays = {k: getattr(lod, k) for k in ("positions", "normals", "uvs", "indices", "tangents", "uv_sets")
                  if getattr(lod, k) is not None}
        np.savez_compressed(folder / "mesh.npz", **arrays)
        for i, tex in enumerate(bundle.textures):
            Image.fromarray(tex.rgba).save(folder / f"texture-{i}.png")
        meta = dict(name=name.strip() or source.stem, slot=slot, source_name=source.name,
                    sections=[asdict(s) for s in lod.sections], materials=[asdict(m) for m in bundle.materials],
                    textures=[dict(name=t.name, pak_path=t.pak_path, srgb=t.srgb) for t in bundle.textures])
        (folder / "part.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        shutil.rmtree(folder)
        raise
    path = PREFIX + key
    return path, load(path)


def load(path: str) -> ModelBundle:
    folder = _folder(path)
    meta = json.loads((folder / "part.json").read_text(encoding="utf-8"))
    with np.load(folder / "mesh.npz", allow_pickle=False) as data:
        arrays = {k: np.array(data[k], copy=True) for k in data.files}
    lod = MeshLOD(**arrays, sections=[Section(**s) for s in meta["sections"]])
    textures = []
    for i, info in enumerate(meta["textures"]):
        with Image.open(folder / f"texture-{i}.png") as image:
            rgba = np.asarray(image.convert("RGBA"), np.uint8).copy()
        textures.append(Texture(**info, width=rgba.shape[1], height=rgba.shape[0], rgba=rgba))
    return ModelBundle(mesh=Mesh(name=meta["name"], pak_path=path, lods=[lod], source_format="Local"),
                       display_name=meta["name"], materials=[Material(**m) for m in meta["materials"]], textures=textures)

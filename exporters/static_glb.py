"""Static glTF 2.0 (GLB) for a single model, keeping its skeleton and skin weights.

OBJ cannot carry bones; this writer emits the same reflected-metre rig that the
animation exporter uses, but with the bind pose only, so Blender/UE can pose the
asset afterwards instead of getting a frozen triangle soup.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import tempfile

import numpy as np

from core.inspection import world_matrices
from core.types import Material, Section
from exporters.animation_glb import _Document, gl_pose


def skeleton_available(mesh) -> bool:
    """True when this mesh can be exported as a skinned model."""
    if mesh is None or not mesh.lods:
        return False
    lod = mesh.lods[0]
    return (getattr(lod, "bone_weights", None) is not None
            and getattr(lod, "bones", None)
            and getattr(mesh, "reference_pose", None) is not None
            and getattr(mesh, "bone_parents", None))


def export_static_glb(bundle, path, *, lod_index: int = 0):
    """Write geometry + materials + skin into one .glb; returns a summary dict."""
    mesh = bundle.mesh
    if mesh is None or not mesh.lods:
        raise ValueError("模型没有可导出的网格")
    lod = mesh.lods[0] if not lod_index else mesh.lods[min(lod_index, len(mesh.lods) - 1)]
    writer = _Document()
    doc = writer.doc
    basis = np.array([[0, .01, 0, 0], [0, 0, .01, 0], [-.01, 0, 0, 0], [0, 0, 0, 1]], float)
    inverse_basis = np.linalg.inv(basis)

    skeleton = skeleton_available(mesh)
    first = len(doc["nodes"])
    skin_index = None
    if skeleton:
        bones = list(lod.bones)
        parents = list(mesh.bone_parents)[:len(bones)]
        parents += [-1] * (len(bones) - len(parents))
        poses = gl_pose(mesh.reference_pose)
        roots = []
        for index, name in enumerate(bones):
            pose = poses[index] if index < len(poses) else np.array([0, 0, 0, 1, 0, 0, 0, 1, 1, 1], float)
            doc["nodes"].append(dict(name=str(name), rotation=pose[:4].tolist(),
                                     translation=pose[4:7].tolist(), scale=pose[7:10].tolist()))
        for index, parent in enumerate(parents):
            if 0 <= parent < len(bones):
                doc["nodes"][first + parent].setdefault("children", []).append(first + index)
            else:
                roots.append(first + index)
        doc["scenes"][0]["nodes"].extend(roots)
        world = world_matrices(mesh.reference_pose, mesh.bone_parents)
        inverse_bind = basis @ np.linalg.inv(world) @ inverse_basis
        doc["skins"].append(dict(name=mesh.name,
                                 joints=list(range(first, first + len(bones))),
                                 inverseBindMatrices=writer.accessor(
                                     inverse_bind.transpose(0, 2, 1).astype("<f4").reshape(-1, 16), "MAT4")))
        skin_index = len(doc["skins"]) - 1

    attributes = dict(POSITION=writer.accessor(lod.positions.astype("<f4"), "VEC3", 34962, True),
                      NORMAL=writer.accessor(lod.normals.astype("<f4"), "VEC3", 34962))
    if lod.uvs is not None:
        attributes["TEXCOORD_0"] = writer.accessor(lod.uvs.astype("<f4"), "VEC2", 34962)
    if lod.tangents is not None:
        tangent = lod.tangents.astype("<f4").copy()
        tangent[:, :3] -= lod.normals * np.sum(tangent[:, :3] * lod.normals, axis=1, keepdims=True)
        length = np.linalg.norm(tangent[:, :3], axis=1, keepdims=True)
        if np.all(length > 1e-8):
            tangent[:, :3] /= length
            tangent[:, 3] = np.where(tangent[:, 3] < 0, -1, 1)
            attributes["TANGENT"] = writer.accessor(tangent, "VEC4", 34962)

    if skeleton:
        weights = np.asarray(lod.bone_weights, np.float32)
        weights = weights / np.maximum(weights.sum(axis=1, keepdims=True), 1e-12)
        joints = np.asarray(lod.bone_indices, np.int32)
        for slot, start in enumerate(range(0, weights.shape[1], 4)):
            w = weights[:, start:start + 4]
            j = joints[:, start:start + 4]
            if w.shape[1] < 4:
                pad = 4 - w.shape[1]
                w = np.pad(w, ((0, 0), (0, pad)))
                j = np.pad(j, ((0, 0), (0, pad)))
            j = np.where(w > 0, j, 0)
            attributes["JOINTS_" + str(slot)] = writer.accessor(np.maximum(j, 0).astype("<u2"), "VEC4", 34962)
            attributes["WEIGHTS_" + str(slot)] = writer.accessor(w.astype("<f4"), "VEC4", 34962)

    by_path = {m.pak_path: m for m in bundle.materials}
    primitives = []
    sections = lod.sections or [Section(num_triangles=lod.triangle_count)]
    for index, section in enumerate(sections):
        indices = np.asarray(lod.indices[section.first_index:section.first_index + section.num_triangles * 3], "<u4")
        if not len(indices):
            continue
        if indices.max() >= lod.vertex_count:
            raise ValueError("模型包含越界三角面")
        material = by_path.get(section.material_path) or (bundle.materials[min(index, len(bundle.materials) - 1)]
                                                          if bundle.materials else Material(name="Default"))
        primitives.append(dict(attributes=attributes,
                               indices=writer.accessor(indices, "SCALAR", 34963),
                               material=writer.material(material, bundle.textures)))
    if not primitives:
        raise ValueError("模型没有可导出的三角面")
    doc["meshes"].append(dict(name=mesh.name, primitives=primitives))
    node = dict(name=mesh.name, mesh=len(doc["meshes"]) - 1,
                extras=dict(source=mesh.pak_path, skeleton=bool(skeleton)))
    if skin_index is not None:
        node["skin"] = skin_index
    doc["nodes"].append(node)
    doc["scenes"][0]["nodes"].append(len(doc["nodes"]) - 1)

    doc["buffers"] = [dict(byteLength=len(writer.data))]
    for key in ("materials", "images", "textures", "skins", "animations"):
        if not doc[key]:
            doc.pop(key)
    metadata = json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    metadata += b" " * (-len(metadata) % 4)
    writer.data.extend(b"\0" * (-len(writer.data) % 4))

    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".static-", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            handle.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(metadata) + 8 + len(writer.data)))
            handle.write(struct.pack("<II", len(metadata), 0x4E4F534A))
            handle.write(metadata)
            handle.write(struct.pack("<II", len(writer.data), 0x004E4942))
            handle.write(writer.data)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            os.unlink(temporary)
    return dict(path=str(path), bytes=path.stat().st_size, vertices=int(lod.vertex_count),
                triangles=int(lod.triangle_count), bones=len(lod.bones) if skeleton else 0,
                materials=len(doc.get("materials", [])), skinned=bool(skeleton))

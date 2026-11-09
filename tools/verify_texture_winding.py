"""The same UV-mapped surface must render identically with either winding."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from core.types import Material, Mesh, MeshLOD, Section, Texture
from render.viewer import OffscreenViewer, SceneState

app = QApplication.instance() or QApplication([])
rgba = np.zeros((32, 64, 4), np.uint8)
rgba[:, :32] = [220, 20, 20, 255]
rgba[:, 32:] = [20, 40, 220, 255]
lod = MeshLOD(positions=np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], np.float32),
              normals=np.array([[0, 0, 1]] * 4, np.float32),
              uvs=np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32),
              indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
              sections=[Section(material_path="plane", num_triangles=2)])
state = SceneState(mesh=Mesh(lods=[lod]),
                   materials=[Material(pak_path="plane", base_color_texture="asymmetric", roughness=.9)],
                   textures=[Texture(pak_path="asymmetric", rgba=rgba)])
state.camera.yaw = state.camera.pitch = 0
state.camera.distance = 3
state.camera.target = (0, 0, 0)
viewer = OffscreenViewer(state)
front = viewer.render(256, 256)
lod.indices = lod.indices.reshape(-1, 3)[:, ::-1].reshape(-1).copy()
state.mesh_version += 1
back = viewer.render(256, 256)
delta = float(np.abs(front.astype(float) - back.astype(float)).mean())
assert delta < .02, delta
# An unavailable optional texture must not abort the frame.
state.materials[0].normal_texture = "missing"
state.textures.append(Texture(pak_path="missing", rgba=None))
state.texture_version += 1
viewer.render(256, 256)
# Packed NCE normal maps must ignore their blue mask channel.
packed = np.full((4, 4, 4), 128, np.uint8)
packed[..., 2] = 0
packed[..., 3] = 255
state.textures[-1] = Texture(name="T_NCEMap", pak_path="missing", rgba=packed)
# The texture's real name normally also occurs in its path.
state.textures[-1].pak_path = "T_NCEMap"
state.materials[0].normal_texture = "T_NCEMap"
state.texture_version += 1
low_blue = viewer.render(256, 256)
packed[..., 2] = 255
state.texture_version += 1
high_blue = viewer.render(256, 256)
packed_delta = float(np.abs(low_blue.astype(float) - high_blue.astype(float)).mean())
assert packed_delta < .02, packed_delta
viewer.release()
print(json.dumps(dict(winding_pixel_delta=delta, missing_texture_frame=True, packed_normal_blue_delta=packed_delta)))

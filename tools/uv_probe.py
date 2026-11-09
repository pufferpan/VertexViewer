"""UV 朝向探针：一片带 4 色贴图的四边形，看四个角的颜色是否与 UE 约定一致。

UE 约定：贴图第 0 行在 UV 的 v=0 一侧（v 向下）。所以「左上角的 UV=(0,0)」——
四边形左上角应当采到贴图的左上角像素。

    python tools/uv_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from core.types import Material, Mesh, MeshLOD, Texture  # noqa: E402
from render.viewer import OffscreenViewer, SceneState, mesh_bounds  # noqa: E402

W = H = 256


def quad_mesh():
    # x 向右、y 向上、z 朝观察者；u/v 按 UE 口径给：左上角 = (0,0)
    pos = np.array([[-1, 1, 0], [1, 1, 0], [1, -1, 0], [-1, -1, 0]], np.float32)
    nrm = np.tile(np.array([0, 0, 1], np.float32), (4, 1))
    uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], np.float32)
    idx = np.array([0, 2, 1, 0, 3, 2], np.uint32)          # 逆时针朝 +Z
    lod = MeshLOD(positions=pos, normals=nrm, uvs=uv,
                  indices=idx, uv_sets=uv.reshape(4, 1, 2))
    return Mesh(name="probe", lods=[lod], source_format="StaticMesh")


def corner_texture():
    """8x8 四象限：左上红、右上绿、左下蓝、右下黄（行序 = 图像自上而下）。"""
    arr = np.zeros((8, 8, 4), np.uint8)
    arr[..., 3] = 255
    arr[0:4, 0:4, :3] = (255, 0, 0)      # 左上
    arr[0:4, 4:8, :3] = (0, 255, 0)      # 右上
    arr[4:8, 0:4, :3] = (0, 0, 255)      # 左下
    arr[4:8, 4:8, :3] = (255, 255, 0)    # 右下
    return Texture(name="probe", pak_path="probe.uasset", rgba=arr)


def main():
    mesh = quad_mesh()
    mat = Material(name="probe", base_color_texture="probe.uasset")
    tex = corner_texture()
    state = SceneState(style="pbr", mesh=mesh, materials=[mat], textures=[tex])
    state.lighting.key_intensity = 1.0
    state.lighting.fill_intensity = 0.0
    state.lighting.rim_intensity = 0.0
    state.lighting.env_intensity = 0.0
    state.lighting.exposure_ev = 0.0
    c, r = mesh_bounds(mesh, 0)
    state.camera.frame(c, r)
    # 正对着四边形看：yaw=0/pitch=0，距离按 fov 把 2x2 的板子塞满画面约 90%，
    # 这样 (0.25,0.25) 这类采样点一定落在板子上而不是背景。
    state.camera.yaw = 0.0
    state.camera.pitch = 0.0
    state.camera.target = (0.0, 0.0, 0.0)
    state.camera.distance = 2.9

    # 回归检查：重复取包围盒/重复渲染不能改变 UV（早先 prepare_lod 原地翻 V，
    # 每调一次就翻一次，贴图就上下颠倒）。
    before = np.array(mesh.lods[0].uv_sets, copy=True)
    for _ in range(3):
        mesh_bounds(mesh, 0)
    if not np.allclose(before, mesh.lods[0].uv_sets):
        print("BUG: mesh_bounds() 改写了 UV 数据（原地翻转）")
    from render.viewer import prepare_lod as _prepare  # noqa: E402

    for _ in range(3):
        _prepare(mesh.lods[0], 0)
    uv_stable = bool(np.allclose(before, mesh.lods[0].uv_sets))
    print("UV 数据稳定（prepare_lod 不再原地改写）:", uv_stable)

    viewer = OffscreenViewer(state, W, H)
    px = viewer.renderer.render(state, W, H, readback=True)
    if px is None:
        print("no pixels")
        return
    arr = np.asarray(px)
    if arr.ndim == 3 and arr.shape[2] == 4:
        arr = arr[:, :, :3]
    # readback 是自上而下的行序
    def sample(fx, fy, label):
        x = int(fx * (W - 1))
        y = int(fy * (H - 1))
        patch = arr[max(0, y - 6):y + 7, max(0, x - 6):x + 7].reshape(-1, 3).astype(int)
        col = np.median(patch, axis=0).astype(int)
        return col

    def classify(col):
        r, g, b = (int(v) for v in col)
        # 只比「哪个通道压倒性最强」，避开色调映射/曝光带来的整体偏移
        if r > b + 60 and g > b + 60 and abs(r - g) <= 60:
            return "黄"
        if r > g + 40 and r > b + 40:
            return "红"
        if g > r + 40 and g > b + 40:
            return "绿"
        if b > r + 40 and b > g + 40:
            return "蓝"
        return f"混合{tuple(col)}"

    print("屏幕四角采样（期望：左上红 右上绿 左下蓝 右下黄）")
    got = {"左上": sample(0.25, 0.25, "左上"), "右上": sample(0.75, 0.25, "右上"),
           "左下": sample(0.25, 0.75, "左下"), "右下": sample(0.75, 0.75, "右下")}
    want = {"左上": "红", "右上": "绿", "左下": "蓝", "右下": "黄"}
    ok = 0
    for k in want:
        cls = classify(got[k])
        hit = cls == want[k]
        ok += 1 if hit else 0
        print(f"  {k}: RGB {tuple(int(v) for v in got[k])} -> {cls}  期望 {want[k]}  {'OK' if hit else 'MISMATCH'}")
    print("verdict:", "V 轴一致（贴图没上下颠倒）" if ok == 4 else f"{4 - ok} 个角不一致 -> 翻转口径有误")
    out = r"G:\xmcl-fetch\work\uv_probe.png"
    try:
        from render.viewer import save_png
        save_png(out, np.asarray(px))
        print("saved", out)
    except Exception as exc:                                  # noqa: BLE001
        print("save failed", exc)


if __name__ == "__main__":
    main()

"""把当前模型一键送进 Blender。

两个用途：
1. 视口里按住 Ctrl+Shift 拖动，松手就把当前模型导出并丢进 Blender；
2. 导出页/菜单里的「发送到 Blender」。

Blender 可执行文件的查找顺序：环境变量 ``VERTEXVIEWER_BLENDER`` →
配置文件里的 ``blender`` / ``blender_exe`` → 常见安装位置（含 Steam 版）。
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".config")) / "VertexViewer"

_COMMON = (
    r"C:\Program Files\Blender Foundation\Blender */blender.exe",
    r"C:\Program Files\Blender Foundation\Blender*/blender.exe",
    r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
    r"G:\SteamLibrary\steamapps\common\Blender\blender.exe",
    r"D:\SteamLibrary\steamapps\common\Blender\blender.exe",
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "/usr/bin/blender",
    "/usr/local/bin/blender",
)

GESTURE_THRESHOLD = 36          # 拖动多少像素才算「要送进 Blender」


def is_gesture(modifiers_ok: bool, distance: float) -> bool:
    """按住热键并拖动超过阈值才算一次投放手势。"""
    return bool(modifiers_ok) and float(distance) >= GESTURE_THRESHOLD


def _config_value(*keys: str) -> str:
    try:
        data = json.loads((CONFIG_DIR / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def blender_candidates() -> List[str]:
    found: List[str] = []
    env = os.environ.get("VERTEXVIEWER_BLENDER", "").strip()
    if env and os.path.isfile(env):
        found.append(env)
    cfg = _config_value("blender", "blender_exe", "blenderPath")
    if cfg and os.path.isfile(cfg):
        found.append(cfg)
    for pattern in _COMMON:
        for match in sorted(glob.glob(pattern), reverse=True):
            if os.path.isfile(match) and match not in found:
                found.append(match)
    return found


def blender_exe() -> str:
    """返回可用的 blender 路径，找不到返回空串。"""
    candidates = blender_candidates()
    return candidates[0] if candidates else ""


def import_script(model_path: str, *, reset: bool = False) -> str:
    """生成让 Blender 导入模型的脚本。

    默认不动当前场景：不删对象、不清集合，直接追加导入（reset=True 才清空）。
    路径用正斜杠，避免转义问题。
    """
    path = str(model_path).replace("\\", "/")
    lines = [
        "import bpy",
        "from mathutils import Vector",
        "",
    ]
    if reset:
        lines += [
            "bpy.ops.object.select_all(action='SELECT')",
            "bpy.ops.object.delete(use_global=False)",
            "",
        ]
    lines += [
        f"target = {path!r}",
        "if target.lower().endswith('.obj'):",
        "    bpy.ops.wm.obj_import(filepath=target)",
        "else:",
        "    bpy.ops.import_scene.gltf(filepath=target)",
        "",
        "# 选中导入的东西并框住视图，省得用户自己找",
        "imported = [o for o in bpy.context.scene.objects if o.type == 'MESH']",
        "if imported:",
        "    bpy.ops.object.select_all(action='DESELECT')",
        "    for obj in imported:",
        "        obj.select_set(True)",
        "    bpy.context.view_layer.objects.active = imported[0]",
        "    for area in bpy.context.screen.areas if bpy.context.screen else []:",
        "        if area.type == 'VIEW_3D':",
        "            for region in area.regions:",
        "                if region.type == 'WINDOW':",
        "                    with bpy.context.temp_override(area=area, region=region):",
        "                        bpy.ops.view3d.view_selected()",
        "                    break",
        "    print('[vertexviewer] imported', len(imported), 'objects from', target)",
        "    print('[vertexviewer] scene objects now:', len(bpy.context.scene.objects))",
        "else:",
        "    print('[vertexviewer] import produced no mesh:', target)",
        "",
    ]
    return "\n".join(lines)


def launch(model_path: str, *, exe: Optional[str] = None,
           extra_args: Optional[List[str]] = None) -> subprocess.Popen:
    """启动 Blender（带界面）并执行导入脚本。"""
    blender = exe or blender_exe()
    if not blender:
        raise FileNotFoundError("没找到 blender.exe，可在设置里指定，或设 VERTEXVIEWER_BLENDER")
    script = Path(tempfile.gettempdir()) / "vertexviewer_blender_import.py"
    script.write_text(import_script(model_path), encoding="utf-8")
    argv = [blender, "--python", str(script)]
    if extra_args:
        argv.extend(extra_args)
    return subprocess.Popen(argv, close_fds=True)


__all__ = ["GESTURE_THRESHOLD", "blender_candidates", "blender_exe", "import_script",
           "is_gesture", "launch"]

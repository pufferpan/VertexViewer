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
import time
from pathlib import Path
from typing import List, Optional

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".config")) / "VertexViewer"
BRIDGE_DIR = Path(tempfile.gettempdir()) / "vertexviewer_bridge"
PID_FILE = BRIDGE_DIR / "blender.pid"

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


def _alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def session_pid() -> int:
    """还活着的桥接 Blender 进程；没有就是 0。"""
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0
    return pid if _alive(pid) else 0


def request_import(model_path: str) -> bool:
    """给正在运行的桥接 Blender 投一个导入请求（它自己轮询目录）。"""
    if not session_pid():
        return False
    try:
        BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{int(time.time() * 1000)}-{os.getpid()}.json"
        (BRIDGE_DIR / name).write_text(json.dumps({"path": str(model_path)}, ensure_ascii=False),
                                       encoding="utf-8")
        return True
    except OSError:
        return False


def bridge_script(first_model: str = "") -> str:
    """常驻脚本：先把 first_model 导进来，然后每 0.4 秒检查一次新请求。"""
    first_line = f"FIRST = {first_model!r}" if first_model else "FIRST = ''"
    return "\n".join([
        "import bpy, glob, json, os",
        f"REQ = {str(BRIDGE_DIR).replace(chr(92), '/')!r}",
        f"PID = {str(PID_FILE).replace(chr(92), '/')!r}",
        "",
        "def _import_one(path):",
        "    low = str(path).lower()",
        "    if low.endswith('.obj'):",
        "        bpy.ops.wm.obj_import(filepath=path)",
        "    else:",
        "        bpy.ops.import_scene.gltf(filepath=path)",
        "    imported = [o for o in bpy.context.scene.objects if o.type == 'MESH']",
        "    if imported:",
        "        bpy.ops.object.select_all(action='DESELECT')",
        "        for obj in imported:",
        "            obj.select_set(True)",
        "        bpy.context.view_layer.objects.active = imported[0]",
        "    print('[vertexviewer] imported', path)",
        "",
        "def _tick():",
        "    try:",
        "        for name in sorted(glob.glob(os.path.join(REQ, '*.json'))):",
        "            try:",
        "                with open(name, encoding='utf-8') as fh:",
        "                    data = json.load(fh)",
        "                os.remove(name)",
        "                _import_one(data.get('path', ''))",
        "            except Exception as exc:",
        "                print('[vertexviewer] request failed:', exc)",
        "    except Exception as exc:",
        "        print('[vertexviewer] watcher error:', exc)",
        "    return 0.4",
        "",
        first_line,
        "if FIRST:",
        "    _import_one(FIRST)",
        "os.makedirs(REQ, exist_ok=True)",
        "with open(PID, 'w', encoding='utf-8') as fh:",
        "    fh.write(str(os.getpid()))",
        "bpy.app.timers.register(_tick, first_interval=0.4, persistent=True)",
        "print('[vertexviewer] bridge ready pid', os.getpid())",
        "",
    ])


def launch(model_path: str, *, exe: Optional[str] = None,
           extra_args: Optional[List[str]] = None) -> Optional[subprocess.Popen]:
    """把模型送进 Blender。

    已经有桥接实例在跑 → 投请求，由它导入到当前场景（返回 None）；
    否则新开一个 Blender，直接用常驻脚本导入（不清空场景）。
    """
    if request_import(model_path):
        return None
    blender = exe or blender_exe()
    if not blender:
        raise FileNotFoundError("没找到 blender.exe，可在设置里指定，或设 VERTEXVIEWER_BLENDER")
    script = Path(tempfile.gettempdir()) / "vertexviewer_blender_import.py"
    script.write_text(bridge_script(model_path), encoding="utf-8")
    argv = [blender, "--python", str(script)]
    if extra_args:
        argv.extend(extra_args)
    return subprocess.Popen(argv, close_fds=True)


__all__ = ["GESTURE_THRESHOLD", "blender_candidates", "blender_exe", "bridge_script",
           "import_script", "is_gesture", "launch", "request_import", "session_pid"]

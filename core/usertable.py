"""用户自定义图标表（可分享）。

游戏自带的图标（`I:\\Game\\UIIcon`）只能覆盖一部分资产，剩下的都是
分类色块占位。这里让用户自己给某个资产挑一张图，并且**存成一张可分享的表**：

* 表：``work/icon_table.json``  —— ``{"<资产名>": "icons/xxx.png", ...}``
  用「资产名」当键（不是完整 vpath），这样别人拿到同一份表 + 同一批 png
  也能直接用，不受自己游戏安装路径影响。
* 图片：默认拷到 ``work/icons/``（跟表在一起，打包/分享时整个目录一起给）。

打包版里 ``work/`` 可能是只读的，所以写入失败时自动回退到
``%LOCALAPPDATA%\\VertexViewer\\icons``，并在表里记录绝对路径。
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Dict, Optional

_KIND_SUFFIX = ("_1p_hd", "_3p_hd", "_1p", "_3p", "_ui", "_hd", "_sk", "_lod0", "_lod",
                "_lay_hd", "_lay", "_preview", "_cutscene", "_skeleton")

_table: Optional[Dict[str, str]] = None
_table_path: Optional[str] = None


def _work_dir() -> str:
    try:
        from core import loader
        return loader.WORK
    except Exception:                                          # noqa: BLE001
        return os.path.join(os.getcwd(), "work")


def _fallback_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "VertexViewer", "icons")
    os.makedirs(path, exist_ok=True)
    return path


def table_path() -> str:
    global _table_path
    if _table_path is None:
        _table_path = os.path.join(_work_dir(), "icon_table.json")
    return _table_path


# --------------------------------------------------------------------------- #
# 材质槽（干员/皮肤网格只有 1 个 section，整只模型只能用一个材质；
# 导出体里找不到 section 表，所以让用户按资产手动指定用哪一格，存这里）
# --------------------------------------------------------------------------- #

_mat: Optional[Dict[str, int]] = None
_mat_path: Optional[str] = None


def material_table_path() -> str:
    global _mat_path
    if _mat_path is None:
        _mat_path = os.path.join(_work_dir(), "material_table.json")
    return _mat_path


def _load_mat() -> Dict[str, int]:
    global _mat
    if _mat is None:
        data: Dict[str, int] = {}
        try:
            with open(material_table_path(), encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    try:
                        data[str(k).lower()] = int(v)
                    except Exception:                          # noqa: BLE001
                        continue
        except Exception:                                      # noqa: BLE001
            data = {}
        _mat = data
    return _mat


def _save_mat() -> None:
    table = _load_mat()
    path = material_table_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(table.items())), fh, ensure_ascii=False, indent=1)


def slot_for(vpath: str) -> Optional[int]:
    """这个资产被指定用第几个材质槽（None = 自动）。"""
    table = _load_mat()
    if not table:
        return None
    for cand in _variants(stem_of(vpath)):
        if cand in table:
            return table[cand]
    return None


def set_slot(vpath: str, index: int) -> None:
    load()  # 触发 work/ 目录检查，顺带保证目录存在
    _load_mat()[stem_of(vpath).lower()] = int(index)
    _save_mat()


def clear_slot(vpath: str) -> bool:
    table = _load_mat()
    hit = False
    for cand in list(_variants(stem_of(vpath))):
        if cand in table:
            table.pop(cand, None)
            hit = True
    if hit:
        _save_mat()
    return hit


def stem_of(vpath: str) -> str:
    return os.path.splitext(os.path.basename(str(vpath).replace("\\", "/")))[0]


def _variants(stem: str):
    low = stem.lower()
    yield low
    for suf in _KIND_SUFFIX:
        if low.endswith(suf):
            low = low[: -len(suf)]
            yield low


def load() -> Dict[str, str]:
    global _table
    if _table is None:
        data: Dict[str, str] = {}
        try:
            with open(table_path(), encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                data = {str(k).lower(): str(v) for k, v in raw.items()}
        except Exception:                                      # noqa: BLE001
            data = {}
        _table = data
    return _table


def _save() -> None:
    table = load()
    path = table_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(table.items())), fh, ensure_ascii=False, indent=1)


def override_for(vpath: str) -> Optional[str]:
    """用户给这个资产配过图就返回图片绝对路径。"""
    table = load()
    if not table:
        return None
    for cand in _variants(stem_of(vpath)):
        rel = table.get(cand)
        if not rel:
            continue
        path = rel if os.path.isabs(rel) else os.path.join(_work_dir(), rel)
        if os.path.exists(path):
            return path
    return None


def _normalize(src: str, dest: str, box: int = 256) -> bool:
    """把任意图片压成 `box×box` 的透明底 PNG（等比缩放居中，不裁不变形）。

    卡片上只显示 58px，但导出分享、放大看都要清楚，所以统一存 256。
    Pillow 不在就返回 False，调用方退化成原样拷贝。
    """
    try:
        from PIL import Image
    except Exception:                                          # noqa: BLE001
        return False
    try:
        im = Image.open(src).convert("RGBA")
        im.thumbnail((box, box), Image.LANCZOS)
        canvas = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        canvas.paste(im, ((box - im.width) // 2, (box - im.height) // 2), im)
        canvas.save(dest, "PNG", optimize=True)
        return True
    except Exception:                                          # noqa: BLE001
        return False


def set_override(vpath: str, src_png: str) -> str:
    """把 src_png 记到表里（图片归一到 256px PNG 存进 icons/），返回最终路径。"""
    stem = stem_of(vpath)
    name = f"{stem}.png"
    dest_dir = os.path.join(_work_dir(), "icons")
    rel = os.path.join("icons", name)
    try:
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, name)
        if not _normalize(src_png, dest):
            dest = os.path.join(dest_dir, f"{stem}{os.path.splitext(src_png)[1] or '.png'}")
            shutil.copyfile(src_png, dest)
            rel = os.path.join("icons", os.path.basename(dest))
    except Exception:                                          # noqa: BLE001
        dest = os.path.join(_fallback_dir(), name)
        if not _normalize(src_png, dest):
            shutil.copyfile(src_png, dest)
        rel = dest
    load()[stem.lower()] = rel.replace("\\", "/")
    _save()
    return dest


def clear_override(vpath: str) -> bool:
    table = load()
    hit = False
    for cand in list(_variants(stem_of(vpath))):
        if cand in table:
            table.pop(cand, None)
            hit = True
    if hit:
        _save()
    return hit


def count() -> int:
    return len(load())


def export_table(dest: str) -> str:
    """把表 + 引用的图片打包成一个目录（便于发给别人）。"""
    table = load()
    os.makedirs(dest, exist_ok=True)
    icons_out = os.path.join(dest, "icons")
    os.makedirs(icons_out, exist_ok=True)
    new_table: Dict[str, str] = {}
    for key, rel in table.items():
        path = rel if os.path.isabs(rel) else os.path.join(_work_dir(), rel)
        if not os.path.exists(path):
            continue
        target = os.path.join(icons_out, f"{key}{os.path.splitext(path)[1]}")
        try:
            shutil.copyfile(path, target)
        except Exception:                                      # noqa: BLE001
            continue
        new_table[key] = os.path.join("icons", os.path.basename(target)).replace("\\", "/")
    with open(os.path.join(dest, "icon_table.json"), "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(new_table.items())), fh, ensure_ascii=False, indent=1)
    return dest

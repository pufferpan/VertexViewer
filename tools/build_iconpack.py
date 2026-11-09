"""把游戏 UI 图标压成随包的小图标库（SQLite，一张 PNG 一列）。

游戏里的 `I:\\Game\\UIIcon` 有 1956 张图、123MB（大部分 512~1024），
卡片上只显示 58px，所以构建时统一缩到 92px、PNG 量化后塞进 SQLite，
体积能压到十几 MB，直接跟着安装包走，别人电脑上不装游戏也有图标。

用法： python tools/build_iconpack.py [图标目录] [输出 db]
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import time

from PIL import Image

OUT_SIZE = 92
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIRS = (r"I:\Game\UIIcon", r"G:\Game\UIIcon",
                r"D:\Game\UIIcon", r"E:\Game\UIIcon")
DEFAULT_OUT = os.path.join(ROOT, "work", "icons.db")

_SKIP_DIRS = {"itemicon"}          # 空目录，跳过也无所谓


def _keys(stem: str) -> list:
    """一个文件名可能对应多个键：完整名、去 Icon_ 前缀、下划线前的 ID。"""
    out = []
    low = stem.lower()
    if low.startswith("icon_"):
        out.append(low[5:])
    elif low.startswith("icon"):
        out.append(low[4:])
    out.append(low)
    # `28010020001_18010000012` 这种「ID_ID」组合，两边都要能查到
    for part in re.split(r"[_\s]+", low):
        if part and part not in out:
            out.append(part)
    return [k for k in dict.fromkeys(out) if k]


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else ""
    if not src:
        for d in DEFAULT_DIRS:
            if os.path.isdir(d):
                src = d
                break
    if not src or not os.path.isdir(src):
        print("找不到图标目录", src)
        return 1
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    tmp = out + ".tmp"
    for p in (tmp, tmp + "-journal", tmp + "-wal", tmp + "-shm"):
        if os.path.exists(p):
            os.remove(p)

    conn = sqlite3.connect(tmp)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("CREATE TABLE icons(key TEXT PRIMARY KEY, png BLOB) WITHOUT ROWID")
    conn.execute("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)")

    t0 = time.time()
    n_img = n_row = 0
    total = 0
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS]
        for name in files:
            if not name.lower().endswith(".png"):
                continue
            path = os.path.join(base, name)
            try:
                with Image.open(path) as im:
                    im = im.convert("RGBA")
                    im.thumbnail((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
                    # 量化成 128 色 + 优化，体积能再小一半，肉眼看不出来
                    q = im.quantize(colors=128, method=Image.FASTOCTREE)
                    import io as _io
                    buf = _io.BytesIO()
                    q.save(buf, format="PNG", optimize=True)
                    blob = buf.getvalue()
            except Exception as exc:                              # noqa: BLE001
                print("  跳过", name, exc)
                continue
            n_img += 1
            total += len(blob)
            stem = os.path.splitext(name)[0]
            for key in _keys(stem):
                try:
                    conn.execute("INSERT OR IGNORE INTO icons(key, png) VALUES(?, ?)",
                                 (key, blob))
                    n_row += 1
                except sqlite3.Error:
                    pass
        if n_img % 300 == 0 and n_img:
            print(f"  {n_img} 张…", flush=True)

    conn.execute("INSERT INTO meta(k, v) VALUES('count', ?)", (str(n_img),))
    conn.execute("INSERT INTO meta(k, v) VALUES('built', ?)",
                 (time.strftime("%Y-%m-%d %H:%M"),))
    conn.commit()
    conn.execute("VACUUM")
    conn.commit()
    conn.close()
    if os.path.exists(out):
        os.remove(out)
    os.replace(tmp, out)
    print(f"done: {n_img} 张 / {n_row} 个键 / {total / 1048576:.1f}MB（未压缩）"
          f" -> {out} {os.path.getsize(out) / 1048576:.1f}MB / {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

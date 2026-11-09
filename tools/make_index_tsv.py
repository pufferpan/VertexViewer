"""把 fileindex.json.gz 转成可流式读取的 index.tsv.gz（启动进度条要用）。

为什么不用 JSON：`json.load` 是一次性 C 解析，中间拿不到任何进度，加载界面的
进度条只能假装在动。TSV 一行一个资产，边读边数，进度就是真的
「已读压缩字节 / 总字节」和「已装载条目 / 总条目」。

格式：
    第 1 行    `#VERTEXVIEWER-INDEX\\t1\\t<条目数>`
    之后每行   `资产虚拟路径\\t<pak 名>\\t<偏移>`

用法： python tools/make_index_tsv.py [--force]
"""
from __future__ import annotations

import gzip
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WORK = os.path.join(ROOT, "work")
SRC = os.path.join(WORK, "fileindex.json.gz")
DST = os.path.join(WORK, "index.tsv.gz")


def build(force: bool = False) -> str:
    if os.path.exists(DST) and not force and os.path.getmtime(DST) >= os.path.getmtime(SRC):
        print(f"[tsv] 已是最新：{DST}")
        return DST
    with gzip.open(SRC, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    n = len(data)
    tmp = DST + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as out:
        out.write(f"#VERTEXVIEWER-INDEX\t1\t{n}\n")
        for path, value in data.items():
            try:
                pak, loc = value[0], value[1]
            except Exception:                                  # noqa: BLE001
                continue
            out.write(f"{path}\t{pak}\t{loc}\n")
    os.replace(tmp, DST)
    print(f"[tsv] {n} 条 -> {DST} ({os.path.getsize(DST) / 1024 / 1024:.1f} MB)")
    return DST


if __name__ == "__main__":
    build("--force" in sys.argv)

"""按虚拟路径批量导出 pak 条目：python tools/dump_vpaths.py outdir vpath... 或 --file list.txt"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import loader  # noqa: E402

outdir = sys.argv[1]
args = sys.argv[2:]
if args and args[0] == "--file":
    with open(args[1], encoding="utf-8") as fh:
        args = [ln.strip() for ln in fh if ln.strip()]
os.makedirs(outdir, exist_ok=True)
for vp in args:
    try:
        data = loader.read_entry(vp)
    except Exception as exc:                                     # noqa: BLE001
        print("FAIL", vp, exc)
        continue
    name = vp.rsplit("/", 1)[-1]
    path = os.path.join(outdir, name)
    with open(path, "wb") as fh:
        fh.write(data)
    print(len(data), "->", path)

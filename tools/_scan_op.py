"""快速摸底：Commerical 下的目录结构、干员（Operator）相关资产落在哪。"""
import collections
import os
import sqlite3

DB = os.path.expandvars(r"%LOCALAPPDATA%\VertexViewer\index.db")
con = sqlite3.connect(DB)
cur = con.cursor()


def norm(v: str) -> str:
    return v.replace("/", "\\").lower()


def show(title: str, pairs) -> None:
    print(f"== {title} ==")
    for k, n in pairs:
        print(f"{n:7d}  {k}")
    print()


cnt = collections.Counter()
for (v,) in cur.execute("select vpath from assets where lower(vpath) like '%content/commerical/%'"):
    rest = norm(v).split("commerical\\", 1)[-1]
    parts = rest.split("\\")
    key = "\\".join(parts[:2]) if len(parts) > 1 else parts[0]
    cnt[key] += 1
show("commerical 两级目录", cnt.most_common(18))

cnt = collections.Counter()
for (v,) in cur.execute("select vpath from assets where vpath like '%.uasset' and lower(vpath) like '%operator%'"):
    cnt[os.path.dirname(norm(v))] += 1
show("含 operator 的 uasset 目录", cnt.most_common(12))

cnt = collections.Counter()
for (v,) in cur.execute("select vpath from assets where vpath like '%.uasset' and lower(vpath) like '%/chara%'"):
    cnt[os.path.dirname(norm(v))] += 1
show("含 chara 的 uasset 目录", cnt.most_common(12))

"""看干员本体模型和 Commerical/CharAppear 皮肤分别放在哪、叫什么。"""
import collections
import os
import sqlite3

DB = os.path.expandvars(r"%LOCALAPPDATA%\VertexViewer\index.db")
con = sqlite3.connect(DB)
cur = con.cursor()


def norm(v: str) -> str:
    return v.replace("/", "\\")


def dump(title: str, rows, limit: int = 40) -> None:
    print(f"== {title} ==")
    for r in rows[:limit]:
        print("   ", r)
    if len(rows) > limit:
        print(f"    ... 共 {len(rows)}")
    print()


# 1) 干员本体：Models/Characters* 下的 uasset，按目录归组
rows = []
for (v,) in cur.execute(
        "select vpath from assets where vpath like '%.uasset' "
        "and lower(vpath) like '%content/models/characters%' "
        "and lower(vpath) not like '%/animation/%'"):
    rows.append(os.path.dirname(norm(v)).lower().split("content\\", 1)[-1])
cnt = collections.Counter(rows)
print("== Models/Characters 目录（去动画） ==")
for k, n in cnt.most_common(25):
    print(f"{n:6d}  {k}")
print()

# 2) Commerical/CharAppear 下的结构
cnt = collections.Counter()
for (v,) in cur.execute("select vpath from assets where lower(vpath) like '%commerical/charappear/%'"):
    rest = norm(v).lower().split("charappear\\", 1)[-1]
    parts = rest.split("\\")
    cnt["\\".join(parts[:2]) if len(parts) > 1 else parts[0]] += 1
print("== Commerical/CharAppear 两级 ==")
for k, n in cnt.most_common(25):
    print(f"{n:6d}  {k}")
print()

# 3) CharAppear 里带 skm/sk_ 前缀的模型样例
rows = [v for (v,) in cur.execute(
    "select vpath from assets where lower(vpath) like '%commerical/charappear/%' "
    "and vpath like '%.uasset' and (lower(vpath) like '%skm_%' or lower(vpath) like '%sk_%')")]
dump("CharAppear 里的骨骼模型样例", rows, 20)

# 4) 干员本体骨骼模型样例
rows = [v for (v,) in cur.execute(
    "select vpath from assets where vpath like '%.uasset' and lower(vpath) like '%hero%' "
    "and (lower(vpath) like '%skm_%' or lower(vpath) like '%sk_%')")]
dump("Hero 相关的 SKM/SK 样例", rows, 25)

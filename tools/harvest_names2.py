"""harvest_names2.py —— 重建 work/names.json（v2：DataTable + locres + StringTable 三源）。

比 v1 多做三件事：

1. **字符串来源扩到 StringTable**：把 855 个 `.ustbin` 全解成 `{namespace: {key: text}}`
   和 locres 合并（实测 locres 缺 74 个 namespace / 5000+ key，例如
   `LOC_CommonItemAssets_Weapon` 的 2032 行里就有 locres 没编进去的条目）。
2. **跨表按行号合并**：v1 要求「名字文本」和「模型路径」同时出现在同一行；实际上
   武器/载具的模型路径在 `CommonItemAssets_*`，名字在 `*_Weapon_*`/`NameTable` 等表，
   行号（ItemID）相同。v2 先建 `行号 → 名字`、`行号 → 模型路径` 两个全局索引再合并。
3. **补不出官方名字的给可读派生名**（`conf=0.35, derived=True`）：武器部件按前缀
   （`Rec_` 枪管 / `Muz_` 枪口 / `StockP_` 枪托 …）+ 家族词（`Vector` / `AK74`）拼出
   「Vector · 枪管」这类名字，让模型库至少能读、能搜。

    python tools/harvest_names2.py            # 全量（1~3 分钟）
    python tools/harvest_names2.py --skip-st # 不解析 .ustbin
"""
import argparse
import collections
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(ROOT, "work")
for _p in (ROOT, HERE, WORK):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import dtparse  # noqa: E402
import fetch  # noqa: E402
import mini_upk as mu  # noqa: E402
from ustbin import parse_ustbin  # noqa: E402

NAMES_JSON = os.path.join(WORK, "names.json")
LOC_ZH = os.path.join(WORK, "locres_zh.json")
LOC_EN = os.path.join(WORK, "locres_en.json")
ST_JSON = os.path.join(WORK, "stringtables.json")
CATALOG = r"G:\xmcl-fetch\work\mesh_catalog.json"

TERM_RE = re.compile(r"\[Term#([^\]]+)\]")
NAME_KEYS = ["Name", "DisplayName", "ItemName", "WeaponName", "SkinName", "ShortName",
             "FullName", "Title", "ShowName", "RowName", "Desc", "Description"]


def asset_name(p):
    return str(p or "").replace("\\", "/").rsplit("/", 1)[-1].split(".", 1)[0]


def game_to_vpath(p):
    p = str(p or "").replace("\\", "/")
    if "/Game/" in p:
        return "../../../DeltaForce/Content/" + p.split("/Game/", 1)[1]
    return p


# ------------------------------------------------------------------ 字符串表
def load_stringtables():
    if os.path.exists(ST_JSON):
        try:
            return json.load(open(ST_JSON, encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            pass
    index = fetch.index()
    targets = [p for p in index if p.endswith(".ustbin")]
    out = {}
    t0 = time.time()
    for i, path in enumerate(targets):
        # .ustbin 整个文件就是一个独立小包（前 4 字节是 uasset magic），
        # 直接整块喂给 parse_ustbin
        try:
            blob = fetch.get(path) or b""
        except Exception:                                     # noqa: BLE001
            blob = b""
        if not blob:
            continue
        name, rows = parse_ustbin(blob)
        if not name:
            name = os.path.basename(path).rsplit(".", 1)[0]
        if rows:
            out.setdefault(name, {}).update(dict(rows))
        if (i + 1) % 150 == 0:
            print(f"  ..ustbin {i + 1}/{len(targets)}  表 {len(out)}  {time.time() - t0:.0f}s",
                  flush=True)
    json.dump(out, open(ST_JSON, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"stringtables: {len(out)} 表 / {sum(len(v) for v in out.values())} 行 -> {ST_JSON}")
    return out


class Resolver:
    """按优先级查文本：locres(zh) → StringTable → locres(en)，并展开 [Term#…]。"""

    def __init__(self, zh, st, en):
        self.layers = [d for d in (zh, st, en) if d]
        self.by_key = {}
        for layer in self.layers:
            for _ns, rows in layer.items():
                for k, v in rows.items():
                    if v and k not in self.by_key:
                        self.by_key[k] = v
        self.misses = collections.Counter()

    def raw(self, ns, key):
        for layer in self.layers:
            rows = layer.get(ns) or {}
            v = rows.get(key)
            if v:
                return v
        return self.by_key.get(key, "")

    def expand(self, s, depth=3):
        if not s or "[Term#" not in s:
            return s
        for _ in range(depth):
            m = TERM_RE.search(s)
            if not m:
                break
            s = s[:m.start()] + self.by_key.get(m.group(1), "") + s[m.end():]
            if "[Term#" not in s:
                break
        return s

    def resolve(self, ns, key, lang=0):
        if lang:
            layer = self.layers[lang] if lang < len(self.layers) else {}
            v = (layer.get(ns) or {}).get(key, "")
            return self.expand(v).strip() if v else ""
        v = self.raw(ns, key)
        if not v:
            self.misses[ns] += 1
            return ""
        return self.expand(v).strip()


def ns_of_table(ftext_table):
    if not ftext_table:
        return ""
    t = ftext_table.rsplit("/", 1)[-1]
    return t.rsplit(".", 1)[-1] or t


# ------------------------------------------------------------------ DataTable
def scan_tables(texts_by_id, paths_by_id, row_texts, row_paths, stats):
    index = fetch.index()
    tables = sorted(p for p in index if "/DataTables/" in p and p.endswith(".uasset"))
    print("datatables:", len(tables))
    t0 = time.time()
    for i, path in enumerate(tables):
        try:
            upk = mu.Upk(fetch.get(path), fetch.get(path[:-7] + ".uexp") or b"")
            if not upk.exports:
                stats["no_export"] += 1
                continue
            data = upk.export_data(upk.exports[0])
            rows, _end, _n = dtparse.walk(data, upk.names)
            stats["tables_ok"] += 1
            stats["rows"] += len(rows)
        except Exception:                                     # noqa: BLE001
            stats["tables_fail"] += 1
            continue
        for row_name, props in rows:
            texts, paths = [], []
            for nm, typ, size, aidx, vs, vl in props:
                if typ == "TextProperty":
                    info = dtparse.text_info(data, vs, upk.names) or {}
                    if info.get("key"):
                        texts.append((nm, ns_of_table(info.get("table")), info["key"]))
                elif typ in ("StructProperty", "SoftObjectProperty", "ObjectProperty"):
                    if vl > 16:      # 只认 12/16 字节的 SoftObjectPath，大结构体里扫是乱猜
                        continue
                    s = dtparse.softpath(data, vs, upk.names, vl)
                    if s and "/Models/" in s:
                        paths.append((nm, s))
            key = (path, row_name)
            if texts:
                row_texts[key] = texts
                for nm, ns, k in texts:
                    # (字段名, 命名空间, key) —— 字段名很重要：`Name` 和
                    # `SimpleDescription` 都是 TextProperty，但只有前者是名字
                    texts_by_id.setdefault(row_name, []).append((nm, ns, k))
            if paths:
                row_paths[key] = paths
                for nm, s in paths:
                    paths_by_id.setdefault(row_name, []).append((nm, s, path))
        if (i + 1) % 400 == 0:
            print(f"  ..{i + 1}/{len(tables)} 行 {stats['rows']} 文本行 {len(row_texts)} "
                  f"路径行 {len(row_paths)}  {time.time() - t0:.0f}s", flush=True)
    return tables


def looks_like_name(val: str) -> bool:
    """过滤掉「本地化查出来是个等级字母」的情况。

    `LOC_BattleSectorTable` 这类表里同一个行号下挂着的是评级（A~F），
    按行号跨表补齐时会把枪管配成「C」。真名字至少两个字，
    而且不会是单个字母/数字。
    """
    v = (val or "").strip()
    if len(v) < 2:
        return False
    if re.fullmatch(r"[A-Za-z0-9\-\+\.\s]{1,2}", v):
        return False
    return True


def pick_name(resolver, texts, prefer_ns=""):
    """从一行里的若干个 (字段, ns, key) 中挑最像名字且能解出中文的。"""
    best = None
    ordered = sorted(texts, key=lambda t: (NAME_KEYS.index(t[0]) if t[0] in NAME_KEYS else 99,
                                           len(t[2])))
    for nm, ns, key in ordered:
        if prefer_ns and ns != prefer_ns:
            continue
        val = resolver.resolve(ns, key)
        if val and looks_like_name(val):
            conf = 0.95 if nm in ("Name", "DisplayName", "ItemName") else 0.75
            best = (val, ns, key, nm, conf)
            break
    return best


# ------------------------------------------------------------------ 派生名
PART_WORDS = [
    ("MagFollower", "托弹板"), ("Muzzle", "枪口"), ("Barrel", "枪管"), ("StockPad", "枪托垫"),
    ("StockP", "枪托"), ("Stock", "枪托"), ("Handguard", "护木"), ("RailCover", "导轨盖"),
    ("Rail", "导轨"), ("Grip", "握把"), ("Trigger", "扳机"), ("Bolt", "枪机"), ("DustCover", "防尘盖"),
    ("Charging", "拉机柄"), ("Bipod", "脚架"), ("Scope", "瞄具"), ("Sight", "瞄具"),
    ("Muz", "枪口"), ("Rec", "枪管"), ("Mag", "弹匣"), ("Ammo", "弹药"), ("Piston", "导气活塞"),
    ("GasBlock", "导气箍"), ("BufferTube", "缓冲管"), ("Cheek", "贴腮板"), ("Butt", "托底"),
    ("Other", "配件"), ("ScopeMount", "瞄具座"), ("Mount", "支架"),
    ("Helmet", "头盔"), ("Armor", "护甲"), ("Backpack", "背包"), ("Rig", "胸挂"),
    ("Keycard", "门卡"), ("Key", "钥匙"),
]
# `Xxx_Base` / `Xxx_Preview` 这类后缀也是常见的「本体/预览」网格
TAIL_WORDS = [("_base", "本体"), ("_preview", "预览图"), ("_preview2", "预览图"),
              ("_cd", "过场"), ("_cutscene", "过场"), ("_anim", "动画用")]
FAMILY_RE = re.compile(r"(AK-?12|AK-?15|AK74|M4A1|M16|M14|SCAR-?H|SCAR-?L|AUG|Vector|MP5|MP7|"
                       r"MP9|P90|SR25|SR-?25|M700|M870|M250|QBZ-?95|QBZ-?191|ASVal|AS-?Val|"
                       r"PKM|RPK|G3|FAL|SCAR|UMP|M249|M60|DEagle|Deagle|Glock|M9|P226|"
                       r"K416|K437|KC17|K145|AWM|SV98|SVD|VSS|M4|M7|"
                       # 载具
                       r"AAV7|CSVP4|LAV-?25|LAV|M1A2|M1|T-?90|T90|BMP-?2|BMP|AH-?64|AH64|"
                       r"UH-?60|Mi-?8|WZ-?11|WZ11|Z-?10|Z10|FV-?510|FV510|M2A3)", re.I)


def derive_name(stem: str, folder: str) -> str:
    """给没查到官方名的模型拼一个能读的名字：<家族> · <部件类型>。"""
    part = ""
    for prefix, word in TAIL_WORDS:
        if stem.lower().endswith(prefix):
            part = word
            break
    if not part:
        for prefix, word in PART_WORDS:
            # 必须落在「词边界」上：`Butt` 能匹配 `Butt_02`，不能匹配 `Butterfly`
            pattern = r"(?:^|_)" + re.escape(prefix) + r"(?=_|[A-Z]|\d|$)"
            if re.search(pattern, stem):
                part = word
                break
    if not part:
        head = re.split(r"[_\-]", stem, 1)[0]
        for prefix, word in PART_WORDS:
            if head.lower() == prefix.lower():
                part = word
                break
    fam = ""
    m = FAMILY_RE.search(stem) or FAMILY_RE.search(folder or "")
    if m:
        fam = m.group(1).upper().replace("-", "")
    # 家族名只认 FAMILY_RE 里那些真实型号（AK74 / AAV7 / …）。
    # 早先用「第一个不是噪声的 token」当家族，结果拼出 `SeasonQuest`、
    # `Government`、`CCOLD` 这种把目录/皮肤前缀当型号的假名字，已废弃：
    # 拿不到型号就只显示部件类型（「头盔」），再拿不到就返回空串让 UI 显示资产名。
    if fam and part:
        return f"{fam} · {part}"
    if part:
        return part
    return ""


def classify(pkg, cn, ns=""):
    p = (pkg or "").lower()
    c = cn or ""
    # 名字里出现的词（中文为主，安全）；「D6 战术头盔」目录在 Weapons 里，
    # 但东西是头盔，所以名字优先。
    name_rules = [
        ("载具", ("坦克", "装甲车", "直升机", "防空", "步战", "运兵车")),
        ("装备", ("头盔", "护甲", "胸挂", "背包", "防弹衣", "面罩", "防毒", "战术背心")),
        ("配件", ("枪管", "枪口", "枪托", "握把", "瞄具", "护木", "弹匣", "导轨",
                  "弹鼓", "前匣", "消焰", "消音", "脚架", "机匣", "倍镜", "瞄准镜",
                  "狙击镜", "热成像", "红点", "全息", "镭射", "激光")),
        ("道具", ("钥匙", "门卡", "医疗", "消耗", "针剂", "弹药箱")),
        ("武器", ("步枪", "冲锋枪", "霰弹枪", "狙击", "手枪", "机枪", "近战", "手榴弹")),
    ]
    dir_rules = [
        ("载具", ("/models/vehicles/", "/armorvehicle", "armorvehicle", "/vehicle")),
        ("角色", ("/models/characters/hero", "/characters/hero")),
        ("AI", ("/models/characters/ai", "characters_hd/ai", "characters/boss")),
        ("装备", ("/models/equipments", "/armors", "/helmets", "/backpacks", "/rigs")),
        ("道具", ("/models/props/", "/models/items/", "/collect/", "/props/")),
        ("配件", ("weapons/parts", "/parts/")),
        ("武器", ("/models/weapons/",)),
    ]
    for cat, keys in name_rules:
        if any(k in c for k in keys):
            return cat
    for cat, keys in dir_rules:
        if any(k in p for k in keys):
            return cat
    return "其他"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-st", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    zh = json.load(open(LOC_ZH, encoding="utf-8")) if os.path.exists(LOC_ZH) else {}
    en = json.load(open(LOC_EN, encoding="utf-8")) if os.path.exists(LOC_EN) else {}
    st = {} if args.skip_st else load_stringtables()
    print(f"locres zh ns={len(zh)} en ns={len(en)}  stringtable ns={len(st)}")
    R = Resolver(zh, st, en)

    texts_by_id, paths_by_id = {}, {}
    row_texts, row_paths = {}, {}
    stats = collections.Counter()
    scan_tables(texts_by_id, paths_by_id, row_texts, row_paths, stats)
    print(f"行内：文本行 {len(row_texts)} 路径行 {len(row_paths)}；"
          f"行号索引：名字 {len(texts_by_id)} 路径 {len(paths_by_id)}")

    # ---- 1) 同行配对
    votes = collections.defaultdict(collections.Counter)
    meta = {}
    same_row = 0
    for key, texts in row_texts.items():
        paths = row_paths.get(key)
        if not paths:
            continue
        picked = pick_name(R, texts)
        if not picked:
            continue
        cn, ns, tkey, prop, conf = picked
        for pprop, path in paths:
            stem = asset_name(path)
            if not stem:
                continue
            votes[stem][cn] += 1
            rec = {"cn": cn, "en": "", "conf": conf, "src": f"{ns}:{key[1]}",
                   "pkg": game_to_vpath(path), "prop": pprop, "ns": ns,
                   "key": tkey, "row": key[1]}
            if stem not in meta or conf > meta[stem]["conf"]:
                meta[stem] = rec
            same_row += 1
    print(f"同行配对 {same_row} 条，覆盖 stem {len(votes)}")

    # ---- 2) 跨表按行号补齐（路径行没有文本，或文本行没有路径）
    # 同一个行号在别的表里也可能挂着 TextProperty，但那可能是「描述/属性」而不是
    # 名字（曾经把 `props_keycard_Dam_Gold_710` 配成「耐久度：20」）。所以这里按
    # 「字段名像名字 → key 以 _Name 结尾 → key 带 Desc 的排最后」打分后再取。
    def _rank(entry, row_name=""):
        nm, _ns, key = entry
        score = 0
        if nm in NAME_KEYS:
            score -= 4
        low = f"{nm} {key}".lower()
        if key.lower().endswith("_name") or key.lower().endswith("name"):
            score -= 3
        # 行号关联最硬的证据：本地化 key 的前缀就是行号（如 15200000056_Name）
        if row_name and key.startswith(str(row_name)):
            score -= 6
        elif row_name:
            score += 4
        if "desc" in low or "attribute" in low or "tip" in low or "hint" in low \
                or key.lower().endswith(("_shortname", "_subname")):
            score += 5
        return score

    # 这些 namespace 是「输入映射/设置界面」的文案（返回、关闭…），
    # 按行号补齐会把曲线资产配成「返回」。曲线资产本身也不是网格，直接跳过。
    SKIP_NS = ("DisplayInputAction", "InputAction", "Settings", "Options")
    added = 0
    for key, paths in row_paths.items():
        for _pprop, path in paths:
            stem = asset_name(path)
            if not stem or stem in votes or "/Curve/" in path:
                continue
            row_name = key[1]
            raw = sorted(texts_by_id.get(row_name, []),
                         key=lambda e, rn=row_name: _rank(e, rn))[:8]
            # 两档：A 档「行号前缀对得上」= conf 0.7；B 档只有名字字段本身可信 = conf 0.5。
            # 但凡字段像描述/属性（Desc/Attribute/Tip/Hint）一律不要，宁可留空。
            candidates = []
            for cand in raw:
                score = _rank(cand, row_name)
                nm, cns, ckey = cand
                low = f"{nm} {ckey}".lower()
                if any(skip in cns for skip in SKIP_NS):
                    continue
                nameish = nm in NAME_KEYS or ckey.lower().endswith(("_name", "name"))
                if "desc" in low or "attribute" in low or "tip" in low or "hint" in low \
                        or ckey.lower().endswith(("_shortname", "_subname")):
                    continue
                if score < 4:
                    candidates.append((cand, 0.7))
                elif nameish:
                    candidates.append((cand, 0.5))
            for (nm, ns, tkey), conf in candidates:
                val = R.resolve(ns, tkey)
                if val and looks_like_name(val):
                    votes[stem][val] += 1
                    if stem not in meta or conf > meta[stem]["conf"]:
                        meta[stem] = {"cn": val, "en": "", "conf": conf,
                                      "src": f"{ns}:{row_name}", "pkg": game_to_vpath(path),
                                      "prop": _pprop, "ns": ns, "key": tkey, "row": row_name,
                                      "field": nm}
                    added += 1
                    break
    print(f"跨表按行号补齐 {added} 条，覆盖 stem {len(votes)}")

    catalog = {}
    if os.path.exists(CATALOG):
        catalog = json.load(open(CATALOG, encoding="utf-8"))
    models = [asset_name(k) for k, v in catalog.items()
              if v in ("StaticMesh", "SkeletalMesh")]
    folders = {asset_name(k): k for k, v in catalog.items()
               if v in ("StaticMesh", "SkeletalMesh")}

    out = {}
    for stem, counter in votes.items():
        cn = counter.most_common(1)[0][0]
        rec = dict(meta.get(stem) or {})
        rec["cn"] = cn
        rec["hits"] = sum(counter.values())
        rec["alts"] = [a for a, _ in counter.most_common(3)[1:]]
        rec["cat"] = classify(rec.get("pkg", ""), cn, rec.get("ns", ""))
        rec.setdefault("conf", 0.6)
        rec.setdefault("en", "")
        out[stem] = rec

    # ---- 3) 派生名兜底
    derived = 0
    for stem in models:
        if stem in out and (out[stem].get("cn") or "").strip():
            continue
        folder = str(folders.get(stem, "")).rsplit("/", 1)[0]
        label = derive_name(stem, folder)
        if not label:
            continue
        out[stem] = {"cn": label, "en": "", "conf": 0.35, "derived": True,
                     "src": "derived:part-prefix", "pkg": folders.get(stem, ""),
                     "prop": "", "ns": "", "cat": classify(folders.get(stem, ""), label)}
        derived += 1
    print(f"派生名补 {derived} 个，总映射 {len(out)}")

    by_ns = collections.Counter((r.get("src") or ":").split(":")[0] for r in out.values())
    src = dict(stats)
    src.update({
        "by_namespace": dict(by_ns.most_common()),
        "by_cat": dict(collections.Counter(r.get("cat", "其他") for r in out.values()).most_common()),
        "conf_ge_0.9": sum(1 for r in out.values() if r.get("conf", 0) >= 0.9),
        "derived": derived,
        "note": "cn 优先取 locres(zh-Hans)，缺了用 StringTable(.ustbin) 与 en 兜底；"
                "同行配对 conf=0.95/0.75，跨表行号关联 conf=0.7，派生名 conf=0.35(derived=true)",
    })
    payload = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "source": src, "map": out}
    json.dump(payload, open(NAMES_JSON, "w", encoding="utf-8"), ensure_ascii=False)
    named_models = sum(1 for m in models if (out.get(m, {}).get("cn") or "").strip())
    print(f"names.json: {len(out)} 条  覆盖模型 {named_models}/{len(models)}  "
          f"{os.path.getsize(NAMES_JSON) / 1e6:.1f} MB  {time.time() - t0:.0f}s")
    for cat, n in collections.Counter(r.get("cat", "其他") for r in out.values()).most_common():
        print(f"   {cat:6s} {n}")


if __name__ == "__main__":
    main()

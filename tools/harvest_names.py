#!/usr/bin/env python
"""harvest_names.py —— 一条命令重建 work/names.json（该游戏 模型资产 → 中文名）。

流水线：
  1. 抽取所有 zh-Hans / en 的 .locres（FTextLocalizationResource）→ work/locres_{zh,en}.json
  2. 遍历 Content/DataTables/**/*.uasset（DataTable），逐行解析 tag：
       行名(ItemID/RowName) + TextProperty(FText→字符串表 key) + SoftObjectPath(模型路径)
  3. FText key 回查 locres（表名 = LOC_<DataTable 名>），解析 [Term#xxx_yyy] 交叉引用
  4. 同行的「模型路径」与「中文名」配对 → 资产名列 → 中文名
  5. 合并去重 + 置信度 + 分类，写 work/names.json

用法：
  python tools/harvest_names.py                # 全量（约 1-3 分钟）
  python tools/harvest_names.py --only 4       # 只跑前 4 张表（调试）
  python tools/harvest_names.py --lang en      # 只重建 en 本地化
  python tools/harvest_names.py --no-locres    # 跳过 locres 重建
"""
import sys, os, json, time, collections, re, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(ROOT, 'work')
for p in (ROOT, HERE, WORK):
    if p not in sys.path:
        sys.path.insert(0, p)

import fetch                     # noqa: E402
import mini_upk as mu            # noqa: E402
import dtparse                   # noqa: E402
import locres                    # noqa: E402

NAMES_JSON = os.path.join(WORK, 'names.json')
LOC_ZH = os.path.join(WORK, 'locres_zh.json')
LOC_EN = os.path.join(WORK, 'locres_en.json')

LANGS = {'zh': ('/zh-Hans/', '/zh/'), 'en': ('/en/',)}

# 名字类字段优先级（越小越优先）
NAME_KEYS = ['Name', 'DisplayName', 'ItemName', 'WeaponName', 'SkinName', 'ShortName',
             'FullName', 'Title', 'RowName', 'ShowName', 'Desc', 'Description']
# 路径类字段前缀（用于挑「主模型」）
PATH_PREF = ['item1pmeshpath', 'item3pmeshpath', 'itemuimeshpath', 'itemdroppedmeshpath',
             'meshpath', 'mesh', 'skeletalmesh', 'staticmesh', 'sk', 'modelpath',
             'itemuimeshlist', 'itemdroppedmesglist', 'previewmesh']

TERM_RE = re.compile(r'\[Term#([^\]]+)\]')


def game_to_vpath(p):
    """'/Game/X/Y.Z' -> '../../../DeltaForce/Content/X/Y'"""
    if not p:
        return p
    q = p.split('.')[0]
    if q.startswith('/Game/'):
        return '../../../DeltaForce/Content/' + q[len('/Game/'):]
    if q.startswith('/Engine/'):
        return '../../../Engine/Content/' + q[len('/Engine/'):]
    return q


def asset_name(p):
    """'/Game/Models/A/B/C_1P.C_1P' -> 'C_1P'"""
    q = p.split('.')[0].rstrip('/')
    return q.rsplit('/', 1)[-1] if q else ''


# ---------------------------------------------------------------- locres
def build_locres(lang, out, force=False):
    if os.path.exists(out) and not force:
        try:
            return json.load(open(out, encoding='utf-8'))
        except Exception:
            pass
    idx = fetch.index()
    wanted = LANGS[lang]
    cands = [p for p in idx if p.endswith('.locres') and any(w in p for w in wanted)]
    cands.sort(key=lambda p: (wanted[0] not in p, p))
    merged = {}
    t0 = time.time()
    for p in cands:
        try:
            data = fetch.get(p)
            ver, ns, lut, used = locres.parse(data)
        except Exception as e:
            print('  locres FAIL', p.split('/')[-1], repr(e)[:70])
            continue
        for nsn, d in ns.items():
            tgt = merged.setdefault(nsn, {})
            for k, v in d.items():
                if v and k not in tgt:
                    tgt[k] = v
        print('  %-34s ns=%-4d %6.2fs' % (p.split('/')[-1], len(ns), time.time() - t0))
    json.dump(merged, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print('locres[%s] namespaces=%d keys=%d -> %s (%.1f MB)'
          % (lang, len(merged), sum(len(v) for v in merged.values()), out,
             os.path.getsize(out) / 1e6))
    return merged


class Names:
    """locres 查询器：namespace 精确 → key 全局回退 → [Term#…] 递归展开。"""

    def __init__(self, L):
        self.L = L
        self.bykey = {}
        for nsn, d in L.items():
            for k, v in d.items():
                if k not in self.bykey:
                    self.bykey[k] = v
        self.misses = collections.Counter()

    def lookup(self, ns, key):
        if key in self.L.get(ns, {}):
            return self.L[ns][key]
        if key in self.bykey:
            return self.bykey[key]
        return ''

    def expand(self, s, depth=3):
        if not s or '[Term#' not in s:
            return s
        for _ in range(depth):
            m = TERM_RE.search(s)
            if not m:
                break
            rep = self.bykey.get(m.group(1), '')
            s = s[:m.start()] + rep + s[m.end():]
            if '[Term#' not in s:
                break
        return s

    def resolve(self, ns, key):
        raw = self.lookup(ns, key)
        if not raw:
            self.misses[ns] += 1
            return ''
        return self.expand(raw).strip()


def ns_of_table(ftext_table):
    """'/Game/StringTables/.../LOC_CommonItemAssets_Weapon.LOC_...' -> 'LOC_CommonItemAssets_Weapon'"""
    if not ftext_table:
        return ''
    t = ftext_table.rsplit('/', 1)[-1]
    return t.rsplit('.', 1)[-1] or t


# ---------------------------------------------------------------- datatable
def datatable_paths():
    idx = fetch.index()
    return sorted(p for p in idx
                  if '/DataTables/' in p and p.endswith('.uasset'))


def harvest_table(path, N, stats, want_models_only=False):
    """-> list of (stem, cn, en, ns, key, row, prop, pkg_path, conf)"""
    out = []
    try:
        uasset = fetch.get(path)
        uexp = fetch.get(path[:-7] + '.uexp') or b''
        upk = mu.Upk(uasset, uexp)
        if not upk.exports:
            stats['no_export'] += 1
            return out
        d = upk.export_data(upk.exports[0])
        names = upk.names
        t0 = time.time()
        rows, end, n = dtparse.walk(d, names)
        stats['tables_ok'] += 1
        stats['rows'] += len(rows)
        stats['seconds'] += time.time() - t0
    except Exception as e:
        stats['tables_fail'] += 1
        if stats['tables_fail'] <= 8:
            print('  DT FAIL', path.split('/')[-1], repr(e)[:90])
        return out

    tname = asset_name(path)
    for rn, ps in rows:
        texts, paths = [], []
        for nm, typ, size, aidx, vs, vl in ps:
            low = nm.lower()
            if typ == 'TextProperty':
                info = dtparse.text_info(d, vs, names)
                if info and info.get('key'):
                    texts.append((nm, ns_of_table(info.get('table')), info['key'],
                                  info.get('history', '')))
            elif typ in ('StructProperty', 'SoftObjectProperty', 'ObjectProperty'):
                if vl > 16:          # 只认 12/16 字节的 SoftObjectPath，大结构体里扫是乱猜
                    continue
                s = dtparse.softpath(d, vs, names, vl)
                if s and '/Models/' in s:
                    paths.append((nm, s))
        if not texts or not paths:
            continue
        # 选名字
        texts.sort(key=lambda t: (NAME_KEYS.index(t[0]) if t[0] in NAME_KEYS else 99,
                                  len(t[2])))
        cn = ''
        chosen = None
        for nm, ns, key, hist in texts:
            cn = N.resolve(ns, key)
            if cn:
                chosen = (nm, ns, key, hist)
                break
        if not cn:
            stats['rows_no_cn'] += 1
            continue
        # 选路径：优先 Item1P/Item3P 等主模型
        paths.sort(key=lambda p: (PATH_PREF.index(p[0].lower())
                                  if p[0].lower() in PATH_PREF else 99, len(p[1])))
        conf_base = 0.95 if chosen[0] in ('Name', 'DisplayName', 'ItemName') else 0.75
        for pnm, p in paths:
            if want_models_only and '/Models/' in p:
                pass
            stem = asset_name(p)
            if not stem or stem[:3] in ('T_V', 'MI_', 'MPC', 'MF_') or stem.startswith('T_'):
                continue
            is_model = '/Models/' in p
            out.append((stem, cn, '', chosen[1], chosen[2], rn, pnm, p,
                        conf_base if is_model else 0.6))
            stats['pairs'] += 1
            if is_model:
                stats['pairs_model'] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', type=int, default=0)
    ap.add_argument('--lang', default='both')
    ap.add_argument('--no-locres', action='store_true')
    ap.add_argument('--tables', default='')
    args = ap.parse_args()

    t0 = time.time()
    if args.lang in ('both', 'zh'):
        if args.no_locres and os.path.exists(LOC_ZH):
            L = json.load(open(LOC_ZH, encoding='utf-8'))
        else:
            L = build_locres('zh', LOC_ZH, force=not args.no_locres)
    else:
        L = json.load(open(LOC_ZH, encoding='utf-8'))
    LE = {}
    if args.lang in ('both', 'en'):
        if args.no_locres and os.path.exists(LOC_EN):
            LE = json.load(open(LOC_EN, encoding='utf-8'))
        else:
            LE = build_locres('en', LOC_EN, force=not args.no_locres)
    N = Names(L)
    NE = Names(LE) if LE else None
    print('locres zh ns=%d keys=%d   en ns=%d keys=%d'
          % (len(L), len(N.bykey), len(LE), len(NE.bykey) if NE else 0))

    paths = datatable_paths()
    if args.tables:
        want = set(args.tables.split(','))
        paths = [p for p in paths if any(w and w in p for w in want)]
    if args.only:
        paths = paths[:args.only]
    print('datatables: %d' % len(paths))

    stats = collections.Counter()
    entries = []
    t1 = time.time()
    for i, p in enumerate(paths):
        entries += harvest_table(p, N, stats, want_models_only=False)
        if (i + 1) % 200 == 0:
            print('  %d/%d  pairs=%d model=%d %.0fs'
                  % (i + 1, len(paths), stats['pairs'], stats['pairs_model'],
                     time.time() - t1))
    print('harvest: tables_ok=%d fail=%d rows=%d pairs=%d model_pairs=%d rows_no_cn=%d %.0fs'
          % (stats['tables_ok'], stats['tables_fail'], stats['rows'], stats['pairs'],
             stats['pairs_model'], stats['rows_no_cn'], time.time() - t1))

    # 合并：同一 stem 取票数最多的中文名
    votes = collections.defaultdict(collections.Counter)
    meta = {}
    for stem, cn, en, ns, key, row, pnm, pkg, conf in entries:
        votes[stem][cn] += 1
        if stem not in meta or conf >= meta[stem]['conf']:
            meta[stem] = {'en': en, 'cat': '', 'conf': conf,
                          'src': '%s:%s' % (ns, row),
                'pkg': game_to_vpath(pkg), 'prop': pnm, 'ns': ns, 'key': key,
                'row': row}
    out = {}
    conflicts = 0
    for stem, c in votes.items():
        cn, n = c.most_common(1)[0]
        if len(c) > 1:
            conflicts += 1
        m = meta[stem]
        m = dict(m)
        m['src'] = m.get('src') or ''
        out[stem] = {'cn': cn, 'en': m.get('en', ''), 'cat': m.get('cat', ''),
                     'conf': round(m.get('conf', 0.6), 2), 'src': m.get('src', ''),
                     'pkg': m.get('pkg', ''), 'prop': m.get('prop', ''),
                     'ns': m.get('ns', ''),
                     'hits': n, 'alts': [a for a, _ in c.most_common(3)[1:]]}

    # 分类
    for stem, rec in out.items():
        rec['cat'] = classify(rec.get('pkg', ''), rec['cn'], rec.get('ns', ''))

    # 来源/分布统计（自解释，UI 和验收脚本都吃这个）
    by_ns = collections.Counter((r.get('src') or ':').split(':')[0] for r in out.values())
    src = dict(stats)
    src.update({
        'by_namespace': dict(by_ns.most_common()),
        'by_cat': dict(collections.Counter(r['cat'] for r in out.values()).most_common()),
        'conf_ge_0.9': sum(1 for r in out.values() if r['conf'] >= 0.9),
        'conf_lt_0.6': sum(1 for r in out.values() if r['conf'] < 0.6),
        'note': 'cn 来自 locres(zh-Hans) 文本，经 DataTable 行内 SoftObjectPath 绑到模型资产；'
                'src=<locres namespace>:<行名>；conf>=0.9 = 名字字段是 Name/DisplayName 且路径在 /Models/ 下；'
                'conf<0.6 是跨表模糊关联（猜的）',
    })
    data = {
        'generated': time.strftime('%Y-%m-%d %H:%M:%S'),
        'source': src,
        'map': out,
    }
    json.dump(data, open(NAMES_JSON, 'w', encoding='utf-8'), ensure_ascii=False)
    print('\nnames.json: %d 条映射  conflicts=%d  %.1f MB  %.0fs'
          % (len(out), conflicts, os.path.getsize(NAMES_JSON) / 1e6, time.time() - t0))
    cats = collections.Counter(r['cat'] for r in out.values())
    for k, v in cats.most_common():
        print('   %-14s %d' % (k, v))
    miss = sum(N.misses.values())
    print('locres misses=%d  (top: %s)' % (miss, N.misses.most_common(5)))


CAT_RULES = [
    ('配件', ('weapons/parts', 'weaponpart', '子弹', '弹药', '弹匣', '枪管', '枪托', '握把',
             '瞄具', '护木', '消音', '弹鼓', '导轨', '扳机', '枪口', '后坐', '准星',
             '弹夹', '弹链', '枪机', '撞针', '上机匣', '下机匣')),
    ('武器', ('weapons/guns', 'weapons/melees', 'weapons/bowparts', 'weapons/throwweapon',
             '步枪', '冲锋枪', '霰弹枪', '狙击', '轻机枪', '手枪', '近战', '弓弩', '投掷')),
    ('角色', ('characters/hero', 'characters_hd/hero', '干员', '特勤处')),
    ('AI', ('characters/ai', 'characters_hd/ai', 'characters/boss', 'characters_hd/boss',
            'characters_hd/npc', '敌方', '小兵')),
    ('载具', ('vehicles', '载具', '坦克', '装甲车', '直升机', '越野车')),
    ('装备', ('equipments', '头盔', '护甲', '胸挂', '背包', '防弹')),
    ('道具', ('props', '消耗', '医疗', '食物', '钥匙', '材料', '电子')),
]


NS_CAT = [('VehicleSkin|VehicleModification|VehicleUnlock|CommonItemAssets_Vehicle', '载具'),
          ('AmmoDataTable', '弹药'),
          ('WeaponSkin|MeleeWeaponSkin|MysticalSkin|Wear', '皮肤'),
          ('PartSockets|PartsDataTable|PartsStyle|PartAttribute', '配件'),
          ('Hero', '干员'),
          ('Pendant', '挂饰'),
          ('AICharacter', 'AI')]


def classify(pkg, cn, ns=''):
    p = (pkg or '').lower()
    SEG_CAT = [('/models/vehicles/', '载具'),
               ('/models/characters', '角色'),
               ('/models/equipments', '装备'),
               ('/models/props/', '道具'),
               ('/models/weapons/pendant/', '皮肤'),
               ('/models/weapons/', '武器')]
    for cat, keys in CAT_RULES:
        for k in keys:
            if ('/' in k or '_' in k) and k in p:
                return cat
    for cat, keys in CAT_RULES:
        for k in keys:
            if '/' not in k and '_' not in k and k in (cn or ''):
                return cat
    for pat, cat in SEG_CAT:
        if pat in p:
            return cat
    for pat, cat in NS_CAT:
        if pat.lower() in (ns or '').lower():
            return cat
    return '其他'


if __name__ == '__main__':
    main()

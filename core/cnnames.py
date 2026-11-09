"""cnnames —— 该游戏资产 → 中文名映射，只读查询层。

数据来自 `work/names.json`（由 `tools/harvest_names.py` 从 DataTable + locres 挖出来）。
首次调用任意函数时懒加载（约 3MB JSON），之后走内存索引。

    from core.cnnames import resolve_cn, category, search_cn
    resolve_cn('../../../DeltaForce/Content/Models/Weapons/Parts/FroS/FroS_M4A1-Std_001/FroS_M4A1-Std_001_1P.uasset')
    # -> 'M4A1前准星'

匹配顺序（逐级降级，命中不了返回 ''）：
    1. 精确资产名（去掉 .uasset/.uexp 后的最后一段）
    2. 剥后缀重试：_LOD0.._LOD9 / _1P / _3P / _UI / _SK / _VM / _PhysicsAsset / 末尾 _数字
    3. 补后缀重试：拿不到就给资产名加 _1P / _3P / _UI / _SK 再查
    4. 同目录 + 文件名前缀模糊（同目录里前缀相同的兄弟资产，conf 会降到 0.5 并标 fuzzy）
"""
from __future__ import annotations

import json
import os
import re
import threading

_DATA = None
_PATH = None
_lock = threading.Lock()

_MODEL_EXT = ('.uasset', '.uexp', '.ubulk', '.umap')

# 剥后缀：一次剥一层，循环剥到剥不动
_SUF_RES = [
    re.compile(r'[_-]physicsasset$', re.I),
    re.compile(r'[_-]skeleton$', re.I),
    re.compile(r'[_-]skeletalmesh$', re.I),
    re.compile(r'[_-]lod\d*$', re.I),
    re.compile(r'[_-](1p|3p|ui|sk|vm|hd|low|mid|high|mat|inst|bp)$', re.I),
    re.compile(r'[_-](lod|sk|mesh)\d+$', re.I),
]
_NUM_TAIL = re.compile(r'\d{1,3}$')
_ADD_SUFFIX = ('_1P', '_3P', '_UI', '_SK')


# ------------------------------------------------------------------ 载入
def _default_path() -> str:
    """名字表的真实路径：打包进程序内部的那份优先，`data/` 里放同名文件可覆盖。"""
    try:
        from .loader import data_file
        hit = data_file('names.json')
        if hit:
            return hit
    except Exception:                                            # noqa: BLE001
        pass
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, 'work', 'names.json')


def load(force: bool = False) -> dict:
    """懒加载 names.json，返回 {资产名: 记录}（同一对象，别改）。"""
    global _DATA, _PATH
    if _DATA is not None and not force:
        return _DATA
    with _lock:
        if _DATA is not None and not force:
            return _DATA
        p = _default_path()
        try:
            with open(p, encoding='utf-8') as f:
                raw = json.load(f)
        except FileNotFoundError:
            raw = {'map': {}, 'source': {}}
        _PATH = p
        _DATA = {'map': raw.get('map') or {}, 'source': raw.get('source') or {},
                 'generated': raw.get('generated', ''),
                 'dirs': {}, 'tail': {}, 'base': {}, 'lower': {}}
        for stem, rec in _DATA['map'].items():
            mv = rec.get('pkg') or ''
            dpath = mv.rsplit('/', 1)[0] if '/' in mv else ''
            _DATA['dirs'].setdefault(dpath, []).append(stem)
            key = '/'.join(dpath.split('/')[-2:])
            _DATA['tail'].setdefault(key, []).append(stem)
            _DATA['base'].setdefault(dpath.rsplit('/', 1)[-1], []).append(stem)
            _DATA['lower'].setdefault(stem.lower(), stem)
        return _DATA


def stats() -> dict:
    d = load()
    return {'file': _PATH, 'generated': d.get('generated'), 'count': len(d['map']),
            'source': d.get('source')}


# ------------------------------------------------------------------ 工具
def _stem(asset_path: str) -> str:
    """任意路径/资产名 → 最后一段（去掉扩展名）。"""
    if not asset_path:
        return ''
    p = asset_path.replace('\\', '/').rstrip('/')
    name = p.rsplit('/', 1)[-1]
    low = name.lower()
    for e in _MODEL_EXT:
        if low.endswith(e):
            return name[:-len(e)]
    return name.split('.')[0] if '.' in name else name


def _strip_variants(stem: str):
    """产出 (候选名, 是否降级过)。"""
    yield stem, False
    cur = stem
    for _ in range(5):
        cand = None
        for rx in _SUF_RES:
            m = rx.search(cur)
            if m and m.start() >= 3:
                cand = cur[:m.start()]
                break
        if cand is None:
            m = _NUM_TAIL.search(cur)
            # 只剥「数字尾巴」且剥完不能落在 _ / - 上（否则是 -Std_001 这种真实名的一截）
            if m and m.start() >= 6 and cur[m.start() - 1] not in '-_':
                cand = cur[:m.start()]
        if not cand or cand == cur:
            break
        cur = cand
        yield cur, True


def _norm(s: str) -> str:
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', (s or '').lower())


# ------------------------------------------------------------------ 查询
def lookup(asset_path: str) -> dict:
    """返回命中的完整记录（含 conf/src/fuzzy），未命中返回 {}。"""
    d = load()
    m = d['map']
    if not m:
        return {}
    stem = _stem(asset_path)
    if not stem:
        return {}

    # 1/2/3 精确 → 剥后缀 → 补后缀（都按「降级程度」排序）
    bases = [c for c, _ in _strip_variants(stem)]
    cands = [(c, c != stem) for c in bases]
    cands += [(c + s, True) for c in bases for s in _ADD_SUFFIX]
    seen = set()
    for cand, degraded in cands:
        if cand in seen:
            continue
        seen.add(cand)
        rec = m.get(cand)
        if rec:
            return dict(rec, matched=cand, fuzzy=False,
                        conf=rec.get('conf', 0.9) if not degraded else min(rec.get('conf', 0.9), 0.85))
        alt = d['lower'].get(cand.lower())
        if alt:
            return dict(m[alt], matched=alt, fuzzy=False,
                        conf=min(m[alt].get('conf', 0.9), 0.8))

    # 4 同目录模糊：优先「该目录下中文名唯一」的兄弟资产，否则取最长公共前缀
    #    贴图/材质/蓝图等不是模型资产，模糊必错，直接不参与
    up = stem.upper()
    if up.startswith(('T_', 'MI_', 'MPC_', 'MF_', 'MFG_', 'ABP_', 'BP_', 'SKEL_', 'PHYS_')) \
            or up.endswith(('_PHYSICSASSET', '_SKELETON')):
        return {}
    p = asset_path.replace('\\', '/')
    dpath = p.rsplit('/', 1)[0] if '/' in p else ''
    probes = [dpath, _vpath(dpath), dpath.rsplit('/', 1)[0] if '/' in dpath else '']
    for dirpath in list(probes):
        if dirpath:
            segs = dirpath.rstrip('/').split('/')
            for k in ('/'.join(segs[-2:]), '/'.join(segs[-3:])):
                if k not in probes:
                    probes.append(k)
    for dirpath in probes:
        if not dirpath:
            continue
        sibs = (d['dirs'].get(dirpath) or d['tail'].get(dirpath)
                or d['dirs'].get(dirpath + '/') or None)
        if sibs is None:
            cand = d['base'].get(dirpath.rstrip('/').rsplit('/', 1)[-1])
            if cand and len({m[s].get('cn') for s in cand}) == 1:
                a = _norm(stem)
                b = _norm(cand[0])
                n = 0
                for x, y in zip(a, b):
                    if x != y:
                        break
                    n += 1
                if n >= 8:
                    sibs = cand
        if not sibs:
            continue
        cns = {m[s].get('cn') for s in sibs if m[s].get('cn')}
        if len(cns) == 1:
            best = sibs[0]
            rec = dict(m[best])
            rec.update(matched=best, fuzzy=True, conf=0.5)
            return rec
        best, blen = None, 0
        for s in sibs:
            n = 0
            for a, b in zip(s.lower(), stem.lower()):
                if a != b:
                    break
                n += 1
            if n > blen:
                best, blen = s, n
        if best and blen >= max(6, len(stem) * 0.7):
            rec = dict(m[best])
            rec.update(matched=best, fuzzy=True, conf=0.4)
            return rec
    return {}


def resolve_cn(asset_path: str) -> str:
    """资产路径 → 显示名。

    先查名字表（如果使用者自己放了 `names.json`）；没有就用 `core.humanize`
    从代号拼一个（仓库不附带游戏文本，所以默认走这条）。
    """
    hit = (lookup(asset_path) or {}).get('cn', '') or ''
    if hit:
        return hit
    try:
        from . import humanize
        return humanize.pretty(asset_path)
    except Exception:                                          # noqa: BLE001
        return ''


def resolve(asset_path: str) -> dict:
    """资产路径 → {'cn','en','cat','conf','src','matched','fuzzy'}；拿不到返回空 dict。"""
    rec = lookup(asset_path)
    if not rec:
        return {}
    return {'cn': rec.get('cn', ''), 'en': rec.get('en', ''),
            'cat': rec.get('cat') or category(rec.get('cn', '')),
            'conf': rec.get('conf', 0.5), 'src': rec.get('src', ''),
            'matched': rec.get('matched', ''), 'fuzzy': rec.get('fuzzy', False),
            'pkg': rec.get('pkg', '')}


def _vpath(game_dir: str) -> str:
    """'/Game/Models/X' -> '../../../DeltaForce/Content/Models/X'"""
    if game_dir.startswith('/Game/'):
        return '../../../DeltaForce/Content/' + game_dir[len('/Game/'):]
    return game_dir


# ------------------------------------------------------------------ 分类
CAT_RULES = [
    # 顺序 = 优先级。放前面的先命中，所以「零件/箱子/卡」这些要在「武器」之前
    # —— 该游戏里 Props 目录下的箱子叫 `SM_Crate_*`，名字里常带武器家族词。
    ('钥匙卡', ('钥匙卡', '门卡', '房卡', '通行卡', '门禁')),
    ('藏品', ('藏品', '收藏', '摆件', '雕像', '手办', '盲盒', '纪念币', '古董', '金条')),
    ('容器', ('容器', '箱子', '货箱', '收纳', '保险柜', '柜子', '铁笼', '弹药箱', '手提箱',
              '箱子盖', '背包箱')),
    ('弹匣', ('弹匣', '弹鼓', '弹链', '弹夹', '快拔')),
    ('瞄具', ('瞄具', '瞄准镜', '红点', '全息', '倍镜', '准星配件', '侧瞄', '热成像', '夜视')),
    ('配件', ('枪管', '枪托', '握把', '护木', '消音', '抑制器', '导轨', '枪口', '准星', '扳机',
              '枪机', '复进', '导气', '配件', '套件', '改装', '上机匣', '下机匣', '缓冲',
              '枪族', '握片', '射击模式', '后握', '机匣', '两脚架', '前握把', '消焰器',
              '补偿器', '护盖', '战术装置', '后照门')),
    ('弹药', ('子弹', '弹药', '弹头', '穿甲弹', '曳光弹', '弹丸')),
    ('武器', ('步枪', '冲锋枪', '霰弹枪', '狙击枪', '精确射手', '轻机枪', '机枪', '手枪', '左轮',
              '近战', '刀', '斧', '锤', '匕首', '弓', '弩', '投掷', '手雷', '烟雾弹', '震撼弹',
              '燃烧弹', '地雷', 'C4', '榴弹', '火箭筒', '发射器')),
    ('角色', ('干员', '特勤', '蜂医', '突击兵', '工程兵', '侦察兵', '支援兵', '骇客')),
    ('AI', ('AI', '士兵', '哨兵', '巡逻', '敌军', '首领', 'BOSS', '机枪兵', '盾兵', '狙击手')),
    ('载具', ('载具', '坦克', '装甲车', '直升机', '越野车', '摩托车', '快艇', '防空车', '步战车',
              '轮式', '履带')),
    ('装备', ('头盔', '护甲', '胸挂', '背包', '防弹', '护目镜', '面罩', '腰带', '战术')),
    ('道具', ('医疗', '急救', '止血', '止痛', '食物', '饮料', '水', '钥匙', '材料',
              '电子', '零件', '电池', '燃料', '补给', '情报', '文件', '代币', '货币')),
    ('皮肤', ('皮肤', '涂装', '外观', '挂饰', '喷漆', '贴纸', '名片', '头像', '主题', '套装')),
]

# 容器/藏品这些「Prop 子类」既看中文名也看路径（名字常常是「箱子」以外的词）
_KEYCARD_STEM = ("keycard", "key_card", "cardkey", "doorcard", "keycard")
_COLLECT_DIRS = ("/props/collect/", "/propscollection/", "/collect/", "/collections/")
# 只留真正「装东西的」词。以前把 case/drum/barrel 也算进来，结果弹壳(case)、
# 弹鼓(drum)、枪管(barrel) 全被分到容器里去了。
_CONTAINER_WORDS = ("crate", "container", "locker", "cabinet", "safebox", "chest",
                    "storagebox", "storagelocker", "weaponcase", "toolbox",
                    "briefcase", "suitcase", "footlocker", "ammobox", "lootbox",
                    "medicalbox", "supplybox", "trunk", "dumpster", "vending")
_SKILL_DIRS = ("/militaryprops/",)


def category(cn: str) -> str:
    """按中文名判类别：武器/配件/弹匣/弹药/瞄具/干员/AI/载具/装备/道具/皮肤/其他。"""
    s = cn or ''
    if not s:
        return '其他'
    for cat, keys in CAT_RULES:
        for k in keys:
            if k in s:
                return cat
    return '其他'


_AMMO_PATH_WORDS = ("/ammo", "ammobox", "/bullet", "cartridge", "_ammo/", "/ammunition")
_AMMO_NAME_RE = re.compile(
    r"[0-9]+(?:\.[0-9]+)?\s*(?:mm|毫米|gauge|bmg|blk|acp|magnum|lap|sub|tracer|ae|ap)"
    r"|(?:鹿弹|霾弹|穿甲弹|曳光弹|空尖弹|弹头|弹丸|子弹|弹药)",
    re.IGNORECASE)


def _looks_ammo(path: str, name: str) -> bool:
    """子弹既没有中文物品名也没有素材名（名字就是 `.45 ACP RP` 这种口径串），
    只能靠口径写法和目录判断。放在容器判定之前，否则 `Ammobox` 目录会把子弹判成箱子。
    """
    if any(w in path for w in _AMMO_PATH_WORDS):
        return bool(_AMMO_NAME_RE.search(name or "") or "gauge" in path or "caliber" in path)
    return bool(_AMMO_NAME_RE.search(name or ""))


def category_of(asset_path: str, cn: str = "") -> str:
    """资产路径 + 中文名 → 分类。

    优先级（用户定的口径）：
      角色技能（MilitaryProps）> 钥匙卡 > 名字能确定的硬分类（弹药/武器/配件/装备/载具/角色）
      > 藏品 > 容器 > 路径兜底 > 其他。

    名字先判很重要：`..._Ammobox_...` 这种路径里带 ammo-box 的子弹，名字是
    「.45 ACP RP」，应该进弹药而不是容器；同理「弹链」不能被 drum 抓走。
    """
    path = "/" + (asset_path or "").replace("\\", "/").lower()
    name = cn or ""
    if not name:
        try:
            name = (lookup(asset_path) or {}).get("cn", "") or ""
        except Exception:                                      # noqa: BLE001
            name = ""
    if not name:
        # 仓库不附带游戏文本：没有名字表时用代号拼的显示名兜底
        try:
            from . import humanize
            name = humanize.pretty(asset_path)
        except Exception:                                      # noqa: BLE001
            name = ""

    # 1) 角色技能：该游戏把这些技能道具放在 Weapons/MilitaryProps 下
    if any(d in path for d in _SKILL_DIRS):
        return "角色技能"

    # 1.5) 干员 / 干员皮肤：先按路径定，别让名字里的「头盔/护甲/战术」把整只人判成装备。
    #      该游戏的皮肤模型放在 Commerical/CharAppear/<皮肤>/Character/ 下，
    #      活动皮肤特效在 Commerical/Event/OperatorSkin/，两者都算「角色」。
    if "/charappear/" in path or "/operatorskin/" in path:
        return "角色"
    if "/weaponappear/" in path:
        # 武器皮肤：名字大多是英文皮肤名，没有中文名，走「武器」更符合用户找东西的习惯
        return "武器"
    if "/models/characters" in path and "/characters/ai/" not in path:
        return "角色"

    # 2) 钥匙卡：文件名里几乎一定带 keycard
    if any(k in path for k in _KEYCARD_STEM):
        return "钥匙卡"
    if any(k in name for k in ("钥匙卡", "门卡", "房卡", "通行卡")):
        return "钥匙卡"

    # 3) 名字能确定的硬分类（弹药优先于容器，避免 ammobox 里的子弹被当箱子）
    fine = category(name)
    if fine in ("弹药", "弹匣", "瞄具", "配件", "武器", "装备", "载具", "角色", "AI"):
        return fine

    # 4) 藏品：Props/Collect 目录，或者名字就是摆件/雕像这类
    if any(d in path for d in _COLLECT_DIRS):
        return "藏品"
    if any(k in name for k in ("藏品", "摆件", "雕像", "手办", "盲盒", "纪念币", "古董")):
        return "藏品"

    # 4.5) 子弹（名字是口径串）：要在容器之前判，不然 Ammobox 目录全成箱子
    if _looks_ammo(path, name):
        return "弹药"

    # 5) 容器：箱子/柜子/保险箱。装备目录里的「背包」不算容器
    if any(k in path for k in _CONTAINER_WORDS) or any(
            k in name for k in ("容器", "箱子", "货箱", "收纳", "保险柜", "柜子", "弹药箱",
                                "手提箱", "储物箱", "收纳箱", "医疗箱", "补给箱", "保险箱")):
        if not any(k in path for k in ("/backpacks", "/equipments", "backpack")):
            return "容器"

    if fine in ("道具", "皮肤"):
        return fine
    if "/weapons/parts/" in path or "/parts/" in path:
        return "配件"
    if "/models/weapons/" in path:
        return "武器"
    if "/models/equipments" in path:
        return "装备"
    if "/models/vehicles/" in path or "/vehicles/" in path:
        return "载具"
    if "/models/characters/" in path:
        return "AI" if "/characters/ai" in path else "角色"
    if "/models/props/" in path:
        return "道具"
    rec = {}
    try:
        rec = lookup(asset_path) or {}
    except Exception:                                          # noqa: BLE001
        rec = {}
    return rec.get("cat") or "其他"


# ------------------------------------------------------------------ 搜索
def search_cn(keyword: str, limit: int = 50, cat: str = '', include_en: bool = True):
    """给 UI 用：按中文/英文/资产名子串搜，返回 [{asset, cn, en, cat, conf}]（短的优先）。"""
    d = load()
    kw = (keyword or '').strip().lower()
    out = []
    if not kw:
        return out
    for stem, rec in d['map'].items():
        cn = rec.get('cn') or ''
        if cat and (rec.get('cat') or category(cn)) != cat:
            continue
        en = rec.get('en') or ''
        if kw in cn.lower() or kw in stem.lower() or (include_en and kw in en.lower()):
            out.append({'asset': stem, 'cn': cn, 'en': en,
                        'cat': rec.get('cat') or category(cn),
                        'conf': rec.get('conf', 0.5), 'src': rec.get('src', ''),
                        'pkg': rec.get('pkg', '')})
    out.sort(key=lambda r: (len(r['cn']), r['asset']))
    return out[:limit]


def all_names() -> dict:
    """{资产名: 记录}（只读）。"""
    return load()['map']

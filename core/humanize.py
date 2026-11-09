"""humanize —— 把资产代号拼成一个「像人起的」显示名。

**不读任何游戏文本资源**：没有 `work/names.json`、没有 locres、没有物品图标库也照样出名字。
名字全部由本仓库自己的词典把代号拆开重排出来，例如：

    >>> humanize.pretty('.../Parts/Rec/Rec_AR_M4A1-Std_001/Rec_AR_M4A1-Std_001_3P.uasset')
    'M4A1 机匣'
    >>> humanize.pretty('.../Parts/Bar/Bar_AR-227_SG553-Std_015/Bar_AR-227_SG553-Std_015_1P.uasset')
    'SG553 枪管'
    >>> humanize.pretty('.../Commerical/PropAppear/Ma2/Prop_Collect_5C5P2_up_1479/..._1P.uasset')
    '5C5P2 藏品'

规则（从代号里取信息，取不到就少写，不硬编）：
  1. 去掉扩展名与变体后缀：``_1P/_3P/_UI/_SK/_Lay/_HD/_LODn`` 等；
  2. 按 ``_`` / ``-`` 拆词；
  3. 首个词多半是族前缀（``Rec``/``Bar``/``Mag``…），映射成中文类别词，放到末尾；
  4. 带数字的词（``M4A1``/``SG553``/``M250``）当型号原样保留，放最前；
  5. 已知英文词按词典译成中文（``short``→短管、``silencer``→消音器…）；
  6. 纯数字、``std``/``specail`` 这类内部代号直接丢掉，不往界面上摆。

所以界面上看到的名字是「我们自己起的」，不是游戏里的物品名。
"""
from __future__ import annotations

import os
import re

# 族前缀 → 中文类别词（第一个词是这些时，就把它当类别摆在末尾）
FAMILY_WORDS = {
    'rec': '机匣',
    'bar': '枪管',
    'han': '护木',
    'muz': '枪口',
    'sto': '枪托',
    'pisg': '握把',
    'frog': '前握把',
    'bip': '两脚架',
    'sco': '瞄具',
    'fros': '前准星',
    'reas': '后照门',
    'mag': '弹匣',
    'amm': '弹药',
    'dev': '战术装置',
    'other': '附件',
    'rail': '导轨',
    'prop': '道具',
    'props': '道具',
    'chr': '角色',
    'char': '角色',
    'tank': '坦克',
    'veh': '载具',
    'helmet': '头盔',
    'armor': '护甲',
}

# 已知英文词 → 中文（词义本身是通用词，不涉及任何游戏文本）
WORDS = {
    'short': '短管',
    'long': '长管',
    'heavy': '重型',
    'light': '轻型',
    'std': '',
    'standard': '',
    'specail': '',
    'special': '',
    'small': '小',
    'large': '大',
    'ext': '延伸',
    'extended': '加长',
    'suppressor': '抑制器',
    'silencer': '消音器',
    'compensator': '补偿器',
    'flash': '消焰器',
    'muzzle': '枪口',
    'barrel': '枪管',
    'handguard': '护木',
    'receiver': '机匣',
    'stock': '枪托',
    'grip': '握把',
    'foregrip': '前握把',
    'bipod': '两脚架',
    'scope': '瞄准镜',
    'reddot': '红点',
    'laser': '激光',
    'flashlight': '手电',
    'rail': '导轨',
    'cover': '护盖',
    'drum': '弹鼓',
    'mag': '弹匣',
    'ammo': '弹药',
    'bullet': '子弹',
    'helmet': '头盔',
    'armor': '护甲',
    'vest': '背心',
    'backpack': '背包',
    'med': '医疗',
    'key': '钥匙',
    'card': '卡',
    'crate': '箱子',
    'collect': '藏品',
    'container': '容器',
    'vehicle': '载具',
    'tank': '坦克',
    'heli': '直升机',
    'npc': 'NPC',
    'male': '男',
    'female': '女',
}

# 这些词即使不认识也丢掉（内部代号/皮肤代号，摆出来只会更难读）
DROP = {
    'std', 'specail', 'special', 'lod0', 'lod1', 'lod2', 'lod', 'sk', 'mesh',
    'the', 'and', 'of', 'for', 'v1', 'v2', 'v3', 'h1', 'h2', 'h3', 'up', 'upg',
    'bp', 'wbp', 'mi', 'mpc', 'mf', 'ns', 'abp', 'da', 'dt', 'st', 'ps', 'e',
    'ac', 'hu', 'wi', 'p', 'fx', 'vfx', 'icon', 'ui', 'hd', 'lay', 'layers',
}

_VARIANT_RE = re.compile(
    r'[_-](?:1p|3p|ui|sk|vm|hd|lay|low|mid|high|lod\d*|skeleton|skeletalmesh|'
    r'physicsasset|mesh|mat|inst)$', re.I)
_SPLIT_RE = re.compile(r'[_\-\s]+')
_MODEL_RE = re.compile(r'^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9]{3,12}$')
# 粘贴成驼峰的「型号+英文词」：M250Silencer / M4A1Short / ARCompensator
_SUFFIX_KEYS = sorted((k for k, v in WORDS.items() if v), key=len, reverse=True)


def _peel_suffix(tok: str):
    """`M250Silencer` → ('M250', '消音器')；拆不开返回 (tok, '')。"""
    low = tok.lower()
    for key in _SUFFIX_KEYS:
        if low.endswith(key) and len(tok) > len(key) + 1:
            head = tok[:-len(key)]
            if _looks_model(head) or head.isalpha():
                return head, WORDS[key]
    return tok, ''


def _stem(path: str) -> str:
    name = os.path.basename(str(path or '').replace('\\', '/'))
    if '.' in name:
        name = name.rsplit('.', 1)[0]
    for _ in range(4):
        if not name:
            break
        new = _VARIANT_RE.sub('', name)
        if new == name:
            break
        name = new
    return name


def _looks_model(tok: str) -> bool:
    """M4A1 / SG553 / M250 / 6D2KC：带数字的短词当型号。"""
    return bool(_MODEL_RE.match(tok))


def parse(path: str):
    """资产路径 → (型号词表, 描述词表, 类别词)。"""
    stem = _stem(path)
    tokens = [t for t in _SPLIT_RE.split(stem) if t]
    models, words, family = [], [], ''
    for idx, tok in enumerate(tokens):
        low = tok.lower()
        if idx == 0 and low in FAMILY_WORDS:
            family = FAMILY_WORDS[low]
            continue
        if low in FAMILY_WORDS and low in ('collect', 'prop', 'tank'):
            family = family or FAMILY_WORDS[low]
            continue
        head, word = _peel_suffix(tok)
        if word:
            models.append(head)
            words.append(word)
            continue
        if low in DROP:
            continue
        if low in WORDS:
            w = WORDS[low]
            if w:
                words.append(w)
            continue
        if tok.isdigit():
            continue
        if _looks_model(tok):
            models.append(tok.upper() if not any(c.islower() for c in tok) else tok)
            continue
        if len(low) >= 3 and not low.isdigit():
            # 认不出的英文词：首字母大写后保留，读起来像「Aimpoint Pro」这种
            words.append(tok[:1].upper() + tok[1:])
    return models, words, family


def pretty(path: str) -> str:
    """资产路径 → 显示名（拿不到就返回代号本身，绝不返回空串给界面炸）。"""
    models, words, family = parse(path)
    if words and family in ('道具', '附件', '角色', '载具', '坦克'):
        family = ''            # 「5C5P2 藏品」比「5C5P2 藏品 道具」像人话
    parts = list(dict.fromkeys(models + words))
    if family and family not in parts:
        parts.append(family)   # 部件词（机匣/枪管/弹匣…）放末尾：「M4A1 机匣」
    if not parts:
        return _stem(path)
    return ' '.join(parts)


def category_word(path: str) -> str:
    """给占位图标/分类兜底用的粗粒度类别词。"""
    *_, family = parse(path)
    return family or ''


def describe(path: str) -> dict:
    models, words, family = parse(path)
    return {'models': models, 'words': words, 'family': family, 'name': pretty(path)}

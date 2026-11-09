"""模型库浏览器（v2）：名字优先的卡片视图 + 分类筛选 + 全字段搜索。

和 v1 的区别：

* **默认就是卡片视图**：每个资产一张卡片，上面是游戏内 UI 小图标，下面是
  「中文名 / 分类」，鼠标悬停显示资产名与路径。v1 默认给的是目录树，9443 个资产
  全靠展开目录找，很难读。
* **搜索能搜中文名**：v1 只拿 query 去比对相对路径（`Weapons/AR/M4.uasset`），
  所以搜「M4A1 突击步枪」什么也搜不到。v2 给每个资产建一条可搜索文本
  （中文名 + 英文名 + 资产名 + 分类 + 路径），并让「名字命中」排在「路径命中」前面。
* **分类筛选**：武器 / 配件 / 装备 / 道具 / 载具 / 角色 / AI / 其他（分类来自
  `core.cnnames` 的 names.json，缺的话按目录兜底推断）。
* 目录树还在（切到「目录」），只是不再是默认视图。

数据来源：`core.loader.list_models("Models/")` 拿 6 万条索引，`core.cnnames`
查游戏内名字，`core.icons` 找 UI 小图标。
"""
from __future__ import annotations

import bisect
import os
from typing import Dict, List, Optional, Tuple

from app.fluent_api import (QFrame, QLabel, QListWidget, QListWidgetItem,
                            QPushButton, QScrollArea, QStackedWidget, QThread,
                            QTreeWidget, QTreeWidgetItem, QVBoxLayout, QHBoxLayout,
                            QGridLayout, SearchLineEdit, PushButton, BodyLabel,
                            CaptionLabel, StrongBodyLabel, Signal, Qt, QWidget,
                            qicon, QSize)

try:                                                        # 中文名查询层
    from core.cnnames import resolve_cn as _resolve_cn
except Exception:                                           # noqa: BLE001
    _resolve_cn = None

try:                                                        # 分类/别名（可选）
    from core import cnnames as _cnnames
except Exception:                                           # noqa: BLE001
    _cnnames = None

try:                                                        # UIIcon 小图标
    from core import icons as _icons
except Exception:                                           # noqa: BLE001
    _icons = None


try:
    from app.ui_scale import px as _px
except Exception:                                            # noqa: BLE001
    def _px(value):
        return int(value)


CATEGORY_ORDER = {"武器": 0, "配件": 1, "装备": 2, "弹药": 3, "钥匙卡": 4, "藏品": 5,
                  "容器": 6, "角色技能": 7, "角色": 8, "载具": 9, "道具": 10,
                  "武器皮肤": 11, "角色皮肤": 12, "道具皮肤": 13, "活动": 14,
                  "AI": 15, "其他": 16}

CARD_CSS = ("QFrame#modelCard{background:rgba(255,255,255,10);"
            "border:1px solid rgba(255,255,255,20);border-radius:10px;}"
            "QFrame#modelCard:hover{background:rgba(0,120,212,45);"
            "border:1px solid rgba(0,150,255,150);}")

CHIP_ON = ("QPushButton#categoryChip{background:rgba(0,120,212,200);color:#ffffff;"
           "border:1px solid rgba(0,120,212,255);border-radius:14px;padding:0 10px;}")
CHIP_OFF = ("QPushButton#categoryChip{background:rgba(255,255,255,26);color:#e8e8e8;"
            "border:1px solid rgba(255,255,255,28);border-radius:14px;padding:0 10px;}"
            "QPushButton#categoryChip:hover{background:rgba(255,255,255,34);color:#ffffff;}")

# 没有 UI 小图标时给卡片画一个占位图：分类色块 + 名字首字，
# 比统一一个灰色小圆环好认（该游戏的特效/角色/载具基本都没有小图标）。
CATEGORY_COLORS = {
    "武器": "#c0563a", "配件": "#b98b3c", "装备": "#3f7a8c", "弹药": "#a8763c",
    "钥匙卡": "#c9a227", "藏品": "#b0703c", "容器": "#6f7f5a", "角色技能": "#4a7f9c",
    "道具": "#5a8a5a", "载具": "#6a6a9c", "角色": "#8c5a8c", "AI": "#a04a4a",
    "武器皮肤": "#c9622e", "角色皮肤": "#9c6a9c", "道具皮肤": "#6a9a6a", "活动": "#b08a3c",
    "其他": "#666666",
}


def _first_cjk(text: str) -> str:
    """取第一个汉字（占位图上写字用；`2级手枪消焰器` → `级`）。"""
    for ch in text or "":
        if "\u4e00" <= ch <= "\u9fff":
            return ch
    return ""


def _icon_from_pack(vpath: str):
    """随包的图标包：92x92 PNG，按资产名/物品 ID 命中。"""
    try:
        from app.fluent_api import QIcon, QPixmap
        from core import iconpack
        blob = iconpack.icon_bytes(vpath)
        if not blob:
            return None
        pix = QPixmap()
        if not pix.loadFromData(blob, "PNG"):
            return None
        return QIcon(pix)
    except Exception:                                          # noqa: BLE001
        return None


class _IconCache:
    """按资产路径缓存 QIcon（图标来自游戏目录的 UIIcon 资源，没有就画占位块）。"""

    def __init__(self) -> None:
        self._cache: Dict[str, object] = {}
        self._fallback: Dict[Tuple[str, str], object] = {}

    def __contains__(self, vpath: str) -> bool:
        return bool(vpath) and self._cache.get(vpath) is not None

    def get(self, vpath: str, title: str = "", cat: str = "其他", variant: str = ""):
        if not vpath:
            return self.placeholder(title, cat, variant)
        cached = self._cache.get(vpath)
        if cached is not None:
            return cached or None
        from app.fluent_api import QIcon

        # 用户自己配过的图标优先（core/usertable.py 里的可分享表），其次是游戏 UIIcon
        path = None
        try:
            from core import usertable
            path = usertable.override_for(vpath)
        except Exception:                                      # noqa: BLE001
            path = None
        if not path:
            path = _icons.icon_for(vpath) if _icons else None
        icon = QIcon(path) if path else None
        if icon is None or icon.isNull():
            # 游戏目录里没有图标目录时，用随包带的图标包（core/iconpack.py）
            icon = _icon_from_pack(vpath)
        self._cache[vpath] = icon
        return icon or self.placeholder(title, cat, variant)

    def invalidate(self, vpath: str) -> None:
        self._cache.pop(vpath, None)

    def placeholder(self, title: str = "", cat: str = "其他", variant: str = ""):
        """彩色圆角块 + 首字（同一分类同一首字复用同一张图）。"""
        key = (cat, variant or (title or "")[:1])
        cached = self._fallback.get(key)
        if cached is not None:
            return cached
        from app.fluent_api import QColor, QFont, QIcon, QPainter, QPixmap, QPen, QBrush, Qt

        size = 84
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            color = QColor(CATEGORY_COLORS.get(cat, "#666666"))
            bg = QColor(color)
            bg.setAlpha(70)
            painter.setBrush(QBrush(bg))
            painter.setPen(QPen(color.lighter(120), 2))
            painter.drawRoundedRect(4, 4, size - 8, size - 8, 16, 16)
            char = variant or _first_cjk(title) or cat[:1] or "?"
            font = QFont()
            font.setPixelSize(34 if len(char) <= 2 else 22)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QPen(color.lighter(160)))
            painter.drawText(pix.rect(), Qt.AlignCenter, char)
        finally:
            painter.end()
        icon = QIcon(pix)
        self._fallback[key] = icon
        return icon


MAX_RESULTS = 400

# 卡片视图里一次最多铺多少张（再多的用搜索/分类收窄，避免卡 UI）
PAGE_SIZE = 240

CATEGORIES: Tuple[Tuple[str, str], ...] = (
    ("all", "全部"),
    ("武器", "武器"),
    ("配件", "配件"),
    ("装备", "装备"),
    ("弹药", "弹药"),
    ("钥匙卡", "钥匙卡"),
    ("藏品", "藏品"),
    ("容器", "容器"),
    ("角色技能", "角色技能"),
    ("角色", "角色"),
    ("载具", "载具"),
    ("道具", "道具"),
    ("武器皮肤", "武器皮肤"),
    ("角色皮肤", "角色皮肤"),
    ("道具皮肤", "道具皮肤"),
    ("活动", "活动"),
    ("其他", "其他"),
)

# Class suffixes that exist under Models/ but are not renderable meshes:
# skeletons, animation rollers, physics bodies, decals, baked texture folders.
_SKIP_SUFFIXES = (
    "_Skeleton", "_PhysicsAsset", "_Montage", "_BlendSpace", "_AnimBlueprint",
    "_AnimSequence", "_PoseAsset", "_Destructible", "_SK",
)
_SKIP_DIRS = ("/Textures/", "/Texture/", "/Materials/", "/Material/",
              "/GenTexDir/", "/GenTexDirHD/", "/GenTexDirLD/",
              # 动画/蒙太奇/曲线目录里全是 AnimSequence，不是模型
              "/Anim/", "/Animation/", "/Animations/", "/Montage/",
              "/AnimLayer/", "/Curve/")


def is_model_asset(vpath: str) -> bool:
    """Cheap name based filter, run on the 54k index before the tree is built."""
    low = vpath.replace("\\", "/")
    lower = low.lower()
    if not lower.endswith(".uasset"):
        return False
    if any(part.lower() in lower for part in _SKIP_DIRS):
        return False
    stem = low.rsplit("/", 1)[-1][:-len(".uasset")]
    # 注意：`M_` 前缀在该游戏里是**骨骼网格（盔甲/头盔/身体）**，不能过滤掉；
    # 材质实例是 `MI_`/`MPC_`/`MF_`，贴图是 `T_`，蓝图是 `ABP_`/`BP_`/`WBP_`，
    # 特效/粒子是 `P_`/`FX_`/`NS_`（Commerical/ 的皮肤目录里混着不少）。
    if stem.startswith(("T_", "MI_", "MPC_", "MF_", "NS_", "ABP_", "BP_", "WBP_",
                        "DA_", "DT_", "ST_", "PS_", "E_", "AC_", "HU_", "WI_",
                        "P_", "FX_", "VFX_")):
        return False
    if any(suffix in stem for suffix in _SKIP_SUFFIXES):
        return False
    return True


def cn_name(vpath: str) -> Optional[str]:
    if _resolve_cn is None:
        return None
    try:
        value = _resolve_cn(vpath)
    except Exception:                                       # noqa: BLE001
        return None
    if not value:
        return None
    return str(value)


def model_rel(vpath: str) -> str:
    """`.../Content/Models/Weapons/AR/M4.uasset` -> `Weapons/AR/M4.uasset`."""
    marker = "/Content/"
    idx = vpath.find(marker)
    rel = vpath[idx + len(marker):] if idx >= 0 else vpath
    if rel.startswith("Models/"):
        rel = rel[len("Models/"):]
    return rel


def _stem_of(vpath: str) -> str:
    return os.path.splitext(os.path.basename(str(vpath).replace("\\", "/")))[0]


def commercial_series(vpath: str) -> str:
    """`.../Commerical/WeaponAppear/Ma1/<皮肤>/MP7/Model/...` -> 皮肤名。

    皮肤模型没有中文名（names.json 里一条都没有），卡片标题只能是资产名；
    把皮肤系列名单独拿出来，搜索框里打皮肤名也能找到它的一堆部件。
    """
    low = str(vpath).replace("\\", "/")
    for marker in ("/Commerical/", "/Commercial/"):
        pos = low.lower().find(marker.lower())
        if pos < 0:
            continue
        parts = low[pos + len(marker):].split("/")
        # <类别>/<干员或系列>/<皮肤>/<枪或道具>/...
        for idx, part in enumerate(parts):
            if part.lower() in ("model", "material", "texture", "textures"):
                return parts[idx - 2] if idx >= 2 else ""
        # PropAppear/CharAppear 这种扁平的 <类别>/<干员>/<资产目录>/<资产>，
        # 拿到的「系列名」就是资产自己的目录名，对搜索没帮助。
        fallback = parts[2] if len(parts) > 2 else ""
        if fallback and fallback.strip("/").lower() == low.rsplit("/", 2)[-2].lower():
            return ""
        return fallback
    return ""


def guess_category(vpath: str) -> str:
    """名字库里没分类时的兜底推断（只看目录）。"""
    low = str(vpath).replace("\\", "/").lower()
    if not low.startswith("/"):
        # 传 rel（`Commerical/PropAppear/...`）时补上前导斜杠，下面的 `/x/` 规则才匹配得到
        low = "/" + low
    for cat, keys in (
        # 商城皮肤（`Commerical/`）先认，否则会被下面的 /props/ 之类规则吃掉
        ("武器皮肤", ("/commerical/weaponappear/", "/commercial/weaponappear/")),
        ("角色皮肤", ("/commerical/charappear/", "/commercial/charappear/")),
        ("道具皮肤", ("/commerical/propappear/", "/commerical/businessfiller/",
                      "/commercial/propappear/", "/commercial/businessfiller/")),
        ("活动", ("/commerical/event/", "/commercial/event/")),
        ("配件", ("weapons/parts", "weapon/parts", "/parts/")),
        ("武器", ("/models/weapons/",)),
        ("载具", ("/models/vehicles/", "/vehicle")),
        ("角色", ("/models/characters/hero", "/models/characters_hd/hero")),
        ("AI", ("/models/characters/ai", "/characters/boss", "/characters_hd/ai")),
        ("装备", ("/models/equipments", "/equipments_hd")),
        ("道具", ("/models/props/", "/models/items/", "/props/")),
    ):
        if any(k in low for k in keys):
            return cat
    return "其他"


def _variant_of(stem: str) -> str:
    """`M_Upper_BP_BP_X_087_LAY_HD` -> `LAY HD`；`SM_Mag_X_3P` -> `3P`。

    该游戏同一件东西通常有 1P（第一人称）、3P（第三人称）、UI（图标）、HD（高清）
    几个网格，名字一样，卡片上标出变体才分得清是哪一份。
    `_ui_hd` / `_ui_3p` 这种组合后缀优先算 UI —— UI 网格是摆好姿势的展示模型，
    浏览时比 3P 好看得多。
    """
    low = stem.lower()
    for tag, name in (("_ui_hd", "UI"), ("_ui_3p", "UI"), ("_ui_1p", "UI"),
                      ("_ui_lay", "UI"), ("_ui", "UI")):
        if low.endswith(tag):
            return name
    for tag in ("_lay_hd", "_1p_hd", "_3p_hd", "_lay", "_hd", "_1p", "_3p",
                "_sk", "_preview", "_cutscene"):
        if low.endswith(tag):
            return "LAY HD" if tag == "_lay_hd" else tag.lstrip("_").upper()
    return ""


# 合并同名变体时，卡片挑哪一份来展示：UI（摆好姿势的展示网格）> LAY/HD > 其余按原顺序。
# 1P 是贴脸的第一人称模型（角色上常常只剩两只手），所以不给它更高优先级。
_VARIANT_RANK = {"UI": 0, "LAY HD": 1, "LAY": 2, "HD": 3}


def _variant_rank(stem: str) -> int:
    return _VARIANT_RANK.get(_variant_of(stem), 9)


class _ModelCard(QFrame):
    """一张模型卡片：图标 + 名字（最多两行）+ 分类/变体。"""

    clicked = Signal(str)
    menu_requested = Signal(str, object)      # (vpath, 全局坐标)

    # 卡片尺寸跟着 DPI/字体走：125% / 150% 下别把两行标题挤成省略号
    CARD_W = 140
    CARD_H = 148

    @staticmethod
    def card_size():
        try:
            from app.ui_scale import px as _px
            return (_px(140), _px(148))
        except Exception:                                # noqa: BLE001
            return (_ModelCard.CARD_W, _ModelCard.CARD_H)

    def wheelEvent(self, event) -> None:                       # noqa: N802, D102
        # 卡片是普通 QWidget，滚轮默认被它吃掉、QScrollArea 收不到，列表就滚不动。
        # 这里往上找带 handle_wheel() 的容器（_CardGrid）转过去。
        widget = self.parentWidget()
        while widget is not None and not hasattr(widget, "handle_wheel"):
            widget = widget.parentWidget()
        if widget is not None:
            widget.handle_wheel(event)
        else:
            event.ignore()

    def __init__(self, title: str, sub: str, icon, vpath: str, tip: str, parent=None):
        super().__init__(parent)
        self._vpath = vpath
        self.setObjectName("modelCard")
        cw, ch = self.card_size()
        self._card_w, self._card_h = cw, ch
        self.setFixedSize(cw, ch)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setStyleSheet(CARD_CSS)
        # 右键：给这个资产换图标 / 恢复默认（图标表存在 work/icon_table.json）
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 4)
        lay.setSpacing(2)

        pic = QLabel(self)
        try:
            from app.ui_scale import px as _px
            _icon = _px(58)
        except Exception:                                    # noqa: BLE001
            _icon = 58
        pic.setFixedSize(_icon, _icon)
        pic.setAlignment(Qt.AlignCenter)
        pic.setPixmap(icon.pixmap(_icon, _icon))
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addStretch(1)
        wrap.addWidget(pic)
        wrap.addStretch(1)
        lay.addLayout(wrap)

        name = QLabel(title, self)
        name.setAlignment(Qt.AlignCenter)
        name.setWordWrap(True)
        try:
            from app.ui_scale import px as _px
            name.setFixedHeight(_px(32))
        except Exception:                                    # noqa: BLE001
            name.setFixedHeight(30)
        name.setStyleSheet("color:#e8e8e8;font-size:12px;font-weight:600;")
        lay.addWidget(name)

        meta = QLabel(sub, self)
        meta.setAlignment(Qt.AlignCenter)
        meta.setStyleSheet("color:#8f8f8f;font-size:10px;")
        lay.addWidget(meta)

    def _on_menu(self, pos) -> None:
        self.menu_requested.emit(self._vpath, self.mapToGlobal(pos))

    def mouseReleaseEvent(self, event) -> None:                # noqa: D102, N802
        if event.button() == Qt.LeftButton and self._vpath:
            self.clicked.emit(self._vpath)
        super().mouseReleaseEvent(event)


class _CardGrid(QWidget):
    """按可用宽度自动排若干列的卡片网格。"""

    activated = Signal(str)
    menu_requested = Signal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: List[Dict[str, str]] = []
        self._cols = 0
        self._scroll_area = None
        self._lay = QGridLayout(self)
        self._lay.setContentsMargins(6, 6, 6, 6)
        self._lay.setSpacing(8)
        self._lay.setAlignment(Qt.AlignTop | Qt.AlignLeft)

    def handle_wheel(self, event) -> None:
        """把卡片上的滚轮转成滚动条的位移（QScrollArea 不再接受这条链路）。"""
        area = self._scroll_area
        if area is None:
            event.ignore()
            return
        bar = area.verticalScrollBar()
        delta = event.angleDelta().y()
        if not delta:
            delta = event.pixelDelta().y()
        if delta:
            bar.setValue(int(bar.value() - delta))
            event.accept()
        else:
            event.ignore()

    def wheelEvent(self, event) -> None:                       # noqa: N802
        self.handle_wheel(event)

    def set_items(self, items: List[Dict[str, str]]) -> None:
        self._items = items
        self._cols = 0
        self._rebuild()

    def resizeEvent(self, event) -> None:                      # noqa: D102, N802
        super().resizeEvent(event)
        cw, _ch = _ModelCard.card_size()
        cols = max(1, (self.width() - 12) // (cw + 8))
        if cols != self._cols:
            self._cols = cols
            self._rebuild()

    def _rebuild(self) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        cw, _ch = _ModelCard.card_size()
        cols = self._cols or max(1, (self.width() - 12) // (cw + 8))
        self._cols = cols
        for index, data in enumerate(self._items):
            card = _ModelCard(data["title"], data["sub"], data["icon"],
                              data["vpath"], data["tip"], self)
            card.clicked.connect(self.activated)
            card.menu_requested.connect(self.menu_requested)
            self._lay.addWidget(card, index // cols, index % cols)


class _IndexWorker(QThread):
    done = Signal(list, object, str)
    progress = Signal(str)

    def run(self) -> None:                                  # noqa: D401
        try:
            from core.loader import (list_models, catalog, commercial_like_mesh)
            from core import meshcheck
            paths = list_models("Models/")
            from core.inspection_catalog import inspectable_paths
            # 只留「真的有网格」的条目：目录里记了类名的直接信目录，目录外的
            # （Commerical 皮肤、新版本资产）读 uasset 头确认——动画序列、图集、
            # 蓝图通知同样带 _1P/_3P 尾巴，不验就会混进模型库当空壳。
            known = catalog()
            cand = [p for p in paths
                    if known.get(p) in ("StaticMesh", "SkeletalMesh")
                    or (p not in known and commercial_like_mesh(p))]
            todo = [p for p in cand if p not in known
                    and meshcheck.status(p) is None]
            if todo:
                meshcheck.verify_many(
                    todo, workers=10,
                    progress=lambda i, n: self.progress.emit(f"校验网格 {i}/{n}"),
                    cancel=self.isInterruptionRequested)
            meshes = [p for p in cand
                      if known.get(p) in ("StaticMesh", "SkeletalMesh")
                      or meshcheck.status(p) is True]
            eligible = inspectable_paths([p for p in meshes if p in known],
                progress=lambda i,n: self.progress.emit(f"筛选可检视模型 {i}/{n}"),
                cancel=self.isInterruptionRequested)
            if not self.isInterruptionRequested(): self.done.emit(meshes, eligible, "")
        except Exception as exc:                            # noqa: BLE001
            if not self.isInterruptionRequested(): self.done.emit([], set(), f"{type(exc).__name__}: {exc}")


class ModelBrowser(QWidget):
    modelActivated = Signal(str)
    statusMessage = Signal(str)

    def __init__(self, parent=None, *, auto_build: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("modelBrowser")
        self.setMinimumWidth(_px(300))
        self._rels: List[str] = []
        self._rel_to_path: Dict[str, str] = {}
        self._meta: Dict[str, Dict[str, str]] = {}
        self._worker: Optional[_IndexWorker] = None
        self._ready = False
        self._icons = _IconCache()
        self._view = "cards"                # cards | tree
        self._merge_variants = True          # 卡片视图合并 1P/3P/UI/HD 同名变体
        self._cat = "all"
        self._error = ""
        self._shown = 0
        self._inspectable_paths = set()
        self._closing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(StrongBodyLabel("模型库"))
        head.addStretch(1)
        self.count_label = CaptionLabel("正在索引…")
        head.addWidget(self.count_label)
        root.addLayout(head)

        self.search = SearchLineEdit(self)
        self.search.setPlaceholderText("搜游戏内名字 / 资产名 / 路径（例：M4A1、护木、背包）")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        root.addWidget(self.search)
        from fluentpy import widgets as W
        self.inspect_only = W.CheckBox("只显示可检视模型", self)
        # 默认不勾：勾上只留「能播检视动画」的模型，本机 pak 不全时（比如只装了
        # 几个 chunk）会把弹药/钥匙卡/藏品这些分类整批藏掉，看起来像没有东西。
        self.inspect_only.setChecked(False)
        self.inspect_only.setToolTip(
            "勾选后只列能播放检视动画的模型（骨骼+动画都在本机才满足）。\n"
            "没装全游戏数据时会隐藏大量能渲染的模型，找东西时建议保持不勾。")
        self.inspect_only.toggled.connect(self._toggle_inspect_only)
        root.addWidget(self.inspect_only)

        # 分类筛选：chip 网格。17 个分类后面还要带条数（`角色技能 103`），一行 4 个
        # 会把「钥匙卡 19」裁成「月匙卡 1」，所以一行 3 个。
        self.chips_grid = QGridLayout()
        self.chips_grid.setContentsMargins(0, 0, 0, 0)
        self.chips_grid.setHorizontalSpacing(6)
        self.chips_grid.setVerticalSpacing(6)
        self._chips: Dict[str, QPushButton] = {}
        for idx, (key, label) in enumerate(CATEGORIES):
            chip = QPushButton(label, self)
            chip.setObjectName("categoryChip")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setCheckable(True)
            chip.setAutoExclusive(False)
            chip.setMinimumWidth(52)
            chip.setFixedHeight(26)
            chip.clicked.connect(lambda _=False, k=key: self._set_category(k))
            # 建的时候就把样式铺上，否则没点过的 chip 会用全局默认样式（灰得看不清）
            chip.setStyleSheet(CHIP_ON if key == "all" else CHIP_OFF)
            self.chips_grid.addWidget(chip, idx // 3, idx % 3)
            self._chips[key] = chip
        root.addLayout(self.chips_grid)

        self.stack = QStackedWidget(self)

        # 卡片视图：QListWidget 的 IconMode 在图标大小/文字换行混在一起时会乱排
        # （同一个网格里有的卡片一行、有的两行，字还被裁掉），所以这里自己铺
        # QGridLayout：一张卡片一个控件，宽度不够就自动减列。
        self.card_scroll = QScrollArea(self)
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setFrameShape(self.card_scroll.Shape.NoFrame)
        self.grid = _CardGrid(self.card_scroll)
        self.grid._scroll_area = self.card_scroll             # noqa: SLF001
        self.grid.activated.connect(self._pick_card)
        self.grid.menu_requested.connect(self._card_menu)
        self.card_scroll.setWidget(self.grid)

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["名称", "分类 / 目录"])
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, self.tree.header().ResizeMode.Interactive)
        self.tree.setColumnWidth(1, 130)
        self.tree.setUniformRowHeights(True)
        self.tree.itemExpanded.connect(self._on_expand)
        self.tree.itemClicked.connect(lambda item, col: self._pick_tree_item(item))

        self.stack.addWidget(self.card_scroll)
        self.stack.addWidget(self.tree)
        root.addWidget(self.stack, 1)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        self.more_btn = PushButton("显示更多…", self)
        self.more_btn.clicked.connect(self._show_more)
        self.more_btn.setVisible(False)
        foot.addWidget(self.more_btn)
        foot.addStretch(1)
        self.merge_btn = PushButton("合并变体", self)
        self.merge_btn.setCheckable(True)
        self.merge_btn.setChecked(True)
        self.merge_btn.setToolTip("同一件东西的 1P/3P/UI/HD 网格只显示一张卡片")
        self.merge_btn.clicked.connect(self._toggle_merge)
        foot.addWidget(self.merge_btn)
        self.view_btn = PushButton("详细文件", self)
        self.view_btn.clicked.connect(self._toggle_view)
        foot.addWidget(self.view_btn)
        self.icon_btn = PushButton("图标表", self)
        self.icon_btn.setToolTip("自定义图标存在 work/icon_table.json，可整体导出给别人用")
        self.icon_btn.clicked.connect(self._icon_menu)
        foot.addWidget(self.icon_btn)
        root.addLayout(foot)

        self._highlight()

        if auto_build:
            self.build()

    # -- index ------------------------------------------------------------- #
    def build(self) -> None:
        if self._worker is not None:
            return
        worker = _IndexWorker(self)
        self._worker = worker
        worker.done.connect(lambda paths,eligible,error: self._on_index(paths,error,eligible)
                            if worker is self._worker and not self._closing else None)
        worker.progress.connect(lambda text: self.count_label.setText(text)
                                if worker is self._worker and not self._closing else None)
        worker.start()

    def reload_index(self) -> None:
        """丢掉内存里的索引重新读一遍（设置页「重建索引」成功后调）。"""
        self.shutdown()
        self._closing = False
        from core.inspection_catalog import reset_catalog
        reset_catalog()
        try:
            from core import loader as _ld
            _ld.reset_index()
        except Exception:                                       # noqa: BLE001
            pass
        self._worker = None
        self._rels = []
        self._rel_to_path = {}
        self._meta = {}
        self._ready = False
        self._shown = 0
        self.count_label.setText("正在重新读取索引…")
        self.build()

    def shutdown(self):
        self._closing = True
        if self._worker is not None:
            self._worker.requestInterruption()
            self._worker.wait()

    def _on_index(self, paths: List[str], error: str, eligible=None) -> None:
        self._inspectable_paths = set(eligible or ())
        self._error = error
        if error or not paths:
            detail = error
            try:
                from core import loader as _ld
                if not detail and getattr(_ld, "INDEX_ERROR", ""):
                    detail = _ld.INDEX_ERROR
            except Exception:                                   # noqa: BLE001
                pass
            head = (detail or "没有模型资产").splitlines()[0]
            self.count_label.setText(f"索引不可用：{head}")
            self.count_label.setToolTip(detail or head)
            # 状态栏也给一句，并指路去「设置 → 版本与数据」看完整诊断
            if detail:
                self.statusMessage.emit(f"{head}（完整诊断见 设置 → 版本与数据）")
            self._ready = True
            return
        # 索引好了：状态栏给一句「请享用」——第一次启动时加载条会先退场，
        # 这句话落在主窗口上，用户照样看得到。
        try:
            self.statusMessage.emit("请享用这款软件吧！")
        except Exception:                                       # noqa: BLE001
            pass
        rels: List[str] = []
        mapping: Dict[str, str] = {}
        try:
            from core import loader as _loader
        except Exception:                                       # noqa: BLE001
            _loader = None
        for path in paths:
            if not is_model_asset(path):
                continue
            if _loader is not None:
                try:
                    known = _loader.is_mesh(path)
                except Exception:                               # noqa: BLE001
                    known = None
                if known is False:
                    continue
            rel = model_rel(path)
            if rel in mapping:
                continue
            mapping[rel] = path
            rels.append(rel)
        self._rels = rels
        self._rel_to_path = mapping
        self._build_meta()
        # 排序跟着 meta 走：有名字的排前面、按分类分组，这样卡片第一屏不会
        # 全是 `AI_Crow`、`HS_Security_06_3P` 这种没名字的英文资产名。
        self._rels.sort(key=self._sort_key)
        self._ready = True
        self._populate_root()
        total = len(rels)
        named = sum(1 for m in self._meta.values() if m.get("cn"))
        self.count_label.setText(f"{total} 个模型 · {named} 个有游戏内名字")
        self.statusMessage.emit(f"模型库索引完成：{total} 个模型，{named} 个有名字")
        self._refresh_cards()

    def _build_meta(self) -> None:
        """给每个资产准备显示名 / 分类 / 可搜索文本（一次建好，搜索才有中文名可用）。"""
        meta: Dict[str, Dict[str, str]] = {}
        for rel in self._rels:
            vpath = self._rel_to_path.get(rel, "")
            stem = _stem_of(rel)
            info = {}
            if _cnnames is not None:
                try:
                    info = _cnnames.lookup(vpath) or {}
                except Exception:                               # noqa: BLE001
                    info = {}
            cn = str(info.get("cn") or "").strip()
            en = str(info.get("en") or "").strip()
            cat = ""
            if _cnnames is not None:
                try:
                    # 分类口径集中在 core/cnnames.category_of（钥匙卡/藏品/容器/角色技能…），
                    # 不要用 names.json 里烘焙的旧分类，否则改了规则还要重跑 harvest。
                    cat = _cnnames.category_of(vpath, cn) or ""
                except Exception:                               # noqa: BLE001
                    cat = ""
            cat = cat or guess_category(vpath)
            # core/cnnames 把 CharAppear 归「角色」、WeaponAppear 归「武器」，那是给
            # 名字库用的口径；浏览器的皮肤页签要的是「角色皮肤/武器皮肤」，所以
            # 商城目录优先走 guess_category。
            low_vpath = vpath.replace("\\", "/").lower()
            if "/commerical/" in low_vpath or "/commercial/" in low_vpath:
                skin_cat = guess_category(vpath)
                if skin_cat != "其他":
                    cat = skin_cat
            # 皮肤模型没有中文名，把 `<皮肤系列>` 也塞进搜索词：搜「Gameboy」能
            # 把整套皮肤的枪/弹匣/枪口一次性找出来。
            series = commercial_series(vpath) if "/commerical/" in vpath.lower() or "/commercial/" in vpath.lower() else ""
            # PropAppear/CharAppear 这类没有 `Model/` 子目录的布局，系列名会退回成
            # 资产自己的目录名（和标题重复），没必要再挂到副标题上。
            if series and stem.lower().startswith(series.lower()):
                series = ""
            meta[rel] = {
                "cn": cn, "en": en, "cat": cat, "stem": stem, "vpath": vpath,
                "series": series,
                "title": cn or stem,
                "search": " ".join(x for x in (cn, en, stem, cat, series, rel) if x).lower(),
            }
        self._meta = meta

    def _sort_key(self, rel: str):
        info = self._meta.get(rel) or {}
        cat = info.get("cat") or "其他"
        named = 0 if info.get("cn") else 1
        return (CATEGORY_ORDER.get(cat, 7), named, info.get("title") or _stem_of(rel), rel)

    # -- cards ------------------------------------------------------------- #
    def _visible_rels(self) -> List[str]:
        out = []
        for rel in self._rels:
            if self.inspect_only.isChecked() and self._rel_to_path.get(rel) not in self._inspectable_paths:
                continue
            if self._cat != "all" and self._meta.get(rel, {}).get("cat") != self._cat:
                continue
            out.append(rel)
        return out

    def _refresh_cards(self) -> None:
        rels = self._visible_rels()
        self._shown = 0
        self._append_cards(rels, PAGE_SIZE)
        self.stack.setCurrentWidget(self.card_scroll if self._view == "cards" else self.tree)
        if self._view == "cards":
            self.count_label.setText(f"{len(rels)} 个模型 · 已显示 {self._shown}" if not self.inspect_only.isChecked()
                                     else f"{len(rels)} 个带检视动画的模型 · 已显示 {self._shown}")
        else:
            self._populate_root()
            self.count_label.setText(f"{len(rels)} 个" + ("带检视动画的模型" if self.inspect_only.isChecked() else "模型"))
        self._update_chip_counts()

    def _update_chip_counts(self) -> None:
        """把每个分类页签的真实条数写在 chip 上（`武器 175`），空的那个一眼就看出来。"""
        counts: Dict[str, int] = {}
        inspect_only = self.inspect_only.isChecked()
        for rel in self._rels:
            if inspect_only and self._rel_to_path.get(rel) not in self._inspectable_paths:
                continue
            key = (self._meta.get(rel) or {}).get("cat") or "其他"
            counts[key] = counts.get(key, 0) + 1
        total = sum(counts.values())
        for key, label in CATEGORIES:
            chip = self._chips.get(key)
            if chip is None:
                continue
            num = total if key == "all" else counts.get(key, 0)
            text = f"{label} {num}"
            if chip.text() != text:
                chip.setText(text)
                # 只给最小宽度，别再 setFixedWidth：固定宽度在 3 列网格里会把
                # 「角色技能 103」这类长标签裁掉一半
                chip.setMinimumWidth(max(52, chip.fontMetrics().horizontalAdvance(text) + 18))

    def _card_data(self, rel: str, count: int = 1) -> Dict[str, str]:
        info = self._meta.get(rel) or {}
        title = info.get("title") or _stem_of(rel)
        cat = info.get("cat") or "其他"
        series = info.get("series") or ""
        variant = _variant_of(info.get("stem") or _stem_of(rel))
        if count > 1:
            sub = f"{cat} · {count} 个变体"
        elif series and not variant:
            sub = f"{cat} · {series}"
        else:
            sub = f"{cat} · {variant}" if variant else cat
        tip = [f"名称：{title}"]
        if info.get("en"):
            tip.append(f"英文：{info['en']}")
        if series:
            tip.append(f"皮肤：{series}")
        tip.append(f"资产：{info.get('stem', '')}")
        tip.append(f"分类：{cat}")
        if variant:
            tip.append(f"变体：{variant}")
        if count > 1:
            tip.append(f"同名的还有 {count - 1} 份网格（1P/3P/UI/HD…），卡片只显示第一份")
        tip.append(f"路径：{rel}")
        if info.get("vpath") in self._inspectable_paths:
            sub += " · 可检视"
            tip.append("已找到匹配骨骼的非叠加检视动画")
        return {
            "title": title, "sub": sub, "tip": "\n".join(tip),
            "vpath": info.get("vpath", ""),
            "icon": self._icons.get(info.get("vpath", ""), title, cat, variant),
        }

    def _group_rels(self, rels: List[str]) -> List[Tuple[str, int]]:
        """把「同一件东西的 1P/3P/UI/HD 网格」合成一张卡片。

        该游戏一件装备动辄六七份网格（第一人称、第三人称、UI 图标、高清…），
        名字完全一样。不合并的话，搜「头盔」会看到一屏全是「头盔」，
        所以卡片视图按 (名字, 分类) 聚合，副标题写「N 个变体」。

        挑哪一份展示：**有 UI 网格就用 UI**（摆好姿势的展示模型，比 3P 好看），
        其次是 LAY/HD、1P，最后才是 3P。
        """
        if not self._merge_variants:
            return [(rel, 1) for rel in rels]
        groups: Dict[Tuple[str, str], List[str]] = {}
        order: List[Tuple[str, str]] = []
        for rel in rels:
            info = self._meta.get(rel) or {}
            key = (info.get("title") or _stem_of(rel), info.get("cat") or "其他")
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(rel)
        out: List[Tuple[str, int]] = []
        for key in order:
            members = groups[key]
            best = members[0]
            if len(members) > 1:
                best = min(
                    members,
                    key=lambda rel: (_variant_rank(
                        (self._meta.get(rel) or {}).get("stem") or _stem_of(rel)),
                        members.index(rel)),
                )
            out.append((best, len(members)))
        return out

    def _append_cards(self, rels: List[str], limit: int) -> None:
        groups = self._group_rels(rels)
        start = self._shown
        end = min(len(groups), start + limit) if limit else len(groups)
        items = [self._card_data(rel, count) for rel, count in groups[start:end]]
        if start:
            items = list(getattr(self, "_card_items", [])) + items
        self._card_items = items
        self.grid.set_items(items)
        self._shown = end
        self.more_btn.setVisible(self._shown < len(groups))

    def _toggle_inspect_only(self, *_):
        text = self.search.text().strip()
        if text: self._on_search(text)
        else: self._refresh_cards()

    def reject_inspection(self,vpath):
        self._inspectable_paths.discard(vpath)
        if self._ready and self.inspect_only.isChecked(): self._toggle_inspect_only()

    def _toggle_merge(self) -> None:
        self._merge_variants = bool(self.merge_btn.isChecked())
        text = self.search.text().strip()
        if text:
            self._on_search(text)
        else:
            self._refresh_cards()

    def _show_more(self) -> None:
        self._append_cards(self._visible_rels(), PAGE_SIZE)
        self.count_label.setText(
            f"{len(self._visible_rels())} 个模型 · 已显示 {self._shown}")

    def _card_menu(self, vpath: str, pos) -> None:
        """卡片右键菜单：设置图标 / 导出图标 / 恢复默认 / 复制资产名。

        注意：`QCursor`/`QMenu` 都不在 `app.fluent_api` 的导出里，从这里拿会
        ImportError（右键一按就崩，正是「图标改不了」的真因），一律从 PySide6 拿。
        """
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        act_icon = menu.addAction("设置图标（选本地图片）…")
        act_export = menu.addAction("把当前图标另存为…")
        act_clear = menu.addAction("恢复默认图标")
        menu.addSeparator()
        act_copy = menu.addAction("复制资产名")
        chosen = menu.exec_(QCursor.pos() if pos is None else pos)
        if chosen is act_icon:
            self._pick_icon(vpath)
        elif chosen is act_export:
            self._export_icon(vpath)
        elif chosen is act_clear:
            self._clear_icon(vpath)
        elif chosen is act_copy:
            from app.fluent_api import QApplication
            QApplication.clipboard().setText(self._stem_label(vpath))

    def _export_icon(self, vpath: str) -> None:
        """把这张卡当前用的图标（自定义 / 游戏 / 图标包 / 占位）另存成 PNG。"""
        from app.fluent_api import QFileDialog

        icon = self._icons.get(vpath, self._stem_label(vpath))
        if icon is None:
            self.window().toast("这个资产没有图标", "只有占位色块", ok=False)
            return
        stem = self._stem_label(vpath)
        path, _ = QFileDialog.getSaveFileName(self, "图标另存为", os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "work", f"{stem}.png"),
            "PNG 图片 (*.png)")
        if not path:
            return
        try:
            pix = icon.pixmap(256, 256)
            if not pix.save(path, "PNG"):
                raise RuntimeError("写文件失败")
        except Exception as exc:                                # noqa: BLE001
            self.window().toast("图标另存失败", str(exc), ok=False)
            return
        self.window().status(f"图标已另存：{path}")

    @staticmethod
    def _stem_label(vpath: str) -> str:
        base = str(vpath).replace("\\", "/").rsplit("/", 1)[-1]
        return base.rsplit(".", 1)[0]

    def _pick_icon(self, vpath: str) -> None:
        from app.fluent_api import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self, "选择图标图片", "",
                                              "图片 (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        try:
            from core import usertable
            dest = usertable.set_override(vpath, path)
        except Exception as exc:                                # noqa: BLE001
            self.window().toast("图标保存失败", str(exc), ok=False)
            return
        self._icons.invalidate(vpath)
        self._refresh_cards()
        self.window().status(f"已设置图标：{os.path.basename(dest)}（表：{usertable.table_path()}）")

    def _clear_icon(self, vpath: str) -> None:
        try:
            from core import usertable
            hit = usertable.clear_override(vpath)
        except Exception as exc:                                # noqa: BLE001
            self.window().toast("恢复默认图标失败", str(exc), ok=False)
            return
        self._icons.invalidate(vpath)
        self._refresh_cards()
        self.window().status("已恢复默认图标" if hit else "这个资产本来就没自定义图标")

    def _icon_menu(self) -> None:
        """图标表：打开目录 / 导出分享包 / 统计。"""
        # QDesktopServices / QUrl 不是 fluent_api 导出的名字，直接找 PySide6 拿；
        # 以前写成 from app.fluent_api import QDesktopServices → 点按钮直接 ImportError
        # （会写进「崩溃-时间.txt」，所以这里别再图省事从 fluent_api 拿）。
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QMenu

        try:
            from core import usertable
        except Exception as exc:                                # noqa: BLE001
            self.window().toast("图标表不可用", str(exc), ok=False)
            return
        menu = QMenu(self)
        act_open = menu.addAction(f"打开图标表（{usertable.count()} 项）")
        act_dump = menu.addAction("导出分享包…")
        chosen = menu.exec_(self.icon_btn.mapToGlobal(self.icon_btn.rect().bottomLeft()))
        if chosen is act_open:
            path = usertable.table_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
        elif chosen is act_dump:
            from app.fluent_api import QFileDialog
            dest = QFileDialog.getExistingDirectory(self, "导出到哪个目录（会写 icon_table.json + icons/）")
            if dest:
                try:
                    out = usertable.export_table(os.path.join(dest, "vertexviewer-icons"))
                except Exception as exc:                        # noqa: BLE001
                    self.window().toast("导出失败", str(exc), ok=False)
                    return
                self.window().status(f"图标表已导出：{out}")

    def _pick_card(self, vpath: str) -> None:
        if vpath:
            self.modelActivated.emit(str(vpath))

    # -- category chips ---------------------------------------------------- #
    def _set_category(self, key: str) -> None:
        self._cat = key
        self._highlight()
        text = self.search.text().strip()
        if text:
            self._on_search(text)
        else:
            self._refresh_cards()

    def _highlight(self) -> None:
        """选中的 chip 用强调底色，其余保持透明。"""
        for key, chip in self._chips.items():
            on = key == self._cat
            chip.setChecked(on)
            chip.setStyleSheet(CHIP_ON if on else CHIP_OFF)

    # -- tree (目录视图) --------------------------------------------------- #
    @staticmethod
    def _children(rels: List[str], prefix: str) -> Tuple[Dict[str, int], List[str]]:
        dirs: Dict[str, int] = {}
        files: List[str] = []
        start = bisect.bisect_left(rels, prefix)
        for rel in rels[start:]:
            if not rel.startswith(prefix):
                break
            rest = rel[len(prefix):]
            head, sep, _tail = rest.partition("/")
            if sep:
                dirs[head] = dirs.get(head, 0) + 1
            else:
                files.append(rest)
        return dirs, files

    def _populate_root(self) -> None:
        self.tree.clear()
        self._tree_rels = sorted(self._visible_rels())
        dirs, files = self._children(self._tree_rels, "")
        folder_icon = qicon("folder")
        for name in sorted(dirs):
            item = QTreeWidgetItem([name, f"{dirs[name]} 个"])
            item.setIcon(0, folder_icon)
            item.setData(0, Qt.UserRole, ("dir", ""))
            item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            self.tree.addTopLevelItem(item)
        self._add_files(None, "")

    def _add_files(self, parent: Optional[QTreeWidgetItem], prefix: str) -> None:
        _dirs, files = self._children(self._tree_rels, prefix)
        for rel_name in files:
            full_rel = prefix + rel_name
            info = self._meta.get(full_rel) or {}
            title = info.get("title") or os.path.splitext(rel_name)[0]
            sub = f"{info.get('cat', '其他')} · {os.path.dirname(full_rel)}".strip(" ·")
            item = QTreeWidgetItem([title, sub])
            item.setIcon(0, self._icons.get(info.get("vpath", ""), title, sub.split(" ·")[0]))
            item.setData(0, Qt.UserRole, ("file", info.get("vpath", "")))
            item.setToolTip(0, info.get("vpath", ""))
            item.setToolTip(1, info.get("vpath", ""))
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)

    def _on_expand(self, item: QTreeWidgetItem) -> None:
        kind, _ = item.data(0, Qt.UserRole) or ("", "")
        if kind != "dir" or item.childCount() > 0:
            return
        rel = self._rel_of(item)
        if rel is None:
            return
        prefix = rel + "/"
        dirs, _files = self._children(self._tree_rels, prefix)
        folder_icon = qicon("folder")
        for name in sorted(dirs):
            child = QTreeWidgetItem([name, f"{dirs[name]} 个"])
            child.setIcon(0, folder_icon)
            child.setData(0, Qt.UserRole, ("dir", name))
            child.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            item.addChild(child)
        self._add_files(item, prefix)

    def _rel_of(self, item: QTreeWidgetItem) -> Optional[str]:
        """Rebuild the relative path of a directory node by walking up."""
        kind, _ = item.data(0, Qt.UserRole) or ("", "")
        if kind != "dir":
            return None
        parts: List[str] = []
        node = item
        while node is not None:
            k, _ = node.data(0, Qt.UserRole) or ("", "")
            if k != "dir":
                break
            parts.append(node.text(0))
            node = node.parent()
        parts.reverse()
        return "/".join(parts)

    def _pick_tree_item(self, item: QTreeWidgetItem) -> None:
        kind, vpath = item.data(0, Qt.UserRole) or ("", "")
        if kind == "file" and vpath:
            self.modelActivated.emit(vpath)

    # -- search ------------------------------------------------------------ #
    def _on_search(self, text: str) -> None:
        query = (text or "").strip().lower()
        if not query:
            self._refresh_cards()
            return
        exact, prefix_hit, path_hit = [], [], []
        for rel in self._visible_rels():
            info = self._meta.get(rel) or {}
            if self._cat != "all" and info.get("cat") != self._cat:
                continue
            name = (info.get("cn") or "").lower()
            en = (info.get("en") or "").lower()
            stem = (info.get("stem") or "").lower()
            if name and name == query:
                exact.append(rel)
            elif (name and name.startswith(query)) or (en and en.startswith(query)) \
                    or (stem and stem.startswith(query)):
                prefix_hit.append(rel)
            elif query in (info.get("search") or ""):
                path_hit.append(rel)
        hits = (exact + prefix_hit + path_hit)[:MAX_RESULTS]
        total = len(exact) + len(prefix_hit) + len(path_hit)

        if self._view == "cards":
            self._card_items = []
            self._shown = 0
            self._append_cards(hits, MAX_RESULTS)
            self.count_label.setText(
                f"命中 {total} 个" + ("" if total <= MAX_RESULTS else f"（显示前 {MAX_RESULTS}）"))
            return

        self.tree.clear()
        icon = qicon("view")
        for rel in hits:
            info = self._meta.get(rel) or {}
            item = QTreeWidgetItem([info.get("title") or _stem_of(rel),
                                    info.get("cat", "其他")])
            item.setIcon(0, self._icons.get(info.get("vpath", ""),
                                            info.get("title", ""), info.get("cat", "其他")))
            item.setData(0, Qt.UserRole, ("file", info.get("vpath", "")))
            item.setToolTip(0, info.get("vpath", ""))
            self.tree.addTopLevelItem(item)
        self.count_label.setText(f"命中 {total} 个（最多显示 {MAX_RESULTS}）")

    # -- view toggle ------------------------------------------------------- #
    def _toggle_view(self) -> None:
        self._view = "tree" if self._view == "cards" else "cards"
        self.view_btn.setText("卡片视图" if self._view == "tree" else "详细文件")
        text = self.search.text().strip()
        if text:
            self._on_search(text)
        else:
            self._refresh_cards()
            if self._view == "tree":
                self.stack.setCurrentWidget(self.tree)
                self.count_label.setText(f"{len(self._visible_rels())} 个模型 · 按目录浏览")

    # -- state ------------------------------------------------------------- #
    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def count(self) -> int:
        return len(self._rels)

    def select_first_model(self) -> Optional[str]:
        """Load the first leaf in the tree (used by the screenshot harness)."""
        rels = self._visible_rels()
        if not rels:
            return None
        vpath = self._rel_to_path.get(rels[0])
        if vpath:
            self.modelActivated.emit(vpath)
        return vpath

    def select_model(self, vpath: str) -> Optional[str]:
        """Programmatic pick by virtual path (screenshot harness / drag-drop)."""
        if not vpath:
            return None
        self.modelActivated.emit(vpath)
        return vpath

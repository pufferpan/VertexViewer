"""改枪台：主件 + 配件拼枪。

配件位置**照抄游戏**：该游戏的挂点数据就在包里
（`WeaponPartsMeshSocketNameInfo` / `PartSocketsTable` / `GunDescTable`），
`core.sockets` 把它们解出来，`core.gunsmith.assemble()` 按 socket 链挂接，
和游戏内拼出来的位置一致（用 4053 个官方预设的包围盒验证过）。

界面：

* 左：主件（机匣/整枪）+ 槽位表，每个槽位可以挑一个配件；
* 中：3D 预览，改任意一个参数都会重新合并网格；
* 右：选中配件的位移 / 旋转 / 缩放，以及「自动对齐」「复位」；
* 底：保存方案 / 读取方案 / 导出 OBJ。

配件列表不再现场翻索引：`core.gunsmith.catalog()` 在建索引时就把
「游戏内中文名 / 槽位 / 枪族码」算进 SQLite 的 models 表，弹窗直接查库，
选中之后才真正解包模型。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple
from PySide6.QtCore import QEventLoop
from PySide6.QtCore import QThread,Signal
from copy import deepcopy
import threading

from app.fluent_api import (BodyLabel, CaptionLabel, CardWidget, ComboBox,
                            LineEdit, PrimaryPushButton, PushButton,
                            QApplication, QDialog, QFileDialog, QHBoxLayout,
                            QLabel, QListWidget, QListWidgetItem, QSplitter,
                            QTimer, QVBoxLayout, QWidget, Slider, StrongBodyLabel,
                            TitleLabel, Qt, icon, QCheckBox, QSizePolicy)
from app.viewer import Viewport, create_viewport
from core import cnnames as _cn
from core import loader as _ld
from core import gunsmith as gs
from core.features import SKINS_ENABLED
from core.types import ModelBundle


def _is_model(vpath: str) -> bool:
    try:
        from app.browser import is_model_asset
        return bool(is_model_asset(vpath))
    except Exception:                                       # noqa: BLE001
        return vpath.endswith(".uasset")


def _category(vpath: str) -> str:
    try:
        from core import cnnames
        return cnnames.category_of(vpath, "") or ""
    except Exception:                                       # noqa: BLE001
        return ""


from fluentpy import widgets as W
from PySide6.QtWidgets import QScrollArea, QFrame
from app.asset_picker import asset_picker as _PickerDialog
from core import custom_parts

# Keep the controls on this page as FluentPy's exact native classes.
PushButton, PrimaryPushButton = W.Button, W.AccentButton
ComboBox, Slider, QCheckBox, CardWidget = W.ComboBox, W.Slider, W.CheckBox, W.CardWidget


def _RecipeDialog(names, parent=None):
    return _PickerDialog("读取改枪方案", [(n, n, "", "", "") for n in names], parent=parent)


_SLIDERS = (
    ("px", "左右 X（米）", -1.5, 1.5, 0.005),
    ("py", "上下 Y（米）", -1.5, 1.5, 0.005),
    ("pz", "前后 Z（米）", -1.5, 1.5, 0.005),
    ("ry", "偏航 °", -180.0, 180.0, 1.0),
    ("rp", "俯仰 °", -180.0, 180.0, 1.0),
    ("rr", "翻滚 °", -180.0, 180.0, 1.0),
    ("sc", "缩放", 0.1, 5.0, 0.01),
)


class _InspectionAssemblyWorker(QThread):
    ready=Signal(object,str)
    def __init__(self,base,parts,path,parent=None):
        super().__init__(parent)
        self.base,self.parts,self.path=base,parts,path
        self.cancel=threading.Event()
    def run(self):
        try:
            from core.gunsmith_animation import assemble_animation
            result=assemble_animation(self.base,self.parts,self.path,cancel=self.cancel)
            if not self.cancel.is_set():self.ready.emit(result,'')
        except InterruptedError:pass
        except Exception as exc:
            if not self.cancel.is_set():self.ready.emit(None,str(exc))


class GunsmithPage(QWidget):
    """改枪台主页面。"""

    def __init__(self, window=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("gunsmithPage")
        self.host_window = window
        self.recipe = gs.Recipe()
        self.base_bundle: Optional[ModelBundle] = None
        self._part_bundles: Dict[str, Optional[ModelBundle]] = {}
        self._slot_rows: Dict[str, Tuple[QLabel, QLabel]] = {}
        self._selected: Optional[gs.PartSpec] = None
        self._loading = False
        self._preview_base = None
        self._inspection_generation=0
        self._inspection_worker=None
        self._inspection_active=False
        self._closing=False
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(24)
        self._rebuild_timer.timeout.connect(self._rebuild)
        self._catalog = gs.catalog()

        split = QSplitter(Qt.Horizontal, self)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.addWidget(split, 1)

        # ---------------- 左：主件 + 槽位 ----------------
        left_scroll = QScrollArea(split)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBar(W.FluentScrollBar(Qt.Vertical, left_scroll))
        left = QWidget()
        left_scroll.setWidget(left)
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 8, 0)
        llay.addWidget(StrongBodyLabel("改枪", left))
        hint = CaptionLabel("挑选主件、皮肤和配件；「官方配件」按游戏规则配齐", left)
        hint.setWordWrap(True)
        llay.addWidget(hint)

        self.base_row = QHBoxLayout()
        self.base_label = BodyLabel("主件：未选", left)
        self.base_label.setWordWrap(True)
        self.btn_base = PushButton("选主件", left)
        self.btn_use = PushButton("用当前模型", left)
        self.btn_official = PushButton("官方配件", left)
        self.btn_clear = PushButton("清空配件", left)
        self.base_row.addWidget(self.base_label, 1)
        llay.addLayout(self.base_row)
        for buttons in ((self.btn_base, self.btn_use), (self.btn_official, self.btn_clear)):
            row = QHBoxLayout()
            for button in buttons:
                row.addWidget(button)
            llay.addLayout(row)
        self.skin_controls = QWidget(left)
        skin_layout = QVBoxLayout(self.skin_controls)
        skin_layout.setContentsMargins(0, 0, 0, 0)
        skin_row = QHBoxLayout()
        skin_row.addWidget(CaptionLabel("枪械皮肤", self.skin_controls))
        self.skin_combo = ComboBox(self.skin_controls)
        self.skin_combo.setMinimumWidth(120)
        self.skin_combo.setToolTip("切换枪械皮肤，并替换同套皮肤中对应的配件；其他配件保留")
        skin_row.addWidget(self.skin_combo, 1)
        skin_layout.addLayout(skin_row)
        # 「应用皮肤」单独一行：左栏窄的时候和下拉挤一行会被裁掉，只剩半个字。
        skin_action = QHBoxLayout()
        self.btn_skin = PushButton("应用皮肤", self.skin_controls)
        self.btn_skin.setToolTip("套用下拉里选中的皮肤")
        skin_action.addWidget(self.btn_skin)
        skin_action.addStretch(1)
        skin_layout.addLayout(skin_action)
        self.skin_parts_switch = QCheckBox("同步官方皮肤配件", self.skin_controls)
        self.skin_parts_switch.setChecked(True)
        self.skin_parts_switch.setToolTip("使用该皮肤的官方装配；关闭后保留现有配件，仅替换对应外观")
        skin_layout.addWidget(self.skin_parts_switch)
        llay.addWidget(self.skin_controls)
        self.skin_controls.setVisible(SKINS_ENABLED)
        self._refresh_skins()

        card = CardWidget(left)
        clay = QVBoxLayout(card)
        clay.setContentsMargins(10, 8, 10, 8)
        clay.addWidget(CaptionLabel("槽位", card))
        for slot in gs.SLOTS:
            row = QHBoxLayout()
            name = QLabel(slot.label, card)
            name.setFixedWidth(66)
            cur = BodyLabel("—", card)
            cur.setMinimumWidth(0)
            cur.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            cur.setTextInteractionFlags(Qt.NoTextInteraction)
            pick = PushButton("选", card)
            pick.setFixedWidth(46)
            clear = PushButton("×", card)
            clear.setFixedWidth(28)
            row.addWidget(name)
            row.addWidget(cur, 1)
            row.addWidget(pick)
            row.addWidget(clear)
            clay.addLayout(row)
            self._slot_rows[slot.key] = (cur, name)
            pick.clicked.connect(lambda _c=False, k=slot.key: self._pick_part(k))
            clear.clicked.connect(lambda _c=False, k=slot.key: self._clear_part(k))
        llay.addWidget(card, 0)
        for text, callback in (("添加更多配件", self._add_more), ("导入本地配件", self._import_part),
                               ("移除选中配件", self._remove_selected)):
            button = W.Button(text, left)
            button.clicked.connect(callback)
            llay.addWidget(button)
        llay.addStretch(1)
        split.addWidget(left_scroll)

        # ---------------- 中：预览 ----------------
        self.preview_stack=W.AnimatedStackedWidget(split)
        self.viewport: Viewport = create_viewport(self.preview_stack)
        self.preview_stack.addWidget(self.viewport)
        from app.inspection_page import InspectionPage
        self.inspection=InspectionPage(parent=self.preview_stack,compact=True)
        self.preview_stack.addWidget(self.inspection)
        # QOpenGLWidget cannot participate in opacity effects. Keep FluentPy's
        # native container and switch the live rendering surfaces directly.
        self.preview_stack.setAnimationDuration(0)
        split.addWidget(self.preview_stack)

        # ---------------- 右：选中配件的变换 ----------------
        right_scroll = QScrollArea(split)
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBar(W.FluentScrollBar(Qt.Vertical, right_scroll))
        right = QWidget()
        right_scroll.setWidget(right)
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(8, 0, 0, 0)
        self.sel_combo = ComboBox(right)
        self.sel_combo.addItem("（未选中配件）")
        rlay.addWidget(self.sel_combo)
        self.sel_label = StrongBodyLabel("没选中配件", right)
        self.sel_label.setWordWrap(True)
        rlay.addWidget(self.sel_label)
        self.socket_combo = W.ComboBox(right)
        self.socket_combo.setToolTip("选择挂接位置，例如左、右导轨分别安装镭指和手电")
        self.socket_combo.currentIndexChanged.connect(self._on_socket)
        rlay.addWidget(self.socket_combo)
        self._sliders: Dict[str, Slider] = {}
        self._values: Dict[str, W.DoubleSpinBox] = {}
        for key, label, lo, hi, step in _SLIDERS:
            rlay.addWidget(CaptionLabel(label, right))
            row = QHBoxLayout()
            sld = Slider(Qt.Horizontal, right)
            sld.setRange(0, 1000)
            val = W.DoubleSpinBox(right)
            val.setDecimals(4)
            val.setRange(0.001 if key == "sc" else -10000.0, 10000.0)
            val.setSingleStep(step)
            val.setKeyboardTracking(False)
            val.setFixedWidth(125)
            # FluentPy's NoButtons style currently leaves a 1px edit field on
            # Qt 6.11. Preserve the native control and give its editor room.
            val.lineEdit().setMinimumWidth(88)
            val.setToolTip("可直接输入精确数值；滑块范围外的数值也会保留")
            val.valueChanged.connect(lambda v, k=key: self._on_numeric(k, v))
            row.addWidget(sld, 1)
            row.addWidget(val)
            rlay.addLayout(row)
            self._sliders[key] = sld
            self._values[key] = val
            sld.valueChanged.connect(lambda _v, k=key: self._on_slider(k))
        brow = QHBoxLayout()
        self.btn_auto = PushButton("自动对齐", right)
        self.btn_reset = PushButton("复位", right)
        brow.addWidget(self.btn_auto)
        brow.addWidget(self.btn_reset)
        rlay.addLayout(brow)
        rlay.addStretch(1)
        split.addWidget(right_scroll)
        split.setSizes([300, 780, 320])

        # ---------------- 底：方案 ----------------
        bottom = QHBoxLayout()
        self.btn_save = PushButton("保存方案", self)
        self.btn_load = PushButton("读取方案", self)
        self.btn_export = PushButton("导出 OBJ", self)
        self.btn_inspect=W.AccentButton('检视整枪',self)
        self.btn_inspect.setToolTip('使用当前皮肤、配件和位置播放第一人称检视；再次点击返回装配。')
        self.status = CaptionLabel("先选主件", self)
        bottom.addWidget(self.btn_save)
        bottom.addWidget(self.btn_load)
        bottom.addWidget(self.btn_export)
        bottom.addWidget(self.btn_inspect)
        bottom.addWidget(self.status, 1)
        root.addLayout(bottom)

        self.btn_base.clicked.connect(self._pick_base)
        self.btn_use.clicked.connect(self._use_window_model)
        self.btn_official.clicked.connect(self._apply_official)
        self.btn_skin.clicked.connect(self._apply_skin)
        self.btn_clear.clicked.connect(self._clear_parts)
        self.btn_auto.clicked.connect(self._auto_place)
        self.btn_reset.clicked.connect(self._reset_selected)
        self.btn_save.clicked.connect(self._save)
        self.btn_load.clicked.connect(self._load)
        self.btn_export.clicked.connect(self._export)
        self.btn_inspect.clicked.connect(self._toggle_inspection)
        self.sel_combo.currentIndexChanged.connect(self._on_combo)
        self._sync_sliders()

    # ------------------------------------------------------------------ 工具
    def _name(self, vpath: str) -> str:
        return custom_parts.display_name(vpath) if custom_parts.is_local(vpath) else gs.display_name(vpath, self._catalog)

    def _current_spec(self) -> Optional[gs.PartSpec]:
        for spec in self.recipe.parts:
            if spec is self._selected:
                return spec
        return None

    def _pump(self, text: str) -> None:
        """加载慢的时候让界面还能动一下：更新状态 + 处理一次事件。"""
        self.status.setText(text)
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def _bundle_for(self, vpath: str) -> Optional[ModelBundle]:
        if vpath not in self._part_bundles:
            try:
                self._part_bundles[vpath] = custom_parts.load(vpath) if custom_parts.is_local(vpath) else _ld.load_model(vpath)
            except Exception:                                # noqa: BLE001
                self._part_bundles[vpath] = None
        return self._part_bundles[vpath]

    # ------------------------------------------------------------------ 主件
    def _pick_base(self) -> None:
        dlg = _PickerDialog("选主件（机匣 / 整枪）", gs.bases(), prefer="Rec", parent=self)
        if dlg.exec() != QDialog.Accepted or not dlg.chosen:
            return
        self._set_base(dlg.chosen)

    def _use_window_model(self) -> None:
        bundle = getattr(self.host_window, "bundle", None)
        vpath = getattr(self.host_window, "current_vpath", "")
        if bundle is None or not vpath:
            self.status.setText("模型库里还没加载模型")
            return
        self.use_current(bundle, vpath)

    def use_current(self, bundle: ModelBundle, vpath: str) -> None:
        self.recipe = gs.Recipe(base=vpath, base_name=os.path.basename(vpath))
        self.base_bundle = bundle
        self._part_bundles.clear()
        self._selected = None
        self._refresh_labels()
        self._rebuild()

    def _set_base(self, vpath: str) -> None:
        self._pump("正在加载主件…")
        try:
            bundle = _ld.load_model(vpath)
        except Exception as exc:                             # noqa: BLE001
            self.status.setText("主件加载失败：%s" % exc)
            return
        if not (getattr(bundle, "mesh", None) and bundle.mesh.lods):
            self.status.setText("这个资产没有网格，换一个")
            return
        self.recipe = gs.Recipe(base=vpath, base_name=os.path.basename(vpath))
        self.base_bundle = bundle
        self._part_bundles.clear()
        self._selected = None
        self._refresh_labels()
        self._rebuild()
        # 选完主件就按官方配件配一套（用户要的「官方默认配件」），
        # 没配到再保持空，让他自己挑。
        self._apply_official()

    def _refresh_labels(self) -> None:
        self._refresh_skins()
        if self.recipe.base:
            self.base_label.setText("主件：" + self._name(self.recipe.base))
        else:
            self.base_label.setText("主件：未选")
        for slot in gs.SLOTS:
            spec = next((s for s in self.recipe.parts if s.slot == slot.key), None)
            cur, _name = self._slot_rows[slot.key]
            if slot.key == "receiver" and not spec:
                # 机匣行显示主件本身（它不是一个可删的「配件」）
                cur.setText(self._name(self.recipe.base) if self.recipe.base else "—")
                continue
            matches = [s for s in self.recipe.parts if s.slot == slot.key]
            cur.setText((f"{len(matches)} 件 · " if len(matches) > 1 else "") + self._name(spec.vpath) if spec else "—")
            cur.setToolTip("\n".join(self._name(s.vpath) for s in matches))
        self._refresh_combo()
        self._sync_sliders()

    def _refresh_skins(self) -> None:
        if not hasattr(self, "skin_combo"):
            return
        self.skin_combo.clear()
        if not SKINS_ENABLED:
            self.skin_combo.setEnabled(False)
            self.btn_skin.setEnabled(False)
            return
        if not self.recipe.base:
            self.skin_combo.addItem("先选主件")
            self.skin_combo.setEnabled(False)
            self.btn_skin.setEnabled(False)
            return
        from core import weapon_skins as ws
        try:
            skins = ws.list_skins(self.recipe.base)
        except (ValueError, OSError):
            skins = []
        current = getattr(self.recipe, "skin_id", "") or self.recipe.base
        selected = 0
        for i, skin in enumerate(skins):
            self.skin_combo.addItem(skin.name, userData=skin.id)
            if skin.id == current:
                selected = i
        if not skins:
            self.skin_combo.addItem("当前主件没有可用皮肤")
        self.skin_combo.setCurrentIndex(selected)
        self.skin_combo.setEnabled(bool(skins))
        self.btn_skin.setEnabled(bool(skins))

    def _apply_skin(self) -> None:
        if not SKINS_ENABLED:
            return
        from core import weapon_skins as ws
        skin_id = self.skin_combo.currentData()
        if not self.recipe.base or not skin_id:
            return
        self.btn_skin.setEnabled(False)
        try:
            self._pump("正在加载皮肤及对应配件…")
            result = ws.apply_skin(self.recipe, str(skin_id))
            if self.skin_parts_switch.isChecked():
                result = ws.official_parts(result.recipe)
            new_base = _ld.load_model(result.recipe.base)
            if gs._lod0(new_base) is None:
                raise ValueError("这套皮肤的主件暂时无法解析，当前装配已保留")
            unavailable = []
            effective_parts = []
            used_previous = set()
            for spec in result.recipe.parts:
                previous = self._previous_skin_part(spec, self.recipe.parts, used_previous)
                if previous is not None:
                    used_previous.add(id(previous))
                if gs._lod0(self._bundle_for(spec.vpath)) is None:
                    if previous is not None:
                        effective_parts.append(gs.PartSpec.from_dict(previous.to_dict()))
                    unavailable.append(spec.name or os.path.basename(spec.vpath))
                else:
                    if self.skin_parts_switch.isChecked() and not spec.socket:
                        gs.auto_fit(spec, gs._lod0(new_base), gs._lod0(self._bundle_for(spec.vpath)),
                                    base_vpath=result.recipe.base)
                    effective_parts.append(spec)
            result.recipe.parts = effective_parts
            self.recipe = result.recipe
            self._selected = None
            self.base_bundle = new_base
            paths = {spec.vpath for spec in self.recipe.parts}
            self._part_bundles = {p: b for p, b in self._part_bundles.items() if p in paths}
            if self._preview_base is not None:
                self._preview_base = self.recipe.base
            self._refresh_labels()
            self._rebuild()
            tail = " · %d 个配件无对应皮肤，保留原选件" % len(result.retained) if result.retained else ""
            if unavailable:
                tail += " · %d 个配件暂不可加载，已保留可用选件" % len(unavailable)
            self.status.setText("已应用皮肤：%s · 当前 %d 个配件%s" %
                                (result.skin.name, len(self.recipe.parts), tail))
        except Exception as exc:
            self.status.setText("皮肤切换失败：%s" % exc)
        finally:
            self.btn_skin.setEnabled(bool(self.skin_combo.currentData()))

    @staticmethod
    def _previous_skin_part(spec, previous_parts, used):
        """Match a failed instance by component and socket, never by slot alone."""
        from core.weapon_skins import part_identity
        family = gs.mount_family(spec.vpath, spec.slot)
        candidates = [p for p in previous_parts if id(p) not in used and p.slot == spec.slot
                      and gs.mount_family(p.vpath, p.slot) == family]
        identity = part_identity(spec.skin_source or spec.vpath)
        socket = (spec.socket or "").casefold()
        exact = [p for p in candidates if identity
                 and part_identity(p.skin_source or p.vpath) == identity
                 and (p.socket or "").casefold() == socket]
        if len(exact) == 1:
            return exact[0]
        by_socket = [p for p in candidates if socket and (p.socket or "").casefold() == socket]
        if len(by_socket) == 1:
            return by_socket[0]
        return candidates[0] if len(candidates) == 1 else None

    # ------------------------------------------------------------------ 配件
    def _pick_part(self, slot: str) -> None:
        if not self.recipe.base:
            self.status.setText("先选主件")
            return
        dlg = _PickerDialog("给「%s」挑配件" % gs.SLOT_BY_KEY[slot].label,
                            gs.parts(slot), parent=self)
        if dlg.exec() != QDialog.Accepted or not dlg.chosen:
            return
        self._pump("正在加载配件…")
        bundle = self._bundle_for(dlg.chosen)
        if not (bundle and getattr(bundle, "mesh", None) and bundle.mesh.lods):
            self.status.setText("这个配件没有网格，换一个")
            return
        spec = gs.PartSpec(vpath=dlg.chosen, slot=slot,
                           name=os.path.basename(dlg.chosen))
        if SKINS_ENABLED and self.skin_parts_switch.isChecked() and self.recipe.skin_id:
            from core import weapon_skins as ws
            selection = gs.Recipe(base=self.recipe.base, skin_id=self.recipe.skin_id,
                                  skin_base=self.recipe.skin_base, parts=[spec])
            linked = ws.apply_skin(selection, self.recipe.skin_id).recipe.parts[0]
            linked_bundle = self._bundle_for(linked.vpath)
            if gs._lod0(linked_bundle) is not None:
                spec, bundle = linked, linked_bundle
        self.recipe.parts = [s for s in self.recipe.parts if s.slot != slot]
        self.recipe.parts.append(spec)
        gs.auto_fit(spec, gs._lod0(self.base_bundle), gs._lod0(bundle),
                    base_vpath=self.recipe.base)
        self._selected = spec
        self._refresh_labels()
        self._rebuild()

    def _on_socket(self, *_):
        if self._loading: return
        spec = self._current_spec()
        if spec is None: return
        spec.socket = self.socket_combo.currentData() or ""
        self._refresh_labels()
        self._rebuild_timer.start()

    def _remove_selected(self):
        spec = self._current_spec()
        if spec is None: return
        self.recipe.parts = [s for s in self.recipe.parts if s is not spec]
        self._selected = self.recipe.parts[-1] if self.recipe.parts else None
        self._refresh_labels()
        self._rebuild()

    def _add_more(self):
        if self.base_bundle is None:
            self.status.setText("先选主件")
            return
        rows = [(p, _cn.resolve_cn(p) or "", gs.guess_slot(p), "游戏模型", "part")
                for p, cls in _ld.catalog().items() if "Mesh" in cls]
        rows.extend(custom_parts.rows())
        dlg = _PickerDialog("添加配件 · 游戏模型 / 已导入的本地配件", rows, parent=self)
        if dlg.exec() != QDialog.Accepted or not dlg.chosen: return
        slot = next((r[2] for r in rows if r[0] == dlg.chosen), "other")
        self._append_part(dlg.chosen, slot)

    def _append_part(self, path, slot):
        self._pump("正在加载配件…")
        bundle = self._bundle_for(path)
        if gs._lod0(bundle) is None:
            self.status.setText("配件加载失败，文件可能缺失或格式不受支持")
            return
        spec = gs.PartSpec(vpath=path, slot=slot, name=self._name(path))
        gs.auto_fit(spec, gs._lod0(self.base_bundle), gs._lod0(bundle), base_vpath=self.recipe.base)
        if slot == "tactical":
            used = {s.socket for s in self.recipe.parts if s.slot == slot}
            available = set(gs._sockets.socket_names(self.recipe.base))
            for other in self.recipe.parts:
                available.update(gs._sockets.socket_names(other.vpath))
            for socket in ("CommonR_point", "CommonL_point", "CommonU_point", "CommonD_point"):
                if socket in available and socket not in used:
                    spec.socket = socket
                    break
        self.recipe.parts.append(spec)
        self._selected = spec
        self._refresh_labels()
        self._rebuild()

    def _import_part(self):
        if self.base_bundle is None:
            self.status.setText("先选主件")
            return
        filename, _ = QFileDialog.getOpenFileName(self, "导入本地配件", "", "模型文件 (*.glb *.gltf *.obj *.stl *.ply *.uemodel)")
        if not filename: return
        dialog = W.FramelessDialog("导入本地配件", "模型与贴图会保存到本机配件库。导入后可手动调整位置、方向与缩放。", self)
        name = W.LineEdit(placeholder="配件名称", parent=dialog)
        name.setText(os.path.splitext(os.path.basename(filename))[0])
        slot = W.ComboBox(dialog)
        for item in gs.SLOTS:
            if item.key != "receiver": slot.addItem(item.label, item.key)
        slot.setCurrentIndex(max(0, slot.findData("tactical")))
        units = W.ComboBox(dialog)
        for label, scale in (("单位：米",1.0),("单位：厘米",0.01),("单位：毫米",0.001)): units.addItem(label,scale)
        axis = W.ComboBox(dialog)
        axis.addItem("向上轴：Y（glTF 默认）", "Y")
        axis.addItem("向上轴：Z（OBJ 常用）", "Z")
        for widget in (name, slot, units, axis): dialog.add_content_widget(widget)
        if dialog.exec() != QDialog.Accepted: return
        try:
            self._pump("正在导入模型和贴图…")
            path, bundle = custom_parts.import_file(filename, name.text(), slot.currentData(), units.currentData(), axis.currentData())
            self._part_bundles[path] = bundle
            self._append_part(path, slot.currentData())
        except Exception as exc:
            self.status.setText("导入失败：%s" % exc)

    def _clear_part(self, slot: str) -> None:
        self.recipe.parts = [s for s in self.recipe.parts if s.slot != slot]
        if self._selected is not None and self._selected.slot == slot:
            self._selected = None
        self._refresh_labels()
        self._rebuild()

    def _clear_parts(self) -> None:
        self.recipe.parts = []
        self._selected = None
        self._refresh_labels()
        self._rebuild()

    def _apply_official(self) -> None:
        if not self.recipe.base:
            self.status.setText("先选主件")
            return
        try:
            if SKINS_ENABLED:
                from core.weapon_skins import official_parts
                result = official_parts(self.recipe)
                picks = result.recipe.parts
            else:
                result = None
                picks = gs.official_loadout(self.recipe.base)
        except ValueError:
            result = None
            picks = gs.official_loadout(self.recipe.base)
        except Exception as exc:
            self.status.setText("官方配件加载失败：%s" % exc)
            return
        if not picks:
            self.status.setText("这把枪没找到官方配套件")
            return
        if result is not None:
            self.recipe = result.recipe
        else:
            self.recipe.parts = picks
        base_lod = gs._lod0(self.base_bundle)
        missing = 0
        for i, spec in enumerate(picks, 1):
            self._pump("正在装配官方配件 %d/%d…" % (i, len(picks)))
            if getattr(spec, "socket", ""):
                continue                     # 预设里写明挂点的，位置已经由 socket 定死
            missing += 1
            bundle = self._bundle_for(spec.vpath)
            if bundle is not None and base_lod is not None:
                gs.auto_fit(spec, base_lod, gs._lod0(bundle),
                            base_vpath=self.recipe.base)
        self._selected = picks[0] if picks else None
        self._refresh_labels()
        self._rebuild()
        empty = gs.missing_parts(self.recipe.base or "")
        tail = ""
        if empty:
            tail = " · 包内缺网格：%s" % "、".join(empty)
        if missing:
            self.status.setText("已按官方配件配齐 %d 件（%d 件没挂点，用包围盒兜底）%s"
                                % (len(picks), missing, tail))
        else:
            self.status.setText("已按官方配件配齐 %d 件 · 全部走官方挂点%s"
                                % (len(picks), tail))

    # ------------------------------------------------------------------ 变换
    def _refresh_combo(self) -> None:
        self._loading = True
        try:
            self.sel_combo.clear()
            self.sel_combo.addItem("（未选中配件）")
            idx = 0
            for i, spec in enumerate(self.recipe.parts):
                self.sel_combo.addItem("%s · %s" % (
                    gs.SLOT_BY_KEY.get(spec.slot, gs.SLOT_BY_KEY["other"]).label,
                    self._name(spec.vpath)) + (" · " + spec.socket if spec.socket else ""))
                if spec is self._selected:
                    idx = i + 1
            self.sel_combo.setCurrentIndex(idx)
        finally:
            self._loading = False

    def _on_combo(self, index: int) -> None:
        if self._loading:
            return
        i = index - 1
        if 0 <= i < len(self.recipe.parts):
            self._selected = self.recipe.parts[i]
        else:
            self._selected = None
        self._sync_sliders()

    @staticmethod
    def _to_slider(key: str, value: float) -> int:
        for k, _l, lo, hi, _s in _SLIDERS:
            if k == key:
                span = hi - lo
                return int(max(0, min(1000, round((value - lo) / span * 1000))))
        return 500

    @staticmethod
    def _from_slider(key: str, raw: int) -> float:
        for k, _l, lo, hi, step in _SLIDERS:
            if k == key:
                span = hi - lo
                v = lo + span * (raw / 1000.0)
                return round(v / step) * step
        return 0.0

    def _sync_sliders(self) -> None:
        spec = self._current_spec()
        self._loading = True
        try:
            self.socket_combo.clear()
            self.socket_combo.addItem("挂点：自动", "")
            self.socket_combo.setEnabled(spec is not None)
            if spec is not None:
                available = set(gs.SOCKET_CANDIDATES.get(gs.mount_family(spec.vpath, spec.slot), ()))
                for path in [self.recipe.base] + [s.vpath for s in self.recipe.parts if s is not spec]:
                    available.update(gs._sockets.socket_names(path))
                if spec.socket: available.add(spec.socket)
                for socket in sorted(available): self.socket_combo.addItem(socket, socket)
                self.socket_combo.setCurrentIndex(max(0, self.socket_combo.findData(spec.socket)))
            if spec is None:
                self.sel_label.setText("没选中配件")
                for key, _l, lo, hi, _s in _SLIDERS:
                    default = 1.0 if key == "sc" else 0.0
                    self._sliders[key].setValue(self._to_slider(key, default))
                    self._values[key].setValue(default)
                    self._values[key].setEnabled(False)
                    self._sliders[key].setEnabled(False)
                return
            sock = (" · 挂点 %s" % spec.socket) if getattr(spec, "socket", "") else ""
            self.sel_label.setText("%s · %s%s" % (
                gs.SLOT_BY_KEY.get(spec.slot, gs.SLOT_BY_KEY["other"]).label,
                self._name(spec.vpath), sock))
            vals = {"px": spec.offset[0], "py": spec.offset[1], "pz": spec.offset[2],
                    "ry": spec.rot[0], "rp": spec.rot[1], "rr": spec.rot[2],
                    "sc": spec.scale}
            for key, _l, _lo, _hi, _s in _SLIDERS:
                self._sliders[key].setValue(self._to_slider(key, float(vals[key])))
                self._values[key].setValue(float(vals[key]))
                self._values[key].setEnabled(True)
                self._sliders[key].setEnabled(True)
        finally:
            self._loading = False

    def _on_slider(self, key: str) -> None:
        if self._loading:
            return
        spec = self._current_spec()
        if spec is None:
            return
        v = self._from_slider(key, self._sliders[key].value())
        self._on_numeric(key, v)

    def _on_numeric(self, key, v):
        if self._loading:
            return
        spec = self._current_spec()
        if spec is None:
            return
        if key == "px":
            spec.offset[0] = v
        elif key == "py":
            spec.offset[1] = v
        elif key == "pz":
            spec.offset[2] = v
        elif key == "ry":
            spec.rot[0] = v
        elif key == "rp":
            spec.rot[1] = v
        elif key == "rr":
            spec.rot[2] = v
        else:
            spec.scale = max(0.001, v)
        self._loading = True
        try:
            self._values[key].setValue(v)
            self._sliders[key].setValue(self._to_slider(key, v))
        finally:
            self._loading = False
        self._rebuild_timer.start()

    def _auto_place(self) -> None:
        spec = self._current_spec()
        if spec is None or self.base_bundle is None:
            return
        bundle = self._bundle_for(spec.vpath)
        base_lod = gs._lod0(self.base_bundle)
        part_lod = gs._lod0(bundle) if bundle is not None else None
        if base_lod is None or part_lod is None:
            return
        gs.fit_to_slot(spec, base_lod, part_lod, base_vpath=self.recipe.base)
        spec.rot = [0.0, 0.0, 0.0]
        self._sync_sliders()
        self._rebuild()

    def _reset_selected(self) -> None:
        spec = self._current_spec()
        if spec is None:
            return
        spec.offset = [0.0, 0.0, 0.0]
        spec.rot = [0.0, 0.0, 0.0]
        spec.scale = 1.0
        spec.auto_scale = None
        spec.anchored = False
        self._sync_sliders()
        self._rebuild()

    # ------------------------------------------------------------------ 预览
    def _rebuild(self) -> None:
        self._stop_inspection()
        if self.base_bundle is None:
            return
        pairs = []
        for spec in self.recipe.parts:
            bundle = self._bundle_for(spec.vpath)
            if bundle is not None:
                pairs.append((spec, bundle))
        self._rebuild_timer.stop()
        try:
            combo = gs.assemble(self.base_bundle, pairs, base_vpath=self.recipe.base or "")
        except Exception as exc:
            self.status.setText("装配失败：%s" % exc)
            return
        lod = gs._lod0(combo)
        if lod is None:
            self.status.setText("合并失败")
            return
        try:
            self.viewport.set_mesh(combo.mesh, combo.materials, combo.textures,
                                   preserve_camera=self._preview_base == self.recipe.base)
            self._preview_base = self.recipe.base
        except Exception as exc:                             # noqa: BLE001
            self.status.setText("预览失败：%s" % exc)
            return
        self.status.setText("已装 %d 个配件 · %d 三角形" % (
            len(pairs), lod.triangle_count))

    def _stop_inspection(self):
        was_active=self._inspection_active
        was_preparing=self._inspection_worker is not None
        self._inspection_generation+=1
        if self._inspection_worker:self._inspection_worker.cancel.set()
        if self._inspection_active:
            self.inspection.begin_selection('')
            self.preview_stack.setCurrentIndex(0)
            self._inspection_active=False
        self.btn_inspect.setText('检视整枪')
        if not self._closing and (was_active or was_preparing):
            self.status.setText('已返回装配预览。' if was_active else '已取消检视准备。')

    def _toggle_inspection(self):
        if self._inspection_active or self._inspection_worker is not None:
            self._stop_inspection();return
        if self.base_bundle is None:
            self.status.setText('先选择主件并装配武器，再点击“检视整枪”。');return
        parts=[(deepcopy(s),self._bundle_for(s.vpath)) for s in self.recipe.parts]
        generation=self._inspection_generation
        worker=_InspectionAssemblyWorker(self.base_bundle,parts,self.recipe.base,self)
        self._inspection_worker=worker
        self.btn_inspect.setText('取消准备')
        self.status.setText('正在为当前整枪准备骨骼与配件动画…')
        def ready(bundle,error):
            if self._closing or generation!=self._inspection_generation or worker.cancel.is_set():return
            if error:
                self.status.setText('无法检视：'+error);return
            self._inspection_active=True
            self.inspection.set_bundle(bundle,getattr(bundle,'inspection_path',self.recipe.base))
            self.preview_stack.setCurrentIndex(1)
            self.btn_inspect.setText('返回装配')
            self.status.setText('正在检视当前整枪；修改装配会自动返回改枪预览。')
        worker.ready.connect(ready)
        worker.finished.connect(lambda:self._inspection_finished(worker))
        worker.start()

    def _inspection_finished(self,worker):
        if worker is self._inspection_worker:self._inspection_worker=None
        if not self._inspection_active:self.btn_inspect.setText('检视整枪')
        worker.deleteLater()

    def shutdown(self):
        self._closing=True
        self._stop_inspection()
        self.inspection.shutdown()
        if self._inspection_worker:
            self._inspection_worker.cancel.set();self._inspection_worker.wait()

    # ------------------------------------------------------------------ 方案
    def _save(self) -> None:
        if not self.recipe.base:
            self.status.setText("先选主件")
            return
        default = self._name(self.recipe.base).split("    ")[0] or "未命名"
        dialog = W.FramelessDialog("保存改枪方案", "输入方案名称", self)
        field = W.LineEdit(placeholder="方案名称", parent=dialog)
        field.setText(default)
        dialog.add_content_widget(field)
        if dialog.exec() != QDialog.Accepted or not field.text().strip():
            return
        name = field.text().strip()
        try:
            path = gs.save_recipe(self.recipe, name.strip())
            self.status.setText("已保存：%s" % path)
        except Exception as exc:                             # noqa: BLE001
            self.status.setText("保存失败：%s" % exc)

    def _load(self) -> None:
        names = gs.list_recipes()
        if not names:
            self.status.setText("还没有保存过方案")
            return
        dlg = _RecipeDialog(names, self)
        if dlg.exec() != QDialog.Accepted or not dlg.chosen:
            return
        try:
            recipe = gs.load_recipe(dlg.chosen)
        except Exception as exc:                             # noqa: BLE001
            self.status.setText("读取失败：%s" % exc)
            return
        try:
            bundle = _ld.load_model(recipe.base)
        except Exception as exc:                             # noqa: BLE001
            self.status.setText("主件加载失败：%s" % exc)
            return
        self.recipe = recipe
        self.base_bundle = bundle
        self._part_bundles.clear()
        self._selected = recipe.parts[0] if recipe.parts else None
        self._refresh_labels()
        self._rebuild()
        self.status.setText("已读取方案：%s" % dlg.chosen)

    def _export(self) -> None:
        if self.base_bundle is None:
            self.status.setText("先选主件")
            return
        box = W.FramelessDialog("导出改枪模型", "选择导出方式", self)
        mode = W.ComboBox(box)
        mode.addItems(["合并为一个 OBJ", "按槽位分部件导出"])
        box.add_content_widget(mode)
        if box.exec() != QDialog.Accepted:
            return
        if mode.currentIndex() == 0:
            self._export_merged()
        else:
            self._export_parts()

    def _export_parts(self) -> None:
        from exporters.part_export import export_parts, _safe_name
        if self.base_bundle is None:
            self.status.setText("先选主件")
            return
        directory = QFileDialog.getExistingDirectory(self, "选择分部件导出文件夹",
                                                       os.path.abspath("exports"))
        if not directory:
            return
        stem = _safe_name(os.path.splitext(os.path.basename(self.recipe.base))[0], "gunsmith")
        target = os.path.join(directory, stem + "_parts")
        count = 2
        while os.path.exists(target):
            target = os.path.join(directory, f"{stem}_parts_{count}")
            count += 1
        self.btn_export.setEnabled(False)
        try:
            self._pump("正在按槽位导出部件、材质和贴图…")
            pairs = [(spec, self._bundle_for(spec.vpath)) for spec in self.recipe.parts]
            result = export_parts(self.base_bundle, pairs, self.recipe.base, target, stem)
            if result["errors"]:
                self.status.setText("已导出 %d 个部件，%d 个失败，详情：%s" %
                                    (len(result["parts"]), len(result["errors"]), result["manifest"]))
            else:
                self.status.setText("已导出 %d 个独立部件：%s" % (len(result["parts"]), target))
        except Exception as exc:
            self.status.setText("分部件导出失败：%s" % exc)
        finally:
            self.btn_export.setEnabled(True)

    def _export_merged(self) -> None:
        if self.base_bundle is None:
            self.status.setText("先选主件")
            return
        from exporters import export_obj
        name = self._name(self.recipe.base).split("    ")[0] or "gunsmith"
        path, _f = QFileDialog.getSaveFileName(self, "导出 OBJ", name + ".obj",
                                               "Wavefront OBJ (*.obj)")
        if not path:
            return
        pairs = [(s, self._bundle_for(s.vpath)) for s in self.recipe.parts]
        pairs = [(s, b) for s, b in pairs if b is not None]
        try:
            combo = gs.assemble(self.base_bundle, pairs, base_vpath=self.recipe.base or "")
            export_obj(combo, path, mtl=True)
            self.status.setText("已导出：%s" % path)
        except Exception as exc:                             # noqa: BLE001
            self.status.setText("导出失败：%s" % exc)

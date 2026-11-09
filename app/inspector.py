"""Right hand inspector: material overrides, lighting rig, display options.

Every control here goes through the same public window methods, so the widget
works identically against `render.MeshViewer` and the software fallback:

    window.apply_material_override(metallic, roughness)
    window.apply_lighting(**params)
    window.apply_style(name) / apply_exposure(ev) / apply_background(kind)
    window.apply_lod(i) / apply_wireframe(bool)
"""
from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from app.fluent_api import (BodyLabel, CardWidget, ComboBox, FluentIcon,
                            HorizontalSeparator, IconWidget, PushButton,
                            QColor, QColorDialog, QHBoxLayout, QScrollArea,
                            QSizePolicy, QSlider, QVBoxLayout, Slider,
                            StrongBodyLabel, SubtitleLabel, SwitchButton,
                            TitleLabel, Qt, QWidget, qicon)

try:
    from app.ui_scale import px as _px
except Exception:                                            # noqa: BLE001
    def _px(value):
        return int(value)


STYLE_NAMES = (("game", "游戏影视 Game"), ("pbr", "PBR 写实"), ("toon", "卡通 Toon"),
               ("posterize", "色阶 Posterize"), ("neon", "霓虹 Neon"),
               ("blueprint", "蓝图 Blueprint"), ("clay", "陶土 Clay"))
BACKGROUND_NAMES = (("studio", "影棚渐变"), ("gradient", "深空渐变"), ("dark", "纯深色"),
                    ("grid", "网格 Grid"), ("white", "浅色"))


class _SliderRow(QWidget):
    """label + slider + numeric readout."""

    def __init__(self, text: str, minimum: int, maximum: int, value: int,
                 formatter: Callable[[int], str],
                 parent=None) -> None:
        super().__init__(parent)
        self._fmt = formatter
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.label = BodyLabel(text)
        self.label.setFixedWidth(64)
        self.slider = Slider(Qt.Horizontal, self)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.value_label = BodyLabel(formatter(value))
        self.value_label.setFixedWidth(46)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.label)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value_label)

    def value(self) -> int:
        return int(self.slider.value())

    def set_value(self, value: int) -> None:
        self.slider.setValue(int(round(value)))

    def refresh(self) -> None:
        self.value_label.setText(self._fmt(self.value()))

    def connect(self, slot: Callable[[int], None]) -> None:
        def handler(raw: int) -> None:
            self.refresh()
            slot(raw)
        self.slider.valueChanged.connect(handler)


class Inspector(QWidget):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.host_window = window
        self.setObjectName("inspectorPanel")
        self.setMinimumWidth(_px(280))
        self.setMaximumWidth(_px(360))
        self._light_color: Tuple[float, float, float] = (1.0, 0.97, 0.92)
        self._rows: Dict[str, _SliderRow] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("inspectorBody")
        scroll.setWidget(body)
        outer.addWidget(scroll)

        root = QVBoxLayout(body)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addWidget(TitleLabel("检查器"))

        root.addWidget(self._build_display())
        root.addWidget(self._build_material())
        root.addWidget(self._build_lighting())
        root.addWidget(self._spacer_text())
        root.addStretch(1)

    # -- section builders -------------------------------------------------- #
    def _card(self, title: str) -> Tuple[CardWidget, QVBoxLayout]:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel(title))
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        return card, layout

    def _build_display(self) -> QWidget:
        card, layout = self._card("显示")
        layout.addWidget(BodyLabel("LOD 级别"))
        self.lod_combo = ComboBox(card)
        self.lod_combo.addItem("LOD 0")
        self.lod_combo.currentIndexChanged.connect(
            lambda i: self.host_window.apply_lod(i))
        layout.addWidget(self.lod_combo)

        # UV 通道：该游戏的网格普遍带 2~3 套 UV（UV0 贴图 / UV1 光照图 /
        # UV2 细节图），材质里没写用哪一套时按 UV0 走；万一某套资产把光照
        # 图放在 UV1 上，切错了就是「贴图在、但位置全错」。
        layout.addWidget(BodyLabel("UV 通道"))
        self.uv_combo = ComboBox(card)
        self.uv_combo.addItem("UV0")
        self.uv_combo.currentIndexChanged.connect(
            lambda i: self.host_window.apply_uv_channel(i))
        layout.addWidget(self.uv_combo)

        layout.addWidget(BodyLabel("渲染风格"))
        self.style_combo = ComboBox(card)
        for key, label in STYLE_NAMES:
            self.style_combo.addItem(f"{label}  ({key})", userData=key)
        self.style_combo.currentIndexChanged.connect(
            lambda i: self.host_window.apply_style(self.style_combo.itemData(i) or "pbr"))
        layout.addWidget(self.style_combo)

        layout.addWidget(BodyLabel("背景"))
        self.background_combo = ComboBox(card)
        for key, label in BACKGROUND_NAMES:
            self.background_combo.addItem(f"{label}  ({key})", userData=key)
        self.background_combo.currentIndexChanged.connect(
            lambda i: self.host_window.apply_background(self.background_combo.itemData(i) or "studio"))
        layout.addWidget(self.background_combo)

        self._rows["exposure"] = _SliderRow(
            "曝光 EV", -200, 200, 0, lambda v: f"{v / 100:+.2f}", card)
        self._rows["exposure"].connect(lambda v: self.host_window.apply_exposure(v / 100.0))
        layout.addWidget(self._rows["exposure"])

        wire_row = QHBoxLayout()
        wire_row.addWidget(BodyLabel("线框模式"), 1)
        self.wire_switch = SwitchButton(card)
        self.wire_switch.setOnText("开")
        self.wire_switch.setOffText("关")
        self.wire_switch.checkedChanged.connect(self.host_window.apply_wireframe)
        wire_row.addWidget(self.wire_switch)
        layout.addLayout(wire_row)

        # 手机屏/手表序列帧这类「Masked 但一张贴图都没有」的面，画出来是一整片白，
        # 默认不画；想确认几何还在就把这个开关打开。
        overlay_row = QHBoxLayout()
        overlay_row.addWidget(BodyLabel("显示无贴图部件"), 1)
        self.overlay_switch = SwitchButton(card)
        self.overlay_switch.setOnText("开")
        self.overlay_switch.setOffText("关")
        self.overlay_switch.checkedChanged.connect(
            lambda on: self.host_window.apply_show_untextured(bool(on)))
        overlay_row.addWidget(self.overlay_switch)
        layout.addLayout(overlay_row)

        from fluentpy import widgets as W
        self.inspect_btn = W.Button("当前模型没有检视动画", card)
        self.inspect_btn.setEnabled(False)
        self.inspect_btn.clicked.connect(self.host_window.toggle_inspect)
        layout.addWidget(self.inspect_btn)

        return card

    def _build_material(self) -> QWidget:
        card, layout = self._card("材质覆盖")
        # 材质槽：干员/皮肤网格在导出体里没有 section 表，整只模型只能用一个材质，
        # 默认用最像自己的那格；挑错了（脸/头发用成衣服图集）就在这里手动换，
        # 选择按资产记住，存在 work/material_table.json。
        layout.addWidget(BodyLabel("材质槽"))
        self.material_combo = ComboBox(card)
        self.material_combo.addItem("自动（1 个）", userData=0)
        self.material_combo.currentIndexChanged.connect(
            lambda i: self.host_window.apply_material_slot(
                self.material_combo.itemData(i) if self.material_combo.itemData(i) is not None else i))
        layout.addWidget(self.material_combo)
        layout.addWidget(BodyLabel("金属度 metallic · 0 ~ 1"))
        self._rows["metallic"] = _SliderRow(
            "metallic", 0, 100, 0, lambda v: f"{v / 100:.2f}", card)
        self._rows["metallic"].connect(
            lambda v: self.host_window.apply_material_override(metallic=v / 100.0))
        layout.addWidget(self._rows["metallic"])

        layout.addWidget(BodyLabel("粗糙度 roughness · 0 ~ 1"))
        self._rows["roughness"] = _SliderRow(
            "roughness", 0, 100, 50, lambda v: f"{v / 100:.2f}", card)
        self._rows["roughness"].connect(
            lambda v: self.host_window.apply_material_override(roughness=v / 100.0))
        layout.addWidget(self._rows["roughness"])

        reset = PushButton("恢复材质默认", card)
        reset.clicked.connect(self.reset_material)
        layout.addWidget(reset)
        return card

    def _build_lighting(self) -> QWidget:
        card, layout = self._card("灯光")
        specs = (
            ("azimuth", "主光方位", 0, 360, 42, lambda v: f"{v}°", lambda v: v),
            ("elevation", "主光高度", -10, 90, 38, lambda v: f"{v}°", lambda v: v),
            ("intensity", "主光强度", 0, 300, 135, lambda v: f"{v / 100:.2f}",
             lambda v: v / 100.0),
            ("fill", "补光强度", 0, 200, 42, lambda v: f"{v / 100:.2f}", lambda v: v / 100.0),
            ("rim", "轮廓光强度", 0, 200, 55, lambda v: f"{v / 100:.2f}", lambda v: v / 100.0),
            ("ambient", "环境光强度", 0, 100, 18, lambda v: f"{v / 100:.2f}", lambda v: v / 100.0),
        )
        for key, label, lo, hi, default, fmt, _scale in specs:
            row = _SliderRow(label, lo, hi, default, fmt, card)
            row.connect(lambda v, k=key, s=_scale: self._lighting_changed(k, s(v)))
            layout.addWidget(row)
            self._rows["light_" + key] = row

        color_row = QHBoxLayout()
        color_row.addWidget(BodyLabel("主光颜色"), 1)
        self.color_button = PushButton("■", card)
        self.color_button.setFixedWidth(88)
        self._paint_color_button()
        self.color_button.clicked.connect(self._pick_color)
        color_row.addWidget(self.color_button)
        layout.addLayout(color_row)
        return card

    def _spacer_text(self) -> QWidget:
        label = BodyLabel("参数变化即时作用到渲染器")
        label.setWordWrap(True)
        return label

    # -- actions ----------------------------------------------------------- #
    # 滑杆上写的是「主光方位 / 补光强度」这种短名，LightingState.merge 认的是
    # key_azimuth / fill_intensity 这种全名；中间不做映射的话参数会落到 unknown 里，
    # 表现出来就是「灯光怎么拉都没反应」。
    _LIGHT_KEYS = {
        "azimuth": "key_azimuth",
        "elevation": "key_elevation",
        "intensity": "key_intensity",
        "fill": "fill_intensity",
        "rim": "rim_intensity",
        "ambient": "env_intensity",
        "color": "key_color",
    }

    def _lighting_changed(self, key: str, value) -> None:
        self.host_window.apply_lighting(**{self._LIGHT_KEYS.get(key, key): value})

    def _paint_color_button(self) -> None:
        r, g, b = (int(round(c * 255)) for c in self._light_color)
        text_color = "#101010" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#f0f0f0"
        self.color_button.setStyleSheet(
            f"QPushButton {{ background: rgb({r},{g},{b}); color: {text_color};"
            f" border: 1px solid rgba(255,255,255,0.25); border-radius: 8px;"
            f" font-size: 12px; padding: 0px; }}")
        self.color_button.setText(f"#{r:02X}{g:02X}{b:02X}")

    def _pick_color(self) -> None:
        r, g, b = (int(round(c * 255)) for c in self._light_color)
        chosen = QColorDialog.getColor(QColor(r, g, b), self, "选择主光颜色")
        if chosen.isValid():
            self._light_color = (chosen.redF(), chosen.greenF(), chosen.blueF())
            self._paint_color_button()
            self.host_window.apply_lighting(key_color=self._light_color)

    def reset_material(self) -> None:
        self.set_metallic(0.0)
        self.set_roughness(0.5)

    # -- public state ------------------------------------------------------- #
    def set_metallic(self, value: float) -> None:
        self._rows["metallic"].set_value(value * 100.0)

    def set_roughness(self, value: float) -> None:
        self._rows["roughness"].set_value(value * 100.0)

    def set_exposure(self, ev: float) -> None:
        self._rows["exposure"].set_value(ev * 100.0)

    def set_lod_list(self, count: int, triangles: Optional[int] = None) -> None:
        self.lod_combo.blockSignals(True)
        self.lod_combo.clear()
        for i in range(max(1, count)):
            self.lod_combo.addItem(f"LOD {i}")
        self.lod_combo.setCurrentIndex(0)
        self.lod_combo.blockSignals(False)

    def set_material_list(self, names, current: int = 0) -> None:
        """按当前模型有几个材质槽刷新下拉（只有一个时置灰）。"""
        names = list(names or [])
        combo = getattr(self, "material_combo", None)
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        for i, name in enumerate(names):
            short = str(name) or f"材质 {i + 1}"
            combo.addItem(f"{i + 1}. {short[:34]}", userData=i)
        if not names:
            combo.addItem("自动（1 个）", userData=0)
        combo.setCurrentIndex(max(0, min(int(current or 0), combo.count() - 1)))
        combo.setEnabled(len(names) > 1)
        combo.blockSignals(False)

    def set_uv_list(self, count: int) -> None:
        """按当前 LOD 实际有几套 UV 刷新下拉。"""
        count = max(1, int(count or 1))
        self.uv_combo.blockSignals(True)
        self.uv_combo.clear()
        for i in range(count):
            self.uv_combo.addItem(f"UV{i}")
        self.uv_combo.setCurrentIndex(0)
        self.uv_combo.setEnabled(count > 1)
        self.uv_combo.blockSignals(False)

    def set_inspection_count(self, count=0, *, loading=False):
        self.inspect_btn.setEnabled(count > 0 and not loading)
        self.inspect_btn.setText("正在查找对应动画…" if loading else
                                 f"检视当前模型 · {count} 个动作" if count else "当前模型没有检视动画")
        self.inspect_btn.setToolTip("打开检视页，自动播放当前选中模型的对应动作")

    def set_inspect_anim(self, duration=0.0, label=""):
        self.set_inspection_count(1 if label else 0)

    def set_style_name(self, name: str) -> None:
        for i in range(self.style_combo.count()):
            if self.style_combo.itemData(i) == name:
                self.style_combo.setCurrentIndex(i)
                return

    def set_background(self, name: str) -> None:
        for i in range(self.background_combo.count()):
            if self.background_combo.itemData(i) == name:
                self.background_combo.setCurrentIndex(i)
                return

    def current_lod(self) -> int:
        return max(0, int(self.lod_combo.currentIndex()))

    def values(self) -> Dict[str, float]:
        out = {key: row.value() for key, row in self._rows.items()}
        out["style"] = self.style_combo.currentData()
        out["background"] = self.background_combo.currentData()
        out["wireframe"] = bool(self.wire_switch.isChecked())
        out["light_color"] = tuple(round(c, 3) for c in self._light_color)
        return out

    def light_color(self) -> Tuple[float, float, float]:
        return self._light_color

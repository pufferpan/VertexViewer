"""The five navigation pages.

    LibraryPage   模型库  -- browser | viewport | inspector + bottom status strip
    TexturesPage  贴图    -- texture grid + large preview (GenTexDirHD pak)
    MaterialsPage 材质    -- material table of the current bundle
    ExportPage    导出    -- OBJ export options, runs `exporters.obj`
    SettingsPage  设置    -- theme, cache lifecycle, backends, about

All widgets come from `app.fluent_api` so the same code runs on the vendored
FluentPy (XDDXMT) / the pure-Qt self drawn fallback.
"""
from __future__ import annotations

import os
import time
from typing import Dict, List, Optional

import numpy as np

from app.fluent_api import (BodyLabel, CaptionLabel, CardWidget, ComboBox,
                            PrimaryPushButton, ProgressBar, PushButton,
                            QDoubleSpinBox, QHBoxLayout, QHeaderView, QImage,
                            QLabel, QListWidget, QListWidgetItem, QPixmap,
                            QPlainTextEdit, QSizePolicy, QSplitter,
                            QTableWidget, QTableWidgetItem, QVBoxLayout,
                            QWidget, ScrollArea, StrongBodyLabel, SwitchButton,
                            Theme, TitleLabel, Qt, isDarkTheme, qicon, setTheme,
                            QApplication, QMessageBox)
from app.inspector import Inspector, STYLE_NAMES

CAPTURE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "captures"))


def _gen_tex_candidates(vpath: str, limit: int = 32):
    """GenTexDirHD twin pak entries for a model, as (name, vpath) pairs.

    The texture assets are stored in their own pak (…/Content/GenTexDirHD/Game/
    Models/<folder>/…) rather than next to the mesh, so a model that the loader
    has not decoded yet still gets a meaningful list here.
    """
    if not vpath:
        return []
    try:
        from core.loader import index
    except Exception:                                       # noqa: BLE001
        return []
    folder = os.path.basename(os.path.dirname(vpath.replace("\\", "/")))
    if not folder:
        return []
    needle = f"/GenTexDirHD/Game/Models/"
    marker = f"/{folder}/"
    found = []
    try:
        for path in index():
            if not path.lower().endswith(".uasset"):
                continue
            if needle not in path or marker not in path:
                continue
            name = os.path.splitext(os.path.basename(path))[0]
            if not name.startswith("T_"):
                continue
            found.append((name, path))
            if len(found) >= limit:
                break
    except Exception:                                       # noqa: BLE001
        return []
    found.sort()
    return found


def human_bytes(count: float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(max(0.0, count))
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.1f} TB"


def _elide(text: str, limit: int = 90) -> str:
    if len(text) <= limit:
        return text
    keep = limit - 3
    head = keep // 2
    return f"{text[:head]}…{text[-(keep - head):]}"


def texture_pixmap(tex, size: int = 96) -> Optional[QPixmap]:
    """Texture.rgba (H,W,4) uint8 -> scaled QPixmap."""
    rgba = getattr(tex, "rgba", None)
    if rgba is None:
        return None
    try:
        arr = np.ascontiguousarray(rgba)
    except Exception:                                       # noqa: BLE001
        return None
    if arr.ndim == 2:
        arr = np.dstack([arr, arr, arr, np.full(arr.shape, 255, arr.dtype)])
    if arr.ndim != 3 or arr.shape[2] < 3:
        return None
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.shape[2] == 3:
        arr = np.dstack([arr, np.full(arr.shape[:2], 255, np.uint8)])
    arr = np.ascontiguousarray(arr[..., :4])
    height, width = arr.shape[:2]
    image = QImage(arr.data, width, height, width * 4,
                   QImage.Format.Format_RGBA8888).copy()
    pix = QPixmap.fromImage(image)
    if size and (width > size or height > size):
        pix = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return pix


# --------------------------------------------------------------------------- #
# model library page
# --------------------------------------------------------------------------- #
class StatusStrip(QWidget):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.host_window = window
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 4, 10, 4)
        row.setSpacing(14)
        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.setScaledContents(True)
        self.icon_label.setVisible(False)
        self.path_label = BodyLabel("未加载资产")
        self.path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.tris_label = BodyLabel("三角形 0")
        self.tris_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.cache_label = BodyLabel("缓存 0 B")
        self.cache_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.progress = ProgressBar(self)
        self.progress.setFixedWidth(160)
        self.progress.setVisible(False)
        row.addWidget(self.icon_label)
        row.addWidget(self.path_label, 1)
        row.addWidget(self.tris_label)
        row.addWidget(self.cache_label)
        row.addWidget(self.progress)
        self.setFixedHeight(34)

    def set_asset(self, text: str) -> None:
        self.path_label.setText(_elide(text))

    def set_icon(self, path: Optional[str]) -> None:
        """状态栏左侧的物品图标（没有就隐藏）。"""
        if not path or not os.path.isfile(path):
            self.icon_label.setVisible(False)
            return
        pix = QPixmap(path)
        if pix.isNull():
            self.icon_label.setVisible(False)
            return
        self.icon_label.setPixmap(pix.scaled(24, 24, Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation))
        self.icon_label.setVisible(True)

    def set_triangles(self, count: int) -> None:
        self.tris_label.setText(f"三角形 {count:,}")
        self.tris_label.setMinimumWidth(self.tris_label.sizeHint().width() + 2)

    def set_cache(self, size: int) -> None:
        self.cache_label.setText(f"缓存 {human_bytes(size)}")
        self.cache_label.setMinimumWidth(self.cache_label.sizeHint().width() + 2)

    def set_progress(self, value: Optional[float]) -> None:
        if value is None:
            self.progress.setVisible(False)
            return
        self.progress.setVisible(True)
        if value < 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(max(0, min(100, value))))


class LibraryPage(QWidget):
    def __init__(self, window, viewport, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("libraryPage")
        self.host_window = window
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        toolbar = QWidget(self)
        toolbar.setObjectName("libraryToolbar")
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(12, 8, 12, 8)
        bar.setSpacing(8)
        self.open_button = PushButton(qicon("folder"), "打开游戏目录", toolbar)
        self.uef_open_button = PushButton(qicon("folder"), "打开 .uemodel", toolbar)
        self.export_button = PushButton(qicon("save"), "导出 OBJ", toolbar)
        self.glb_button = PushButton(qicon("save"), "导出 GLB", toolbar)
        self.glb_button.setToolTip("连同骨骼和蒙皮权重一起导出，Blender 里可以继续摆姿势")
        self.capture_button = PushButton(qicon("camera"), "抓图", toolbar)
        self.fullscreen_button = PushButton(qicon("fullscreen"), "全屏", toolbar)
        for button in (self.open_button, self.uef_open_button, self.export_button,
                       self.glb_button, self.capture_button, self.fullscreen_button):
            bar.addWidget(button)
        bar.addStretch(1)
        self.backend_label = CaptionLabel("渲染器：—")
        bar.addWidget(self.backend_label)
        root.addWidget(toolbar)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setContentsMargins(8, 0, 8, 0)
        self.browser = window.browser
        self.viewport = viewport
        self.inspector = Inspector(window, self)
        splitter.addWidget(self.browser)
        splitter.addWidget(self.viewport)
        splitter.addWidget(self.inspector)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([372, 880, 310])
        root.addWidget(splitter, 1)

        self.status = StatusStrip(window, self)
        root.addWidget(self.status)

        self.open_button.clicked.connect(window.open_game_dir)
        self.uef_open_button.clicked.connect(self._open_uemodel)
        self.export_button.clicked.connect(window.export_current)
        self.glb_button.clicked.connect(lambda: window.export_glb())
        self.capture_button.clicked.connect(window.capture_view)
        self.fullscreen_button.clicked.connect(window.toggle_fullscreen)
        self.refresh_backend()

    def refresh_backend(self) -> None:
        vp = self.viewport
        name = "OpenGL" if vp.is_gl else "软件着色"
        self.backend_label.setText(f"渲染器：{name} · {_elide(vp.backend_detail, 48)}")

    def refresh_cache(self) -> None:
        try:
            self.status.set_cache(self.host_window.cache.size_bytes())
        except Exception:                                   # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# textures
# --------------------------------------------------------------------------- #
    def _open_uemodel(self) -> None:
        """直接打开 UEFormat `.uemodel`（别人用 FModel/UEFormat 导出的也能看）。"""
        from app.fluent_api import QFileDialog
        from core import ueformat as _uef
        from core.types import ModelBundle

        path, _ = QFileDialog.getOpenFileName(self, "打开 .uemodel", "",
                                              "UEFormat 模型 (*.uemodel)")
        if not path:
            return
        try:
            mesh, name, obj_path = _uef.read_uemodel(path)
        except Exception as exc:                            # noqa: BLE001
            self._append(f"打不开 {os.path.basename(path)}：{type(exc).__name__}: {exc}")
            return
        bundle = ModelBundle(mesh=mesh, materials=[], textures=[],
                             display_name=name or os.path.basename(path))
        # 视图和检查器都吃同一个 bundle
        views = [self.host_window.viewport, getattr(self.host_window, "inspector", None)]
        self.host_window.set_bundle(bundle) if hasattr(self.host_window, "set_bundle") else None
        try:
            self.host_window.viewport.set_mesh(mesh, [], [])
        except Exception:                                   # noqa: BLE001
            pass
        self._append(f"已打开 UEFormat 模型 {os.path.basename(path)} · "
                     f"{len(mesh.lods)} LOD · {len(mesh.lods[0].indices)//3:,} 三角形")

class TexturesPage(QWidget):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("texturesPage")
        self.host_window = window
        self._textures: List = []
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)
        header = QHBoxLayout()
        title = TitleLabel("贴图")
        self.count_label = CaptionLabel("未加载模型")
        header.addWidget(title)
        header.addSpacing(10)
        header.addWidget(self.count_label, 1)
        root.addLayout(header)
        hint = CaptionLabel("贴图与模型分属不同 pak：模型在 Models/，贴图在 GenTexDirHD/Game/Models/…")
        hint.setWordWrap(True)
        root.addWidget(hint)

        splitter = QSplitter(Qt.Horizontal, self)
        self.list = QListWidget(self)
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setGridSize(self.list.gridSize().__class__(148, 168))
        self.list.setIconSize(self.list.iconSize().__class__(112, 112))
        self.list.setWordWrap(True)
        self.list.currentRowChanged.connect(self._show_current)
        splitter.addWidget(self.list)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)
        self.preview = QLabel(right)
        self.preview.setMinimumSize(360, 360)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background: rgba(0,0,0,0.18); border-radius: 8px;")
        self.info = BodyLabel("选择左侧贴图查看详情")
        self.info.setWordWrap(True)
        right_layout.addWidget(self.preview, 1)
        right_layout.addWidget(self.info)
        splitter.addWidget(right)
        splitter.setSizes([520, 720])
        root.addWidget(splitter, 1)

    def set_bundle(self, bundle, vpath: str = "") -> None:
        self.list.clear()
        self.preview.clear()
        self._textures = list(getattr(bundle, "textures", []) or []) if bundle else []
        if not self._textures:
            candidates = _gen_tex_candidates(vpath) if bundle else []
            if candidates:
                self.count_label.setText(f"{len(candidates)} 个 GenTexDirHD 贴图（未解码）")
                for name, path in candidates:
                    item = QListWidgetItem(name)
                    item.setIcon(qicon("photo"))
                    item.setToolTip(path)
                    self.list.addItem(item)
                self.info.setText(
                    "这些是 GenTexDirHD 侧与模型同名的贴图 pak 条目；\n"
                    "核心解码（core.loader.load_textures_for）接上后会在这里显示像素。")
            else:
                self.count_label.setText("该模型没有解析出贴图" if bundle else "未加载模型")
                self.info.setText("模型贴图会出现在这里；贴图 pak 名形如 …GenTexDirHD…")
            return
        self.count_label.setText(f"{len(self._textures)} 张贴图")
        for tex in self._textures:
            pix = texture_pixmap(tex, 112)
            label = f"{tex.name}\n{tex.width}×{tex.height}"
            item = QListWidgetItem(label)
            if pix is not None:
                item.setIcon(pix)
            else:
                item.setIcon(qicon("photo"))
            item.setToolTip(getattr(tex, "pak_path", ""))
            item.setSizeHint(item.sizeHint())
            self.list.addItem(item)
        self.list.setCurrentRow(0)

    def _show_current(self, row: int) -> None:
        if row < 0 or row >= len(self._textures):
            return
        tex = self._textures[row]
        pix = texture_pixmap(tex, 0)
        if pix is None:
            self.preview.setText("无法解码该贴图")
        else:
            self.preview.setPixmap(pix.scaled(640, 640, Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation))
        srgb = "sRGB" if getattr(tex, "srgb", True) else "线性"
        self.info.setText(
            f"{tex.name} · {tex.width}×{tex.height} · {srgb} · {getattr(tex, 'source_format', '?')}\n"
            f"来源：{getattr(tex, 'pak_path', '')}")


# --------------------------------------------------------------------------- #
# materials
# --------------------------------------------------------------------------- #
class MaterialsPage(QWidget):
    COLUMNS = ("材质", "父材质", "metallic", "roughness", "基础色", "贴图")

    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("materialsPage")
        self.host_window = window
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(TitleLabel("材质"))
        self.count_label = CaptionLabel("未加载模型")
        header.addSpacing(10)
        header.addWidget(self.count_label, 1)
        root.addLayout(header)

        self.table = QTableWidget(self)
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, len(self.COLUMNS)):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents)
        self.table.currentCellChanged.connect(lambda row, *_: self._show_detail(row))
        root.addWidget(self.table, 1)

        card = CardWidget(self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(4)
        card_layout.addWidget(StrongBodyLabel("材质详情"))
        self.detail = BodyLabel("选择一行查看参数与贴图槽")
        self.detail.setWordWrap(True)
        card_layout.addWidget(self.detail)
        self.apply_btn = PushButton("整套网格用这个材质", card)
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply_current)
        card_layout.addWidget(self.apply_btn)
        root.addWidget(card)
        self._materials: List = []

    def set_bundle(self, bundle) -> None:
        self._materials = list(getattr(bundle, "materials", []) or []) if bundle else []
        if not self._materials and bundle is not None:
            self._fill_section_refs(bundle)
            return
        self.table.setRowCount(len(self._materials))
        if not self._materials:
            self.count_label.setText("该模型没有材质覆盖" if bundle else "未加载模型")
            self.detail.setText("解析出的材质会列在这里")
            return
        self.count_label.setText(f"{len(self._materials)} 个材质")
        for row, mat in enumerate(self._materials):
            base = getattr(mat, "base_color", None) or (1, 1, 1, 1)
            base_text = " ".join(f"{float(c):.2f}" for c in base)
            color = getattr(mat, "base_color_texture", "")
            values = (getattr(mat, "name", "?"),
                      getattr(mat, "parent", "") or "—",
                      f"{float(getattr(mat, 'metallic', 0.0)):.2f}",
                      f"{float(getattr(mat, 'roughness', 0.5)):.2f}",
                      base_text,
                      os.path.basename(color) if color else "—")
            for column, text in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(text)))
        self.table.setCurrentCell(0, 0)
        self._show_detail(0)
        # 多材质 + 只有一个 section 的 1P 模型，靠这行按钮手动挑正确的那套贴图
        if len(self._materials) > 1:
            self.apply_btn.setEnabled(True)
            self.apply_btn.setToolTip("整个网格统一用当前选中的材质渲染"
                                      "（1P 模型常常只有一段几何，没法自动分材质）")
        else:
            self.apply_btn.setEnabled(False)

    def _apply_current(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self.host_window.apply_material_index(row)
        self._show_detail(row)

    def _fill_section_refs(self, bundle) -> None:
        """Fallback view: the material asset paths named by the mesh sections."""
        paths: List[str] = []
        mesh = getattr(bundle, "mesh", None)
        for lod in getattr(mesh, "lods", []) or []:
            for section in getattr(lod, "sections", []) or []:
                path = getattr(section, "material_path", "") or ""
                if path and path not in paths:
                    paths.append(path)
        self.table.setRowCount(len(paths))
        for row, path in enumerate(paths):
            name = os.path.splitext(os.path.basename(path))[0]
            values = (name, "—", "—", "—", "—", os.path.basename(path))
            for column, text in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(text)))
            self.table.item(row, 0).setToolTip(path)
        self.count_label.setText(
            f"{len(paths)} 个材质引用（参数未解析）" if paths else "该模型没有材质引用")
        self.detail.setText(
            "材质引用来自 mesh section 的 material_path；metallic / roughness / 贴图槽\n"
            "需要 core.loader 解析材质符号后才有数值。")

    def _show_detail(self, row: int) -> None:
        if row < 0 or row >= len(self._materials):
            return
        mat = self._materials[row]
        slots = {
            "base_color": getattr(mat, "base_color_texture", ""),
            "normal": getattr(mat, "normal_texture", ""),
            "orm": getattr(mat, "orm_texture", ""),
            "emissive": getattr(mat, "emissive_texture", ""),
        }
        slot_text = " · ".join(f"{key}={os.path.basename(v) or '—'}"
                               for key, v in slots.items())
        params = getattr(mat, "scalar_params", {}) or {}
        extra = ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}"
                          for k, v in list(params.items())[:6])
        self.detail.setText(
            f"pak: {getattr(mat, 'pak_path', '')}\n"
            f"混合模式: {getattr(mat, 'blend_mode', '?')} · 双面: "
            f"{bool(getattr(mat, 'two_sided', False))}\n"
            f"贴图槽: {slot_text}\n"
            f"标量参数: {extra or '—'}")


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
class ExportPage(QWidget):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("exportPage")
        self.host_window = window
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(TitleLabel("导出 OBJ"))
        self.target_label = CaptionLabel("未加载模型")
        header.addSpacing(10)
        header.addWidget(self.target_label, 1)
        root.addLayout(header)

        options = CardWidget(self)
        grid = QVBoxLayout(options)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setSpacing(8)

        row1 = QHBoxLayout()
        row1.addWidget(BodyLabel("LOD"))
        self.lod_combo = ComboBox(options)
        self.lod_combo.addItem("全部 LOD", userData=-1)
        row1.addWidget(self.lod_combo)
        row1.addSpacing(18)
        row1.addWidget(BodyLabel("缩放"))
        self.scale_spin = QDoubleSpinBox(options)
        self.scale_spin.setDecimals(3)
        self.scale_spin.setRange(0.001, 1000.0)
        self.scale_spin.setValue(1.0)
        self.scale_spin.setSingleStep(0.1)
        row1.addWidget(self.scale_spin)
        row1.addSpacing(18)
        row1.addWidget(BodyLabel("坐标轴"))
        self.axis_combo = ComboBox(options)
        self.axis_combo.addItem("GL（Y 上）", userData="gl")
        self.axis_combo.addItem("UE（Z 上 / cm）", userData="ue")
        row1.addWidget(self.axis_combo)
        row1.addStretch(1)
        grid.addLayout(row1)

        row2 = QHBoxLayout()
        self.mtl_switch = SwitchButton(options)
        self.mtl_switch.setChecked(True)
        row2.addWidget(BodyLabel("导出 .mtl 与贴图"))
        row2.addWidget(self.mtl_switch)
        row2.addSpacing(18)
        self.flip_switch = SwitchButton(options)
        self.flip_switch.setChecked(True)
        row2.addWidget(BodyLabel("翻转 UV 的 V 轴"))
        row2.addWidget(self.flip_switch)
        row2.addSpacing(18)
        self.merge_switch = SwitchButton(options)
        row2.addWidget(BodyLabel("合并 section 到单个对象"))
        row2.addWidget(self.merge_switch)
        row2.addStretch(1)
        grid.addLayout(row2)

        buttons = QHBoxLayout()
        self.export_button = PrimaryPushButton(qicon("save"), "选择目录并导出", options)
        self.quick_button = PushButton(qicon("download"), "导出到 exports/", options)
        self.uemodel_button = PushButton(qicon("save"), "先导出 .uemodel（几何）", options)
        self.uemodel_button.setToolTip(
            "两段式导出的第一段：只写几何（顶点/法线/UV/切线/索引），不解析贴图。\n"
            "第二段用「.uemodel 上材质」把材质和贴图补回去再导 OBJ。")
        self.export_button.clicked.connect(lambda: self._export(choose=True))
        self.quick_button.clicked.connect(lambda: self._export(choose=False))
        self.uemodel_button.clicked.connect(lambda: self._export_uemodel(choose=True))
        self.fmodel_button = PushButton(qicon("folder"), "按 FModel 目录导出（模型+材质+贴图）", options)
        self.fmodel_button.setToolTip(
            "照 FModel 的口径落盘：模型目录下放 .uemodel/.json/.obj，贴图放进同一模型的\n"
            "Textures/（按包路径还原）。材质里引用的贴图写成相对路径，换机器也能直接用。")
        self.fmodel_button.clicked.connect(lambda: self._export_fmodel(choose=True))
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.quick_button)
        buttons.addWidget(self.uemodel_button)
        buttons.addWidget(self.fmodel_button)
        buttons.addStretch(1)
        grid.addLayout(buttons)
        root.addWidget(options)

        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(220)
        self.log.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace;")
        root.addWidget(self.log, 1)

    def set_bundle(self, bundle, vpath: str = "") -> None:
        self.lod_combo.blockSignals(True)
        self.lod_combo.clear()
        self.lod_combo.addItem("全部 LOD", userData=-1)
        lods = list(getattr(getattr(bundle, "mesh", None), "lods", []) or []) if bundle else []
        for index, lod in enumerate(lods):
            self.lod_combo.addItem(
                f"LOD {index} · {lod.triangle_count:,} tris", userData=index)
        self.lod_combo.blockSignals(False)
        self.target_label.setText(_elide(vpath or "未加载模型", 80))

    def _export_uemodel(self, *, choose: bool) -> None:
        """第一段导出：几何存成 .uemodel，材质只留引用。"""
        bundle = self.host_window.bundle
        if bundle is None:
            self._append("还没有加载模型。")
            return
        target = None
        if choose:
            from app.fluent_api import QFileDialog

            name = getattr(getattr(bundle, "mesh", None), "name", "model") or "model"
            target, _ = QFileDialog.getSaveFileName(
                self, "保存 .uemodel", os.path.join(os.path.abspath("exports"), name + ".uemodel"),
                "UE 模型 (*.uemodel)")
            if not target:
                return
        else:
            target = os.path.join(os.path.abspath("exports"),
                                  getattr(bundle.mesh, "name", "model") + ".uemodel")
        lod_data = self.lod_combo.currentData()
        lod = 0 if lod_data in (None, -1) else int(lod_data)
        try:
            # 严格按 h4lfheart/UEFormat 的二进制规范写（UEFORMAT / UEMODEL）
            from core import ueformat as _uef
            from core.types import Mesh as _Mesh

            mesh = _Mesh(name=getattr(bundle.mesh, "name", "model"),
                         pak_path=getattr(bundle.mesh, "pak_path", ""),
                         lods=[bundle.mesh.lods[lod]], source_format="UEFORMAT")
            paths = {i: (m.pak_path or "") for i, m in enumerate(bundle.materials or [])}
            info = _uef.write_uemodel(
                mesh, target,
                object_name=getattr(bundle.mesh, "name", "model"),
                object_path=getattr(bundle.mesh, "pak_path", ""),
                material_paths=paths)
            info["materials"] = len(bundle.materials or [])
            info["verts"], info["tris"], info["lods"] = info["vertices"], info["triangles"], 1
        except Exception as exc:                            # noqa: BLE001
            self._append(f".uemodel 导出失败：{type(exc).__name__}: {exc}")
            return
        self._append(f"已写 {info['path']} · {info['verts']:,} v / {info['tris']:,} f · "
                     f"{info['lods']} LOD · {info['materials']} 材质引用 · "
                     f"{info['bytes'] / 1024:.0f} KB")
        self._append("下一段：导出页的 OBJ 导出会自动用当前材质上材质；"
                     "命令行可用 python -m exporters.uemodel <file>.uemodel --materialize exports/")

    def _export_fmodel(self, *, choose: bool) -> None:
        """按 FModel 的目录结构导出：模型目录里放 .uemodel/.json/.obj，贴图进 Textures/。"""
        bundle = self.host_window.bundle
        if bundle is None:
            self._append("还没有加载模型，先在「模型库」里选一个资产。")
            return
        vpath = getattr(self.host_window, "current_vpath", "") or ""
        if not vpath:
            vpath = getattr(getattr(bundle, "mesh", None), "pak_path", "") or ""
        directory = None
        if choose:
            from app.fluent_api import QFileDialog

            directory = QFileDialog.getExistingDirectory(
                self, "选择导出根目录", os.path.abspath("exports"))
            if not directory:
                return
        else:
            directory = os.path.abspath("exports")
        try:
            from exporters import fmodel_layout

            info = fmodel_layout.export_tree(bundle, directory, vpath)
        except Exception as exc:                            # noqa: BLE001
            self._append(f"FModel 目录导出失败：{type(exc).__name__}: {exc}")
            return
        self._append(f"已按 FModel 结构写 {info['files']} 个文件 → {info['folder']}")
        self._append(f"  模型 .uemodel + 材质 .json + OBJ/MTL · {info['triangles']:,} tris · "
                     f"{info['materials']} 材质 · {info['textures']} 张贴图（同目录 Textures/）")

    def _export(self, *, choose: bool) -> None:
        bundle = self.host_window.bundle
        if bundle is None:
            self._append("还没有加载模型，先在「模型库」里选一个资产。")
            return
        lod_data = self.lod_combo.currentData()
        lod = None if lod_data in (None, -1) else int(lod_data)
        directory = None
        if choose:
            from app.fluent_api import QFileDialog
            directory = QFileDialog.getExistingDirectory(self, "选择 OBJ 输出目录",
                                                         os.path.abspath("exports"))
            if not directory:
                return
        t0 = time.time()
        try:
            info = self.host_window.export_obj(
                lod=lod,
                directory=directory,
                scale=float(self.scale_spin.value()),
                mtl=bool(self.mtl_switch.isChecked()),
                flip_uv=bool(self.flip_switch.isChecked()),
                axis=str(self.axis_combo.currentData()),
                merge_sections=bool(self.merge_switch.isChecked()),
            )
        except Exception as exc:                            # noqa: BLE001
            self._append(f"导出失败：{type(exc).__name__}: {exc}")
            return
        elapsed = time.time() - t0
        items = info if isinstance(info, list) else [info]
        for item in items:
            self._append(
                f"OK {os.path.basename(item.get('obj', '?'))}  v={item.get('v')} "
                f"vt={item.get('vt')} vn={item.get('vn')} f={item.get('f')} "
                f"材质={item.get('materials')} 贴图={item.get('textures')} "
                f"· {human_bytes(item.get('bytes', 0))}")
        self._append(f"完成 {len(items)} 个文件，用时 {elapsed:.2f}s → "
                     f"{os.path.dirname(items[0].get('obj', ''))}")

    def _append(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{stamp}] {text}")


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
class SettingsPage(QWidget):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.host_window = window
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("settingsBody")
        scroll.setWidget(body)
        outer.addWidget(scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)
        root.addWidget(TitleLabel("设置"))

        # 版本 / 数据目录 / 索引路径：别人报问题时让他把这张卡片读给你
        info_card = CardWidget(body)
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(6)
        info_layout.addWidget(StrongBodyLabel("版本与数据"))
        detail = QLabel("", info_card)
        detail.setWordWrap(True)
        detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        try:
            from core import indexdb
            from core import loader as _ld
            from core.version import stamp
            if indexdb.is_ready():
                idx = f"SQLite（{indexdb.count()} 条）\n{indexdb.db_path()}"
            else:
                idx = "还没建好（点下面「重建索引」，或等它自动扫描 pak）"
            detail.setText(f"版本：{stamp()}\n数据目录：{_ld.WORK}\n索引：{idx}")
        except Exception as exc:                             # noqa: BLE001
            detail.setText(f"读不到版本信息：{exc}")
        info_layout.addWidget(detail)
        root.addWidget(info_card)
        self._info_detail = detail          # 重建索引后要让这张卡片自己更新

        # appearance
        theme_card = CardWidget(body)
        theme_layout = QVBoxLayout(theme_card)
        theme_layout.setContentsMargins(14, 12, 14, 12)
        theme_layout.setSpacing(6)
        theme_layout.addWidget(StrongBodyLabel("外观"))
        theme_row = QHBoxLayout()
        theme_row.addWidget(BodyLabel("深色主题（Fluent 亚克力）"), 1)
        self.theme_switch = SwitchButton(theme_card)
        self.theme_switch.setChecked(isDarkTheme())
        self.theme_switch.checkedChanged.connect(self._set_theme)
        theme_row.addWidget(self.theme_switch)
        theme_layout.addLayout(theme_row)
        root.addWidget(theme_card)

        # materials
        mat_card = CardWidget(body)
        mat_layout = QVBoxLayout(mat_card)
        mat_layout.setContentsMargins(14, 12, 14, 12)
        mat_layout.setSpacing(6)
        mat_layout.addWidget(StrongBodyLabel("材质"))
        mat_row = QHBoxLayout()
        mat_row.addWidget(BodyLabel("贴图只在模型/材质自己的目录里找（FModel 语义）"), 1)
        self.strict_switch = SwitchButton(mat_card)
        from core import loader as _ldr

        self.strict_switch.setChecked(bool(getattr(_ldr, "STRICT_DIRS", True)))
        self.strict_switch.checkedChanged.connect(self._set_strict_dirs)
        mat_row.addWidget(self.strict_switch)
        mat_layout.addLayout(mat_row)
        mat_note = CaptionLabel(
            "开着的时候：模型目录 → `<模型>/Textures/`、GenTexDirHD 同名的镜像目录、"
            "皮肤目录（WeaponAppear/.../Texture）。都没有就不贴图（中性灰），"
            "不会拿别的部位的同名图顶上去。关掉它才会退回「全局按名字猜」，容易出现材质错位。")
        mat_note.setWordWrap(True)
        mat_layout.addWidget(mat_note)
        root.addWidget(mat_card)

        # cache
        cache_card = CardWidget(body)
        cache_layout = QVBoxLayout(cache_card)
        cache_layout.setContentsMargins(14, 12, 14, 12)
        cache_layout.setSpacing(6)
        cache_layout.addWidget(StrongBodyLabel("缓存"))
        self.cache_path = BodyLabel(str(getattr(window.cache, "root", "—")))
        self.cache_path.setWordWrap(True)
        cache_layout.addWidget(self.cache_path)
        self.cache_size = StrongBodyLabel("—")
        cache_layout.addWidget(self.cache_size)
        cache_note = CaptionLabel("缓存为会话缓存：退出程序（aboutToQuit / atexit）时整目录删除，"
                                  "启动时也会清掉超过 1 天的残留目录。")
        cache_note.setWordWrap(True)
        cache_layout.addWidget(cache_note)
        cache_buttons = QHBoxLayout()
        self.stats_button = PushButton("重新统计", cache_card)
        self.purge_button = PushButton(qicon("delete"), "立即清理缓存", cache_card)
        self.stats_button.clicked.connect(self.refresh_cache)
        self.purge_button.clicked.connect(self._purge)
        cache_buttons.addWidget(self.stats_button)
        cache_buttons.addWidget(self.purge_button)
        cache_buttons.addStretch(1)
        cache_layout.addLayout(cache_buttons)
        root.addWidget(cache_card)

        # 数据维护：别人最常见的两个问题就是「索引丢了」「设置乱了」，
        # 这里各给一个一键按钮，不用再去翻 %LOCALAPPDATA%
        maint_card = CardWidget(body)
        maint_layout = QVBoxLayout(maint_card)
        maint_layout.setContentsMargins(14, 12, 14, 12)
        maint_layout.setSpacing(6)
        maint_layout.addWidget(StrongBodyLabel("数据维护"))
        maint_note = CaptionLabel(
            "索引存在用户目录的 VertexViewer/index.db（SQLite 单文件），换机器/删掉了都不要紧。"
            "点「重建索引」会直接扫描游戏目录里的 .pak 重建它，大约 1 分钟，全程有进度。")
        maint_note.setWordWrap(True)
        maint_layout.addWidget(maint_note)
        self.maint_status = BodyLabel("")
        self.maint_status.setWordWrap(True)
        maint_layout.addWidget(self.maint_status)
        self.maint_bar = ProgressBar(maint_card)
        self.maint_bar.setRange(0, 1000)
        self.maint_bar.setValue(0)
        self.maint_bar.setVisible(False)
        maint_layout.addWidget(self.maint_bar)
        maint_buttons = QHBoxLayout()
        self.rebuild_button = PushButton(qicon("sync"), "重建索引", maint_card)
        self.reset_button = PushButton(qicon("delete"), "恢复出厂设置", maint_card)
        self.opendir_button = PushButton(qicon("folder"), "打开数据目录", maint_card)
        self.diag_button = PushButton(qicon("document"), "生成诊断报告", maint_card)
        self.wizard_button = PushButton(qicon("info"), "重看首次向导", maint_card)
        self.rebuild_button.clicked.connect(self._rebuild_index)
        self.reset_button.clicked.connect(self._factory_reset)
        self.opendir_button.clicked.connect(self._open_data_dir)
        self.diag_button.clicked.connect(self._diagnose)
        self.wizard_button.clicked.connect(self._replay_wizard)
        maint_buttons.addWidget(self.rebuild_button)
        maint_buttons.addWidget(self.reset_button)
        maint_buttons.addWidget(self.wizard_button)
        maint_buttons.addWidget(self.opendir_button)
        maint_buttons.addWidget(self.diag_button)
        maint_buttons.addStretch(1)
        maint_layout.addLayout(maint_buttons)
        root.addWidget(maint_card)

        # renderer / assets
        info_card = CardWidget(body)
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(6)
        info_layout.addWidget(StrongBodyLabel("渲染器与资产"))
        self.renderer_label = BodyLabel("—")
        self.renderer_label.setWordWrap(True)
        self.assets_label = BodyLabel("—")
        self.assets_label.setWordWrap(True)
        self.fluent_label = BodyLabel("—")
        self.fluent_label.setWordWrap(True)
        for widget in (self.renderer_label, self.assets_label, self.fluent_label):
            info_layout.addWidget(widget)
        root.addWidget(info_card)

        about = CaptionLabel("VertexViewer · PySide6 + FluentPy · 该游戏资产浏览器")
        about.setWordWrap(True)
        root.addWidget(about)
        self.credits_button = PushButton(qicon("info"), "感谢名单", body)
        self.credits_button.clicked.connect(self._show_credits)
        root.addWidget(self.credits_button, 0, Qt.AlignLeft)
        root.addStretch(1)
        self.refresh()

    def _show_credits(self) -> None:
        credits = getattr(self, "_credits", None)
        if credits is not None:
            credits.raise_()
            credits.activateWindow()
            return
        from app.credits import CreditsWindow
        credits = self._credits = CreditsWindow()

        def done():
            self._credits = None
            credits.deleteLater()

        credits.finished.connect(done)
        credits.start()

    def _set_strict_dirs(self, on: bool) -> None:
        from core import loader as _loader

        _loader.set_strict_dirs(on)
        try:
            cfg = _loader._read_config()
            cfg["strict_dirs"] = bool(on)
            _loader._write_config(cfg)
        except Exception:                                   # noqa: BLE001
            pass
        self.host_window.status("贴图查找：%s" % ("只按目录（FModel 语义）" if on else "允许全局按名字猜"))

    def _set_theme(self, dark: bool) -> None:
        try:
            setTheme(Theme.DARK if dark else Theme.LIGHT)
        except Exception as exc:                            # noqa: BLE001
            self.host_window.status(f"主题切换失败：{exc}")

    def _purge(self) -> None:
        try:
            self.host_window.cache.purge()
        except Exception as exc:                            # noqa: BLE001
            self.host_window.status(f"清理失败：{exc}")
        self._refresh_info_detail()
        self.refresh_cache()
        self.host_window.status("缓存已清理")

    # ---- 数据维护 -------------------------------------------------------- #
    def _maintenance(self):
        from core import maintenance
        return maintenance

    def _open_data_dir(self) -> None:
        path = self._maintenance().open_data_dir()
        try:
            os.startfile(path)                                   # noqa: S606
        except Exception as exc:                                 # noqa: BLE001
            self.host_window.status(f"打开目录失败：{exc}（{path}）")

    def _replay_wizard(self) -> None:
        """重看首次向导：直接开一个向导窗口，走完不动主界面（目录变了就刷索引）。"""
        from core import loader as L
        try:
            from app.wizard import WizardWindow
        except Exception as exc:                                 # noqa: BLE001
            self.maint_status.setText(f"打不开向导：{exc}")
            return
        wizard = WizardWindow()
        self._wizard = wizard                                    # 保活，别被 GC 掉
        before = getattr(L, "PAK_DIR", "")

        def _done(ok: bool) -> None:
            self._wizard = None
            if ok:
                self.maint_status.setText("向导已完成，设置已更新")
            else:
                self.maint_status.setText("已跳过向导")
            after = getattr(L, "PAK_DIR", "")
            if after and after != before:
                try:
                    win = self.window()
                    if hasattr(win, "browser"):
                        win.browser.reload_index()
                    if hasattr(win, "status"):
                        win.status(f"游戏目录已切换到：{after}")
                except Exception:                                # noqa: BLE001
                    pass
            try:
                wizard.deleteLater()
            except Exception:                                    # noqa: BLE001
                pass

        wizard.finished.connect(_done)
        wizard.start()

    def _diagnose(self) -> None:
        """生成诊断报告：写盘 + 弹窗预览 + 一键复制 / 打开所在目录。"""
        from core import diag
        try:
            path = diag.write_report()
        except Exception as exc:                                 # noqa: BLE001
            self.host_window.status(f"生成诊断报告失败：{exc}")
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = ""
        self.host_window.status(f"诊断报告已生成：{path}")
        box = QMessageBox(self)
        box.setWindowTitle("诊断报告")
        box.setText("报告已生成。一定一定把这个文件发送给开发者：3281644795\n"
                    "不然我只能帮你算一卦。\n\n" + path)
        box.setDetailedText(text)
        copy_btn = box.addButton("复制全文", QMessageBox.ActionRole)
        open_btn = box.addButton("打开所在目录", QMessageBox.ActionRole)
        box.addButton("关闭", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is copy_btn:
            QApplication.clipboard().setText(text)
            self.host_window.status("诊断报告已复制到剪贴板")
        elif box.clickedButton() is open_btn:
            try:
                os.startfile(os.path.dirname(path))              # noqa: S606
            except Exception as exc:                             # noqa: BLE001
                self.host_window.status(f"打开目录失败：{exc}")

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.rebuild_button.setEnabled(not busy)
        self.reset_button.setEnabled(not busy)
        self.maint_bar.setVisible(busy)
        if busy:
            self.maint_bar.setValue(0)
        if text:
            self.maint_status.setText(text)

    def _rebuild_index(self) -> None:
        """后台线程重建索引，进度条读 loader.progress()（真进度，不是转圈）。"""
        import threading

        from core import loader as _ld

        if getattr(self, "_rebuilding", False):
            return
        self._rebuilding = True
        self._set_busy(True, "正在扫描游戏 pak…（约 40 秒，别关窗口）")

        def _work():
            from core import maintenance
            ok, text = maintenance.rebuild(write_json=True)
            self._rebuild_result = (ok, text)

        threading.Thread(target=_work, daemon=True, name="dfv-rebuild").start()

        from app.fluent_api import QTimer

        timer = QTimer(self)
        timer.setInterval(160)

        def _poll():
            info = _ld.progress() or {}
            total = int(info.get("total") or 0)
            done = int(info.get("done") or 0)
            if total > 0:
                self.maint_bar.setValue(int(1000 * done / total))
                self.maint_status.setText(
                    f"{info.get('stage') or '正在重建索引'} · {info.get('detail') or ''}")
            if hasattr(self, "_rebuild_result"):
                timer.stop()
                self._rebuilding = False
                ok, text = self._rebuild_result
                del self._rebuild_result
                self._set_busy(False, ("✅ " if ok else "❌ ") + text)
                if ok:
                    self.host_window.status("索引已重建，重启后从新索引秒开")
                    try:
                        self.host_window.browser.reload_index()
                    except Exception:                        # noqa: BLE001
                        pass
                else:
                    self.host_window.status("重建失败，详情见上方说明")

        timer.timeout.connect(_poll)
        timer.start()
        self._rebuild_timer = timer

    def _factory_reset(self) -> None:
        from app.fluent_api import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("恢复出厂设置")
        box.setText("会清空这些内容，然后需要重启软件：\n"
                    "· 会话缓存、导出的 .uemodel\n"
                    "· 自定义图标表与图标文件\n"
                    "· 游戏目录等配置项\n"
                    "· 启动日志\n"
                    "（已重建好的索引默认保留；勾上「连索引一起删」才会删）")
        box.setIcon(QMessageBox.Warning)
        keep = box.addButton("恢复出厂设置", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(box.buttons()[-1])
        box.exec()
        if box.clickedButton() is not keep:
            return
        ok, text = self._maintenance().factory_reset(keep_index=True)
        self.maint_status.setText(("✅ " if ok else "⚠️ ") + text + "\n\n请关闭软件后重新打开。")
        self.host_window.status("已恢复出厂设置，重启后生效")
        self.refresh_cache()

    def showEvent(self, event) -> None:                 # noqa: N802
        super().showEvent(event)
        self._refresh_info_detail()

    def _refresh_info_detail(self) -> None:
        """索引状态会变（重建完就从「还没建好」变成 SQLite），卡片要跟着刷新。"""
        detail = getattr(self, "_info_detail", None)
        if detail is None:
            return
        try:
            from core import indexdb
            from core import loader as _ld
            from core.version import stamp
            if indexdb.is_ready():
                idx = "SQLite（%d 条）\n%s" % (indexdb.count(), indexdb.db_path())
            else:
                idx = "还没建好（点下面「重建索引」，或等它自动扫描 pak）"
            detail.setText("版本：%s\n数据目录：%s\n索引：%s"
                           % (stamp(), _ld.WORK, idx))
        except Exception as exc:                             # noqa: BLE001
            detail.setText(f"读不到版本信息：{exc}")

    def refresh_cache(self) -> None:
        cache = self.host_window.cache
        try:
            stats = cache.stats() if hasattr(cache, "stats") else {}
            size = cache.size_bytes()
        except Exception:                                   # noqa: BLE001
            stats, size = {}, 0
        files = stats.get("files") if isinstance(stats, dict) else None
        self.cache_size.setText(f"当前占用 {human_bytes(size)}"
                                + (f" · {files} 个文件" if files else ""))
        self.cache_path.setText(str(getattr(cache, "root", "—")))

    def refresh(self) -> None:
        vp = self.host_window.viewport
        self.renderer_label.setText(
            f"渲染后端：{vp.backend} · {vp.backend_detail}")
        browser = self.host_window.browser
        self.assets_label.setText(
            f"资产索引：{browser.count} 个模型"
            + (f" · 索引错误 {browser._error}" if getattr(browser, "_error", "") else ""))
        try:
            from app import fluent_api
            info = fluent_api.describe()
            level = info.get("level")
            kind = "首选" if level == 1 else "降级"
            self.fluent_label.setText(
                f"Fluent 组件：{info.get('level_name')}（{kind}）· {info.get('source')}")
        except Exception:                                   # noqa: BLE001
            self.fluent_label.setText("Fluent 组件：—")
        self.refresh_cache()

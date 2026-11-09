# NOTES-18：开屏加载窗改用 FluentPy 的 FluentWindow 重写

## 18.1 为什么重写
原来的开屏是一个自绘 `QWidget`（圆角方板 + 手绘进度条 + 手绘转圈 + ctypes 调 DWM 的
acrylic）。功能没问题，但和主窗口是两套外观：主窗口是 FluentPy 的 `FluentWindow`
（标题栏、Mica、卡片、按钮全是库画的），开屏却是自己画的，交接那一下能看出来「换了个窗口」。

现在开屏本身就是一个 `FluentWindow`：真标题栏、库的 `ProgressBar`、库的标签控件，
和主窗口同一套外观，长满瞬间主窗口在同一矩形接手，几乎看不出是换了窗口。

## 18.2 实现（`app/splash.py`）
- `class SplashWindow(FluentWindow)`，构造后：
  - `setWindowFlag(Qt.FramelessWindowHint / WindowStaysOnTopHint)`；
  - `set_title_bar_enabled(True)`，再把标题栏里的前进/后退按钮隐藏、
    `set_bar_height(40)`、`set_caption_buttons_visible(False, False, True)`；
  - `set_backdrop_enabled(False)` + `setStyleSheet("QMainWindow{background:#1b1c20;}")`
    —— 加载窗尺寸一直在变，DWM backdrop 在这条路径上会在隐藏时对已释放的
    central widget 回调；
  - 内容（logo / 标题 / 副标题 / 状态 / 进度条 / 落款）塞进 `content_layout`。
- 尺寸：`SMALL_W=420 / SMALL_H=300`，屏幕可用区居中。
- 进度：`set_fraction(v)` 只记目标值，16ms 定时器用 `shown += (goal-shown)*0.14`
  逼近平滑推进；`set_fraction(None)` 时以 0.004/帧 爬到 0.9（未知总量的「一直在干活」）。
- 展开：`expand_to(target, done, duration=760)` 用 `QPropertyAnimation(self, b"geometry")`
  （OutCubic）把窗口从小矩形长到目标矩形；同时 120ms 内把内容透明度降到 0；
  到点后先 `done()`（主窗口在同一矩形 `setGeometry` 后 `show()`），再立刻 `hide()` 自己。
- 只隐藏不销毁：FluentPy 的 `theme.subscribe` 挂在窗口上，销毁后会对着已释放的 C++ 对象
  回调并抛 `RuntimeError: Internal C++ object already deleted`。`app/__main__.py`
  里用 `_splash_build["splash"]` 一直持有引用。

## 18.3 踩过的两个坑
1. **`content_layout` 是属性不是方法**。写成 `self.content_layout().addWidget(...)` 会抛
   `TypeError: 'PySide6.QtWidgets.QVBoxLayout' object is not callable`，于是落进
   `except` 里的 `setCentralWidget(self._card)` —— 而 `setCentralWidget` 会删掉
   FluentPy 自己的 `_root`，之后主题刷新调用 `_apply_backdrop/_apply_theme` 就对着
   已释放的 widget 报错（表现为启动到 11 秒左右连续弹「崩溃报告」）。
   正解：只用 `self.content_layout.addWidget(...)`，绝不替换 central widget。
2. 窗口标志 / backdrop 反复开关会让 FluentPy 的 `_apply_theme` 拿到失效的 `_root`，
   所以加载窗干脆不开 backdrop，用纯色底。

## 18.4 验收
- 源码运行：`[splash] enter` → `expand_to enter (750,366,420,300) -> (209,45,1500,940)`
  → `expanded`，无异常、无崩溃报告。
- 帧序列实测（16ms 采样 63 帧）：`420×300`（t=0.015）→ `1167×760`（t=0.515）
  → `1200×780`（t=0.953），宽度单调递增 = 真的在逐帧长大。
- 打包版干净 profile 首启：小窗显示「正在从游戏 paks 重建索引 · 3/344 个 pak · 已收 14374 个资产」，
  重建完成后主窗口在同一矩形接手（`work/zr_1.png`、`work/pk_win2.png`），日志里 0 个崩溃文件。
- 版本 `1.0+2026-10-28.0100`；zip `VertexViewer-1.0-2026-10-28.zip` 78,530,155 字节，
  sha256 `d51f98cd8aa07612187dbe71852d7e1c7edf3f394a735154e2ac688e843c7b90`。

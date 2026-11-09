# NOTES-22：开屏细节打磨（标题字号 / 转圈 / 进度条）

用户 m07663：「软件标题栏文字大一点，现在的进度条有点太简陋了，软件打开中间那个加载小圈圈改成好看的」。

## 22.1 标题栏文字放大
- FluentPy 的标题是标题栏里的 `_WindowTitle(QLabel)`，跟着 `theme.tokens.font_size` 走，
  在 1500 宽的窗口里偏小。
- `app/main_window.py::_tidy_title_bar()` 里补一段：`bar.findChild(_WindowTitle)` 拿到标签，
  把字号放大到原来的 **1.32 倍**（下限 14px）并设 `QFont.Weight.DemiBold`。
- 实测截图 `work/ui_main.png`：`VertexViewer · 模型浏览器 · 1.0+2026-10-30.1000`
  明显比之前大、且和主体同色。

## 22.2 中间那个加载小圈圈
- `app/splash.py::_Card.paintEvent` 新增**贴底环 + 旋转亮弧**的转圈：
  半径 `max(11, h*0.036)`、圆心在 `(w*0.5, h*0.665)`；
  底环 `QColor(255,255,255,62)`、线宽 2.8；亮弧用 `QConicalGradient`
  （起始角 `-90° - phase*360*3`，色标 `150,226,255,245 → 96,196,255,120 → 透明`），
  画 300°，`Qt.RoundCap` 圆头。
- 相位还是复用 `_phase`（每 16ms 推进），所以转圈与滚动条同频但视觉上独立。

## 22.3 进度条
- 原来那条是贴边 3px 硬边矩形 + 一段 ping-pong 亮块，看着简陋。
- 现在：`bar_h = max(5, BAR_H+2)`，左右各留 `pad*0.5` 的边距，
  轨道 `QColor(255,255,255,46)` + `drawRoundedRect(..., bar_h/2)` 圆角；
  亮块 `seg = max(56, w*0.34)`，五段渐变
  `0 → (126,219,255,190) → (196,242,255,245) → (126,219,255,190) → 透明`，
  同样圆角，来回跑。

## 22.4 验收
- 离屏：`work/ui_30.png`、`work/uk_10.png`、`work/uk_42.png`（转圈 + 圆角条）。
- 打包版（`1.0+2026-10-30.1000`，干净 profile 首启）：`work/ui_pkg1.png`、
  `work/ui_pkg2.png`（转圈在标题下方居中、圆角滚动条贴底、状态文字带真实进度）。
- 主窗口：`work/ui_main.png`（标题字号变大、与主体同色）。

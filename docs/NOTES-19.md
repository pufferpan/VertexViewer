# NOTES-19：开屏版式照 Office 启动卡重排

## 19.1 需求
用户给了 Word 2019 的启动图（553×342 蓝卡），要求：
- 版式照图：左上角品牌、正中间大字软件名、左下角「正在启动…」；
- 左上角文字改 `PufferPan`，中间文字改软件名；
- 过渡（小卡 → 主窗口）保留，且「位置要一样」。

## 19.2 版式（`app/splash.py` 里的 `_Card`，全自绘）
- 尺寸 560×346（照原图 553×342 的横宽比），屏幕可用区正中。
- 底色：竖直渐变 `#1f4e9c → #173f80`（Office 那套微软蓝）；FluentPy 标题栏关掉
  （`set_title_bar_enabled(False)`），整块由卡片画，右上角自己画 `✕` 关闭。
- 左上角：透明 logo（20px）+ `PufferPan`（DemiBold）。
- 正中：软件名 `VertexViewer`（约 0.17 倍窗高、Light 字重，宽度居中）；
  其下一行小字副标题「模型浏览器」。
- 左下角：状态文字。默认「正在启动…」，随后换成真实进度
  （「正在装载资产索引… 320000/937088」/「正在从游戏 paks 重建索引 · 10/344 个 pak · 已收 17077 个资产」）。
- 最底部：3px 细进度条贴边（原图没有，这里要显示真实加载量）。

## 19.3 过渡
- `expand_to(target)` 同时跑两条动画：`geometry`（560×346 → 主窗口矩形，OutCubic 760ms）
  和卡片属性 `bgMix` 0→1（蓝卡渐变到主窗口深色 `#1b1c20`）。
- 卡片内容在 120ms 内淡掉，所以长个子的过程是一块**干净的色板**在变大，
  长满瞬间主窗口在同一矩形接手，不会「蓝一下再变黑」。
- 实测（16ms 采样）：`560×346`(t=0) → `1033×671`(t=0.30) → `1200×780`(t=0.75)，
  宽度单调递增；`bgMix` 0 → 0.19 → 1.0，与几何同步。

## 19.4 透明 logo
原 `assets/logo.png` 是**不透明黑底**（alpha 全 255、左上角纯黑），直接画在蓝卡上是
一块黑方块。用 Pillow 生成 `assets/logo_nobg.png`：`alpha = max(R,G,B)*1.35`，
近黑像素透明，颜色保留。`VertexViewer.spec` 把这张也打进 `assets/`。

## 19.5 验收
- 打包版干净 profile 首启：`work/wd_live1.png`、`work/wd_live2.png`
  （蓝卡、PufferPan、VertexViewer、真实重建进度 4/344 → 10/344）。
- 重建完成后主窗口接手（`work/wd_done.png`，1516×979，教程页），
  `logs/` 里崩溃文件 0 个。
- 版本 `1.0+2026-10-28.0230`。

## 19.6 逐字出现 + 微软四点（用户追问）
- 软件名不再整段画，改成**逐字**：`_Card.reveal`（Qt `Property(float)`）由
  `_play_enter()` 用 `QPropertyAnimation` 在 `220 + 字数×95ms` 内推 0→1；
  `paintEvent` 里每个字的本地进度 `t = clamp(reveal*(n+1) - i)`，
  位移 `(1-easeOutCubic(t))*30px`（从右往左滑进来）、透明度 `246*easeOutCubic(t)`
  （透明 → 不透明）。整串的起始 x 仍按总字宽居中，所以滑入过程不会整体偏移。
- 底部那条细进度条删掉，换成**微软式四个点**：`_on_tick` 每 16ms 把
  `_Card._phase` 推 `0.016/1.15`（1.15 秒一圈），`paintEvent` 用
  `pos = phase*4`、`near = 1 - min(1, |pos-(k+0.5)|/1.7)` 算每个点的半径
  `2.1+1.5*near` 与透明度 `70+175*near` —— 看起来就是一个亮点在四点间来回跑。
  四个点跟在状态文字后面 14px；文字太长放不下时自动贴到右边距。
- 真实进度还在：状态文字里仍带「320000/937088」「4/344 个 pak · 已收 14729 个资产」，
  只是不再画进度条。

## 19.7 整串渐变擦除 + 随包粗体（用户 m06574）

- 标题不再逐字：整串一起从右边滑进来（`off = (1-e)*46`，OutCubic），
  同时用**带 alpha 的渐变画笔填字形**做「从右往左擦除」：
  `plan = min(1, reveal/0.85)`、`front = 1 - plan*1.30`、
  `lo = clamp(front-0.02)`、`hi = max(lo, clamp(front+0.22))`，
  stops `0 → alpha 0`、`lo → alpha 0`、`hi → 246`、`1 → 246`；
  `reveal >= 0.985` 直接换实心画笔（否则左边永远半透明）。
- 字重改 Bold（`_title_font(px, bold=True)` → `QFont.Weight.Bold`），
  品牌字 `PufferPan` 与标题共用这套字体。
- 字体随包：`assets/fonts/VertexViewer-Bold.ttf`（63,692 字节，家族名 `VertexViewer Title`），
  由 `NotoSansSC-VF.ttf` 经 fonttools `instantiateVariableFont({"wght":700})`
  + `subset`（只留拉丁/数字/常用标点，中文仍走系统字体）生成；
  `splash.py::_title_family()` 用 `QFontDatabase.addApplicationFont` 注册，
  `VertexViewer.spec` 把它打进 `_internal/assets/fonts/`。
- 打包版实测日志：`[splash] title font -> VertexViewer Title (VertexViewer-Bold.ttf)`（`VERTEXVIEWER_SPLASH_DEBUG=1`）。
- 验收帧：`work/bp_0..3.png`（reveal 0.15 / 0.45 / 0.75 / 1.0 的擦除过程）、
  `work/bf_1.png`（打包版实拍，粗体标题 + 四点）、`work/cv_2_c.png`（源码运行）。

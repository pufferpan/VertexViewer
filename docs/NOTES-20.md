# NOTES-20：开屏按「LOGO2 + MiSans + 底部滚动条」收尾

## 20.1 这轮改了什么
- **标题栏**：`SplashWindow.__init__` 里窗口标题从 `f"{title} · {subtitle}"` 改成只传
  `title`；`FramelessWindowHint` 之外再补三手——`set_title_bar_enabled(False)`、
  `setMenuWidget(None)`、命中 `self._title_bar` 时 `setVisible(False)`；`showEvent`
  里再撤一次（有的窗口管理器 / 库版本会在 `show()` 时把标题栏挂回去）。
  FluentPy 0.7.3 里 `set_bar_height`、`set_caption_buttons_visible` **并不存在**，
  以前写的那两行只会被 `except` 吞掉，没有任何效果。
- **左上角换图**：用用户给的 `LOGO2.png`（1739×324 RGBA）。原图是**深色字形**
  （不透明像素 RGB 均值 ≈ `[42,39,37]`）+ 透明底，画在蓝色卡片上等于看不见，
  所以生成两份：`assets/logo_wordmark.png`（原样）与
  `assets/logo_wordmark_light.png`（保留 alpha、RGB 刷白）；`logo_path()` 优先取
  light 版。原来 «logo 图 + `PufferPan` 文字» 里的文字整段删掉，只画图，高度
  `LOGO_H=26`。
- **底部滚动条**：删掉「微软四点」，也删掉「已知进度填充」（两者叠在一起语义冲突）。
  现在是一条贴底 3px 的槽 + 一段 ping-pong 跑的亮块：
  `seg = max(36, w*0.30)`、`t=(phase%1)*2`、`u = t<=1 ? t : 2-t`、`sx = u*(w-seg)`，
  三段渐变 `(76,194,255,0) → (120,215,255,210) → (76,194,255,0)`。真实进度数字仍在
  状态文字里（「正在从游戏 paks 重建索引 · 4/344 个 pak · 已收 14729 个资产」）。
- **MiSans + 非线性滑入**：fontTools 把 `MiSans-Bold.ttf`（8MB）子集化成
  `assets/fonts/VertexViewer-MiSans-Bold.ttf`（**43,084 字节**），name 表把家族改成
  `VertexViewer MiSans`——不改名的话系统里装的 MiSans 会抢先、随包这份等于白带。
  `title_font_path()` 优先 MiSans、回退旧 Noto 子集；滑入改成
  `e = 1-(1-reveal)**3.4`、`off = (1-e)*(w*0.34)`、`opacity = 0.25+0.75*e`，
  即**从右侧 0.34 倍窗宽处非线性地滑到正中**，同时保留由右向左的渐变擦除。
  时间轴上仍是线性推进（缓动放在 `paintEvent` 里，避免双重缓动变成「跳」）。
- **偶发黑屏**：
  1. `QGraphicsOpacityEffect` 初值由 `0.0` 改成 `1.0`（原来淡入动画一旦没跑，
     卡片就永远全透明 = 黑屏）；
  2. 新增 `_force_timer`（600ms 单发）→ `_force_visible()`：把 opacity 强推回 1.0，
     若 `reveal < 0.05` 就一并设成 1.0（标题也就直接出来，不会空着）；
  3. `showEvent` 里重新起一次这个兜底计时。

## 20.2 打包
- `VertexViewer.spec` 新增 `MISANS_FONT` 与 `logo_wordmark.png` / `logo_wordmark_light.png`
  三条 datas（都落 `_internal/assets`、`_internal/assets/fonts`）。
- 版本 `1.0+2026-10-30.0730`。
- 打包版启动日志实测：`[splash] title font -> VertexViewer MiSans (VertexViewer-MiSans-Bold.ttf)`
  ⇒ 随包字体真的被注册并用于标题。

## 20.3 验收
- `work/ms_live1.png`（2.6s，标题擦到右端 "…er"）、`work/ms_live2.png`（标题已完整、
  状态「… 4/344 个 pak · 已收 14729 个资产」、底部亮块在跑）。
- `work/ms_run2.png`：**第二次启动**同样正常显示，不再黑屏。
- `work/ms_done.png`：重建索引完成后主窗口接手（1516×979），`logs/` 里崩溃文件 0 个。

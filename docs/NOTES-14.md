# 14 · 启动弹出动画 / logo / 首次教程

用户 m04378 的要求：
> 教程是在首次开启的时候显示，把正式使用的时候的动画去了，然后把加载页面的弹出也做上动画，
> logo 在 `C:\Users\32816\Desktop\新建文件夹\1.png`，然后把加载动画弹出文字和进度条都做上拉出动画

## 14.1 logo

- 素材复制到 `assets/logo.png`（433×395 RGBA，绿色三角度量 logo）。
- `app/splash.py::logo_path()` 依次找 `_MEIPASS/assets/logo.png`（打包版）→
  `ROOT/assets/logo.png`（源码运行），找不到就不画，绝不报错。
- `VertexViewer.spec` 里 `datas.append((LOGO, "assets"))`，打包后在 `_internal/assets/logo.png`。

## 14.2 启动卡片的弹出动画（两段）

新增两个 `Property(float)`：

| 属性 | 范围/时长 | 效果 |
| --- | --- | --- |
| `appear` | 0→1，220ms，OutCubic | 卡片按 `0.86 → 1.0` 缩放，整体透明度跟着涨（`p.setOpacity(content * appear)`）；`_plate_rect()` 在展开前额外乘这个缩放系数 |
| `textin` | 0→1，260ms，OutCubic，延后 80ms | 状态文字从下方 10px 滑上来（透明度 × textin）；进度条**轨道宽度按 textin 从 0 拉到满宽**，填充跟着长——就是「拉出」的手感 |

`center_on_screen()` 里先把 `_appear/_textin` 置 0 再 `show()`，然后 `_play_enter()`
起两个动画（pop 立刻开始，text 用 `QTimer.singleShot(80, text.start)` 延后）。
`VERTEXVIEWER_SPLASH_DEBUG=1` 会多打一行 `enter`。

## 14.3 首次启动才放教程动画

- `app/tutorial.py::TutorialPage` 不再在 `showEvent` 里自动播；改为
  `play_intro()`（内部就是 `replay()`），只有 `_pending_intro` 为真时 `showEvent` 才自动播。
- `app/main_window.py::_maybe_first_run_tutorial()`（索引就绪后 260ms 触发）：
  读 `%LOCALAPPDATA%\VertexViewer\config.json`，没有 `tutorial_seen` 就
  `switchTo(tutorial_page)` + `play_intro()`，然后把 `tutorial_seen=True` 写回配置。
  于是：首次启动 → 停在教程并放动画；之后每次 → 正常进模型库，切到教程也是静态的。
- 调试开关：`VERTEXVIEWER_FORCE_TUTORIAL=1` 可以强制每��都当首次启动。

## 14.4 验收

- 离屏抓帧：`work/en_1.png`（appear≈0.3，暗、进度条短）→ `en_2.png`（条更长）→
  `en_4.png`（logo + 标题 + 状态 + 满宽进度条 + 落款）。
- 打包版真机：`work/ey_1_c.png`（启动 1.15s：卡片略小、进度条才 1/5 宽、`20000/937088`）
  → `work/ez_3_c.png`（`900000/937088`，条满）。
- 首次启动：`work/first_run.png`（停在教程页，`config.json` = `{"tutorial_seen": true}`）；
  第二次启动 `work/second_run.png`（当前页 `libraryPage`，没有动画）。
- 版本 `1.0+2026-10-26.1900`。

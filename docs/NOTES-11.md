# 11 · 开屏动画（毛玻璃 / 转圈 / 居中展开 / 落款）

## 11.1 用户反馈

> 把开屏动画优化，我看到在加载完后加载动画会跑左上角，把它修复，然后加载动画得有个转动的圈，
> 然后把加载搞成毛玻璃，加上软件制作：河豚潘 PufferPan

## 11.2 「跑左上角」的真正原因

旧版 `_plate_rect()` 把**位置也一起插值**了：

```python
x = int(_lerp(self._small_rect.x(), 0, t))   # 450 → 0
y = int(_lerp(self._small_rect.y(), 0, t))   # 306 → 0
w = int(_lerp(self._small_rect.width(), full.width(), t))
h = int(_lerp(self._small_rect.height(), full.height(), t))
```

小框在屏幕正中（窗口 1200×780 时 x=450、y=306），而插值终点是 `(0, 0)`。
所以底板一边变大一边往左上角挪 —— 视觉上就是「加载完，动画跑左上角去了」。

修法：**只插值宽高，位置每帧按中心算**：

```python
w = round(lerp(SMALL_W, full_w, t))
h = round(lerp(SMALL_H, full_h, t))
x = (full_w - w) // 2
y = (full_h - h) // 2
```

实测（窗口 1200×780）：

| grow | 底板矩形 | 中心 |
| --- | --- | --- |
| 0.00 | (450, 306, 300, 168) | (599, 389) |
| 0.25 | (337, 229, 525, 321) | (599, 389) |
| 0.50 | (225, 153, 750, 474) | (599, 389) |
| 0.75 | (112, 76, 975, 627) | (599, 389) |
| 1.00 | (0, 0, 1200, 780) | (599, 389) |

中心恒为 (599,389)，再也没有漂移。文字块也一样：`box.moveCenter(plate.center())`，
所以放大过程中是「整张贴片在长大」，不是「大窗口角落飘一行小字」。

## 11.3 转动的圈

`SplashWindow._draw_spinner()`：先画一圈 `rgba(255,255,255,34)` 的底环，
再用 `drawArc` 画 110° 的蓝色弧 `rgba(0,140,235,255)`，起始角随 `_phase` 递减：

```python
start = int((90 - self._phase * 360) * 16)   # Qt 角度单位 1/16°
p.drawArc(rect, start, int(-110 * 16))
```

`_phase` 由 16ms 定时器推进（60fps，转起来不抖），一圈约 0.75 秒。
圈画在状态文字左边（半径 9，中心 `box.left()+pad+9`），旁边是「正在装载资产索引 ·
340000/937088 个资产」。

## 11.4 毛玻璃

`_enable_acrylic(widget)`（`ctypes`，只调 Win32 API，不引依赖）：

1. `user32.SetWindowCompositionAttribute(hwnd, {Attr=19, AccentState=4,
   AccentFlags=2, GradientColor=0xE0202327})` —— 4 = `ACCENT_ENABLE_ACRYLICBLURBEHIND`；
2. 再试 `dwmapi.DwmSetWindowAttribute(hwnd, 38, 3)`（Win11 22H2+ 的
   `DWMWA_SYSTEMBACKDROP_TYPE = DWMSBT_TRANSIENTWINDOW`）；
3. 任一步失败就返回 `False`，底板退回实心渐变 `(30,31,34,252)→(18,19,22,252)`。

开了毛玻璃时底板用半透明 `rgba(28,30,34,176)` + 顶部一圈很淡的白色径向高光，
背后的游戏/桌面透出来是模糊的。`center_on_screen()` 和 `expand_to()` 各调用一次
（窗口 hwnd 在第一次 show 之后才稳定）。

## 11.5 落款

底板内右下角：`软件制作：河豚潘 PufferPan`，10px、`rgba(255,255,255,96)`，
跟着底板一起放大、一起淡出。

## 11.6 尺寸与节奏微调

- 小框从 300×156 改成 **300×168**（多出来的高度给转圈+落款，不再挤）；
- 转圈定时器 33ms → **16ms**；
- 展开仍 `OutQuint / 660ms`、淡出 `130ms`（交叉溶解，主窗口先显示在底下）。

## 11.7 验收

- 离屏：`gl_0.png`（小框，圈+进度条+落款都在）、`gl_14/gl_24.png`（放大中，底板居中）。
- 真机（Acrylic 生效）：`work/ng_1_c.png`、`work/ng_2_c.png`
  —— 卡片半透明、背后游戏画面被模糊、进度 `320000→620000/937088` 递增、卡片始终居中。
- 打包版：标题栏 `1.0+2026-10-26.1200`。

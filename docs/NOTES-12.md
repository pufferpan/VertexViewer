# 12 · 「展开动画看不到了」的修复记录

## 12.1 现象

上一版（毛玻璃 + 转圈）交付后，用户反馈：小卡片停在那儿，然后主窗口**直接出现**，
中间的放大过程一点都看不见。

## 12.2 三个叠在一起的原因

### ① 毛玻璃把「整屏」提前铺满了（主因）

`SetWindowCompositionAttribute(AccentState=4)` 的 acrylic 是把**整个窗口矩形**
做模糊背板，而不是只模糊我们画出来的那块底板。
展开时 `setGeometry(target)` 一执行，窗口就是 1516×979 —— 屏幕上立刻出现一整块
磨砂板，我们的底板在里面从 300×168 长到满，肉眼根本分辨不出来。

修：`expand_to()` 里先 `_disable_acrylic(self)`（`AccentState=0`）再改窗口尺寸，
展开阶段用不透明纯色底板（`QColor(23,24,28,252)`），只有小卡片阶段才开玻璃。

### ② 主窗口的「建卡片数据」把事件循环卡了 1.4 秒

主窗口一构造完，浏览器那边排队等执行的 `_on_index`（给 9397 个资产建卡片数据 + 排序）
立刻占用 GUI 线程，实测 **1.44 秒**。这段时间动画定时器完全被饿死：

```
7.609 beat   ← 心跳正常
9.047 beat   ← 中间 1.44 秒一个字都没跑
9.328 tick   ← 动画才真正开始
```

修：`app/__main__.py::_open()` 里在建完窗之后、开始展开之前，先把这段活干完
（`processEvents` 轮询 `browser.is_ready`，界面上写「正在整理模型库…」，最多等 8 秒）。
改完 `expand_to enter` → `expanded` 只隔 **672ms**。

### ③ 每帧成本太高（50ms/帧）

原来是「窗口先铺满、在里面画一块从小到大的板子」：每帧都要把 1516×979 的整块
layered surface 推给 DWM，还叠着渐变 + 径向光 + 抗锯齿，实测 50ms/帧，
660ms 的动画被拖成 2 秒。

修：
- **窗口本身就是底板**：展开动画改成动画窗口矩形（自定义属性 `expandT`），
  每帧只推屏幕上真实占用的面积，实测 **15.6ms/帧**；
- 展开阶段别再画渐变/径向光/抗锯齿，只做纯色填充 + 1px 边框；
- 缓动 `OutQuint → OutCubic`（OutQuint 前 1/5 就走完 80% 距离，看着像跳）、
  时长 660 → **760ms**。

## 12.3 现在的时序（真机实测）

| 时刻 | 底板尺寸 | 说明 |
| --- | --- | --- |
| 62ms | 570×348 | 刚起动画，卡片略大，文字还在 |
| 187ms | 1000×635 | 明显长大一圈，文字淡出中 |
| 625ms | 1508×974 | 基本满屏，随后 130ms 交叉淡出到主窗口 |

`expand_to enter` → `expanded` 间隔 **672~765ms**，与设定一致；
窗口中心全程不动（`x,y` 由中心反算）。

## 12.4 验证工具

- `tools/probe_splash.py [秒数]`：monkeypatch `paintEvent`/`expand_to`/`center_on_screen`，
  记录 `(t, 事件, grow, 窗口矩形)` 到 `work/splash_probe.txt`，含 50ms 心跳，
  能一眼看出「事件循环哪儿被卡了」。
- `tools/probe_expand_shots.py <前缀>`：在真机启动流程里按 55ms 抓整屏，
  验证「肉眼看到的」展开过程。
- `tools/shot_expand.py <前缀>`：单独起一个 SplashWindow，按 90/220/380/560ms
  抓窗口自身，量尺寸变化（`(582,356) → (1050,668) → (1343,863)`）。
- `tools/bench_splash.py`：对比「有/无毛玻璃」下的 show / accent 切换 / 首次改尺寸耗时。

## 12.5 顺手修掉的小东西

- `_acrylic_state(widget, state, tint)` 统一入口，`_enable_acrylic` / `_disable_acrylic`
  都走它；
- `VERTEXVIEWER_SPLASH_DEBUG=1` 时打印 `expand_to enter / acrylic off / group.start / expanded`
  时间戳，方便以后再查这类「动画没了」的问题。

# 9. 加载界面与真实进度（2026-10-26）

## 9.1 需求
用户：做一个加载界面，屏幕中间一小块；加载完由小块展开成软件大小；进度必须是真实的。

## 9.2 卡片（app/splash.py）
`SplashWindow`：`FramelessWindowHint|Tool|WindowStaysOnTopHint` + `WA_TranslucentBackground`，
**方形、无圆角**（用户要求），渐变底 `(30,31,34,252)` → `(18,19,22,252)`、1px 白 10% 细边框。

### 动画做法：窗口不动，只重绘
第一版是给 `geometry` 做 `QPropertyAnimation`（真的在移动/改变窗口尺寸），
在 Windows 上每帧改窗口矩形会走合成器重新布局，看起来会一顿一顿、边缘还抖动。

现在改成：`expand_to()` 一开始就 `setGeometry(target)` 把窗口铺到目标矩形（此时底板只画在
中间 300×156），真正动的是 `grow` 属性 0 → 1，`paintEvent` 按 `grow` 插值底板矩形
（`_plate_rect()`：小框 → 整个窗口）。整个动画只重绘、不动窗口，帧率稳定。

曲线与时长：
- `grow`：`OutQuint`，660ms（前半段快、后半段收得慢，像"长大"而不是"弹出去"）
- `content`（文字/进度条）：0 → 10% 保持 1.0，28% 淡到 0（底板一放大就先把文字淡掉）
- 收尾：底板铺满后先 `done()` 把主窗口显示在**底板底下**，再对 `windowOpacity`
  做 1 → 0 的 130ms 淡出 —— 两边同一矩形，等于交叉溶解，不会出现"黑一下再出窗口"
- 「选游戏目录」对话框延后 220ms 再弹，免得盖住过渡动画

## 9.3 真实进度（core/loader.py）
旧路径 `fileindex.json.gz` → `json.load` 是一次性 C 解析，中间没有任何进度，
进度条只能假装在跑。改成流式：

- `tools/make_index_tsv.py`：`fileindex.json.gz` → `work/index.tsv.gz`
  （首行 `#VERTEXVIEWER-INDEX` + TAB + `1` + TAB + 条目数，之后每行 `路径` TAB `pak` TAB `偏移`）。
  937088 条 / 8.5MB，生成耗时 5.3s。
- `core/loader.py`：
  - `PROGRESS = {stage, done, total, detail}` + `_set_progress()` + `progress()`（带锁）
  - `_index_tsv_path()`：`WORK/index.tsv.gz` > `BUNDLE/data/index.tsv.gz` > `BUNDLE/work/index.tsv.gz`
  - `_load_index_tsv()`：`gzip.GzipFile` + `io.TextIOWrapper` 逐行读，每 20000 行用 `raw.tell()`
    报「已读压缩字节 / 总字节」，detail 报「N/总数 个资产」；末了合并 `fileindex_extra.json`
  - `_materialize_index()`：解压时按 1MB 分块报字节（给只有 json.gz 的老包用）
- `_work_dir()` 认三种索引名（index.tsv.gz / fileindex.json / fileindex.json.gz），
  否则打包版会把 `data/` 判成「没有索引」。

## 9.4 启动流程（app/__main__.py）
1. 建 splash 并 `processEvents()` 立刻画一帧
2. **后台线程**读索引（daemon），UI 每 50ms 轮询 `loader.progress()`：
   `done/total` → 进度条，`stage + detail` → 状态行
3. 索引读完、且卡片已显示 ≥ 0.75s → 构造 `VertexViewerWindow`
   （这一步会卡 2~3s，此时状态显示「正在构建界面…」并把进度条拉满）
4. `expand_to()` 展开 → `setGeometry` → `show()` → `ensure_game_dir()`

为什么先读索引再建窗口：构造函数里会起模型库、读名字表，GUI 线程被占住，
卡片就是一张冻住的黑图（第一版就是这样，实测 4 秒一动不动）。

## 9.5 验收
- 打包版干净 LOCALAPPDATA，逐帧截屏：
  「300000/937088」→「600000/937088」→「正在构建界面…」100% → 主窗口
- 解压 zip 后同样流程（`work/pz_1.png`、`work/pz_win.png`）
- `tools/grab_screen.py`（PIL ImageGrab 整屏）用来抓分层面板，
  `tools/grab_window.py` 用 PrintWindow 抓主窗口

## 9.6 打包
`VertexViewer.spec` 的 `WORK_FILES` 换成 `index.tsv.gz`（不再带 8.6MB 的 fileindex.json.gz），
COLLECT 之后复制到 `dist/VertexViewer/data/`。

新包：`G:\xmcl-fetch\VertexViewer-1.0-2026-10-26.zip`
- 85,563,868 字节（约 81.6MB），514 个文件
- sha256 `f70584bb850b4ff8dcba1e99733a460994696255a7fbd7ba35efe5a55fb13fbd`

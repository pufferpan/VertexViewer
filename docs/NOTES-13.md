# 13 · 重建索引 / 恢复出厂设置 / 教程页

## 13.1 为什么要重建索引

上一版把 `fileindex.json` 换成了 `index.tsv.gz`（流式读、启动进度条按它算真实
字节），但别人电脑上还是报「找不到 fileindex.json」——因为那是**旧包**的路径。
现在不管新旧、不管放没放对位置，都有一条兜底路径：

1. `loader._located_index()` 按 `index.tsv.gz → fileindex.json.gz → fileindex.json`
   找，找到哪个读哪个；
2. 全都没有，`_load_index_any()` 直接 `rebuild_index_from_paks()` 扫游戏 pak
   现场重建（344 个 pak ≈ 60 秒），成功后写 `%LOCALAPPDATA%\VertexViewer\index\index.tsv.gz`；
3. 重建也失败（例如没指游戏目录），界面弹「立即重建」，或者进「设置 → 数据维护」
   手动点「重建索引」。

## 13.2 三个按钮

| 按钮 | 做了什么 |
| --- | --- |
| 重建索引 | 后台线程扫 pak → 写 `index.tsv.gz`（缓存在 `%LOCALAPPDATA%`）+ `data/index.tsv.gz` + `data/fileindex.json.gz`；进度条读 `loader.progress()`，是真进度（已完成 pak 数 / 总数），完成后 `browser.reload_index()` 不用重启 |
| 恢复出厂设置 | 删 `%LOCALAPPDATA%\VertexViewer\{cache,uemodel,icons,logs,config.json}` 和 `data/icon_table.json`、`data/icons/`；索引默认保留（否则重启又要等重建） |
| 打开数据目录 | `os.startfile(loader.WORK)`，直接看 data/ 里到底有什么 |

实现在 `core/maintenance.py`：`rebuild(write_json=True)`、`factory_reset(keep_index=True)`、
`open_data_dir()`。`loader.reset_index()` 负责把内存索引置空。

## 13.3 教程页

`app/tutorial.py::TutorialPage`，导航栏「教程」。八张卡片：游戏目录 / 搜名字 /
分类变体 / 检视动画 / 贴图材质 UV / 自定义图标表 / 导出 / 索引丢了怎么办。

进场效果和启动卡片**同一套参数**：`EXPAND_MS = 760`、`QEasingCurve.OutCubic`、
每张错开 `STAGGER_MS = 90`。实现方式是把卡片先 `grab()` 成快照，动画期间只画
这张快照按 `0.32 → 1.0` 放大（`paintEvent` 里 `drawPixmap(target, pix, src)`），
结束后把真实控件显示回来——所以文字不会被拉变形，看起来就是「整张卡片在长大」，
和启动时那块底板一模一样。

「重播动画」按钮可以再放一遍；页面右下角落款和启动卡一致（软件制作：河豚潘 PufferPan）。

## 13.4 打包

`VertexViewer.spec` 除了把数据放 `dist/VertexViewer/data/`，还把 `AESKey1.json` 复制一份
到 `_internal/work/`：万一有人把 `data/` 删了还想重建索引，`loader.keyvault()`
会按 `WORK → _internal/work → work → _internal/data` 顺序回落，不至于连 pak 都打不开。

## 13.5 验收

- 断索引启动（删 `data/index.tsv.gz` + 干净 `%LOCALAPPDATA%`）：
  日志 `index missing -> rebuilding from 344 paks` → `index rebuilt -> …（937088 条）`
  → 界面照常，`work/noidx_win.png`。
- 设置页：`work/pkg_settings.png`（版本与数据 / 数据维护三个按钮）。
- 教程页：`work/pkg_tutorial.png`（八张卡片），动画中段 `work/tut_1.png`。
- 重建落盘验证：`work/index.tsv.gz` 8,178,279 B、`work/fileindex.json.gz`
  8,221,455 B（93.7 万条，`{'../../../Engine/Config/Base.ini': ['pak-0-0-pakchunk1-WindowsClient.pak', 1192]}`）。

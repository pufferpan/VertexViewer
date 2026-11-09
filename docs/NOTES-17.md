# NOTES 17 · 残留在旧目录的 fileindex.json 把 WORK 抢走了

## 17.1 用户报告（诊断报告 2026-10-26 21:55）

```
版本           1.0+2026-10-26.2330
exe            D:\qq聊天\VertexViewer-1.0-2026-10-26\VertexViewer\VertexViewer.exe
索引数据库       C:\Users\Administrator\AppData\Local\VertexViewer\index.db   944725 条 / 138.6MB
工作目录 WORK   C:\Users\Administrator\AppData\Local\VertexViewer\index      <-- 这里不对
```

startup.log 里反复出现：

```
索引文件：('C:\\Users\\Administrator\\AppData\\Local\\VertexViewer\\index\\fileindex.json.gz', 'json.gz')
[vertexviewer] load failed …props_collect_mainboard_140_3P.uasset: 读不到 fileindex.json。
```

## 17.2 三个问题叠在一起

1. **`tools/pakpick.py` 里写死了开发机路径**
   ```python
   IDX = r"G:\xmcl-fetch\work\fileindex.json"
   ```
   而 `cache.py::default_extract()` 在 `loader.read_entry()` 抛「非 KeyError」异常时
   **静默回退**到 `pakpick.extract()` → 去开那个只在我电脑上存在的文件 →
   `FileNotFoundError('…\fileindex.json')` → 被 `_friendly_missing()` 拼成
   「读不到 fileindex.json。」 用户自然以为是索引文件丢了。

2. **`_work_dir()` 把 `%LOCALAPPDATA%\VertexViewer\index` 列进候选**
   旧版本曾把 `fileindex.json(.gz)` 解压到这个目录。用户机器升级上来后，
   这个残留目录里有文件 → `_has_index()` 命中 → WORK 被它抢走，
   诊断报告里 WORK 就成了那个目录（连带所有「相对 WORK 找文件」的路径都歪）。

3. **报错文案还在教用户找文件**
   `_friendly_missing()` 和「找不到资产索引」对话框里仍写着
   `index.tsv.gz（或 fileindex.json.gz）`，即使索引早就换成 `index.db` 了。

## 17.3 改动

| 文件 | 改动 |
| --- | --- |
| `tools/pakpick.py` | 整个重写：只转手调 `core.loader.read_entry`，删掉 `PAK_DIR`/`VAULT`/`IDX`/`OODLE` 四个硬编码常量，文件头注释写明这个坑 |
| `cache.py::default_extract` | 去掉 `_extract_via_pakpick` 回退（回退会把真实异常吃掉），只走 `loader.read_entry` |
| `core/loader.py` | 删死代码 `_index_candidates()` / `_materialize_index()` / `FILEINDEX`；`_work_dir()` 候选里移除 `%LOCALAPPDATA%\VertexViewer\index`；新增 `_legacy_index_dirs()` / `cleanup_legacy_index()`（只清理用户目录、exe/data、exe/work，不碰打包资源目录）；`_load_index_any()` 在「旧格式导入成功」和「SQLite 已就绪」两条路径上都调一次清理（`_LEGACY_CLEANED` 保证一次进程只做一次） |
| `app/main_window.py` | `_friendly_missing()` 改成「资产索引存在用户目录 index.db，正常不会缺文件，进设置重建即可」，不再点名 `index.tsv.gz`/`fileindex.json`；「找不到资产索引」对话框文案同步 |

## 17.4 验证

| 场景 | 结果 |
| --- | --- |
| 模拟残留 `%LOCALAPPDATA%\VertexViewer\index\fileindex.json.gz` + 无数据库 | `[indexdb] imported 937088 条 from …fileindex.json.gz` → `[loader] 清理旧版索引文件：…\index\fileindex.json.gz; …\index\` → 目录消失、界面正常 |
| 已有 `index.db` + 残留旧文件 | `[loader] index(db) -> 937088 条` → 旧文件同样被删掉，WORK 不再被抢 |
| 读一个不存在的资产 | `KeyError`（走「这个资产在当前游戏目录里读不到…可能是改名/移除」），不再出现 `fileindex.json` 字样 |
| 开发者自己的 `work/index.tsv.gz` | 不受影响（清理名单不包含打包资源目录） |

版本：`1.0+2026-10-26.2400`

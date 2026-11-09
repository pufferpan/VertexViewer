# 15 · 索引换一种存法：SQLite 单文件

## 15.1 问题（用户 m04502 / m04505）

> 还是出现 fileindex.json 不存在，换一个方式存储这些
> 还是出现 fileindex.json 不存在，在别人电脑上重建索引后就文件会自动消失

两件事叠在一起：

1. **索引是「两个散装文件」**：`data/index.tsv.gz`（随包）+ `%LOCALAPPDATA%\VertexViewer\index\index.tsv.gz`（重建时写的）。位置一变、`data/` 被挪、清理工具一扫，`_work_dir()` 就找不到，于是报「索引不存在」。
2. **文案还在说老名字**：界面里的诊断文字仍写着 `fileindex.json`，用户看到「fileindex.json 不存在」就去 `data/` 里找这个文件——它早就不存在了（现在的格式是 `index.tsv.gz`），于是永远找不着。

「重建完文件自动消失」也是同一个根源：重建把新索引写到 `%LOCALAPPDATA%\VertexViewer\index\`，而下次启动 `_work_dir()` 判定 `WORK` 是别的地方（`data/` 或 exe 旁），两边不是同一处，看起来就像刚建完又没了。

## 15.2 改法：一个 SQLite 文件 `index.db`

新模块 `core/indexdb.py`：

| 项 | 值 |
| --- | --- |
| 位置 | `VERTEXVIEWER_INDEX_DB` > `%LOCALAPPDATA%\VertexViewer\index.db`（固定，不随安装目录走） |
| 表 | `assets(vpath TEXT PRIMARY KEY, pak INTEGER, loc INTEGER) WITHOUT ROWID`、`paks(id, name)`、`meta(key, value)` |
| 写入 | 先写 `index.db.tmp`，完成后 `os.replace()` **原子替换**（断电/崩溃不会留半个文件） |
| 体积 | 937088 条 → **138 MB**（若每行直接存 pak 名字是 309 MB；`paks` 表 + `WITHOUT ROWID` 省一半多） |
| 读取 | `load_all()` 全表扫一遍 **2.6 秒**，其他都不是瓶颈 |

`paks` 表的意义：344 个 pak 名字只存一次，assets 里存 `INTEGER` id —— 这是 309MB → 138MB 的主要原因。

## 15.3 加载顺序（`loader._load_index_any()`）

1. `indexdb.is_ready()` → `load_all()`，日志 `[loader] index(db) -> N 条（…index.db）`；
2. 否则找旧格式文件（`data/`、exe 旁、`%LOCALAPPDATA%`），**读到就顺手 import 成 db**（老用户升级不丢索引）；
3. 都没有 → `rebuild_index_from_paks()` → `indexdb.build()`，日志 `[indexdb] built N 条 -> …index.db`；
4. 仍然空 → `INDEX_ERROR` 用**中文人话、不出现任何文件名**：「没有可用的资产索引，也没能从游戏 pak 重建。…」。

顺带删掉了 `rebuild_index_from_paks()` 里「顺手写一份 `index.tsv.gz` 缓存」的那步 —— 就是它让用户看到「又冒出一个新文件」。现在索引**只**存在 `index.db`。

## 15.4 界面变化

- 设置页「版本与数据」：`索引：SQLite（937088 条）` + 数据库路径（可选中复制）。
- 设置页「数据维护」：说明改成「索引存在用户目录 VertexViewer/index.db，重建会直接扫 pak」。
- 教程第 8 步改成「索引不用你操心」：位置固定、丢了点一次重建即可。
- 恢复出厂设置：`keep_index=True` 时保留 `index.db`；要连它一起删得显式选。

## 15.5 包体变化

`VertexViewer.spec` 的 `WORK_FILES` 去掉 `index.tsv.gz`：

```
WORK_FILES = ("AESKey1.json", "mesh_catalog.json", "names.json", "pakinfo.json")
```

zip 从 84,885,864 → **78,024,810 字节（75 MB）**。首次启动代价是扫一次 pak（约 1 分 10 秒，有真实进度条），之后每次 2~3 秒进界面。

## 15.6 验收

| 场景 | 结果 |
| --- | --- |
| 空 `%LOCALAPPDATA%` 首次启动 | `[indexdb] built 937088 条 -> …\VertexViewer\index.db`，用户目录只有 `cache/config.json/index.db/logs/uemodel`（**没有 index 子目录**），界面正常（`work/final_db.png`） |
| 第二次启动 | `[loader] index(db) -> 937088 条`，几秒进界面（`work/zip_second.png`） |
| 解压 zip 到别的目录 | 同上；索引跟着用户目录走，不跟安装目录 |
| 老索引存在（tsv） | 首次启动自动 import 成 db，之后不再读那个文件 |
| 设置页「重建索引」 | `已重建索引：937088 个资产 / 存到：…\VertexViewer\index.db` |

## 15.7 排查这条报错的口令

以后再有人报「找不到 fileindex.json」：

1. 让他看**标题栏版本号**（本次是 `1.0+2026-10-26.2030`）——老包的报错文案里才带 `fileindex.json`；
2. 新包看到的是「没有可用的资产索引…」，说明是**真的没有 db、也没扫出 pak**（多数是没选游戏目录）；
3. 让他点设置页「打开数据目录」看 `data/` 是否完整（缺 `AESKey1.json` 就无法解 pak），再点「重建索引」。

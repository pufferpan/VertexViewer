# 10 · 「别人电脑上找不到 fileindex.json」的彻底修法

## 10.1 报错里那条路径是哪来的

对方截图里的报错：

```
加载失败  找不到文件：G:\xmcl-fetch\work\fileindex.json
如果是打包版，请确认 data 目录完整（fileindex.json.gz / AESKey1.json）
```

`G:\xmcl-fetch\work\` 是我这台开发机上的仓库目录。**只有一条代码路径会拼出它**：
早期版本的 `_work_dir()` 在找不到 `data/` 时，最后会回落到写死的开发机路径。
那条回落后来删了，但对方手上的 exe 是旧构建，所以一直复现。

结论：对方跑的是旧包。不过只让他换包不够稳，这轮把「找不到索引」这条路彻底焊死。

## 10.2 索引定位：多候选 + 有限深度搜索

`core/loader.py`：

```python
INDEX_NAMES = ("index.tsv.gz", "fileindex.json.gz", "fileindex.json")
```

`_work_dir()` 现在按顺序试：

1. `VERTEXVIEWER_WORK` 环境变量（手动指定，排最前）
2. `exe目录/data`（发布包默认）
3. `exe目录` 自己（有人把文件跟 exe 放一起）
4. `_bundle_dir()/data`、`_bundle_dir()/work`、`_bundle_dir()`（老包 `_internal/work` 布局）
5. `exe目录/work`
6. `%LOCALAPPDATA%\VertexViewer\index`

都不命中时，再用 `_find_index_dir(exe目录 / bundle, max_depth=3)` 往下找三层 ——
网友解压成 `VertexViewer\VertexViewer\data\` 或者把 `data` 改名成 `资源` 也能找到。
**整条链路里没有任何开发机绝对路径。**

## 10.3 三种索引格式都能读（旧包兼容）

`_located_index()` 返回 `(路径, 类型)`，`_load_index_any()` 按类型分派：

| 文件 | 类型 | 加载方式 | 进度 |
| --- | --- | --- | --- |
| `index.tsv.gz` | `tsv` | `_load_index_tsv`，逐行 `rsplit` | 按压缩字节 + `N/937088 个资产` |
| `fileindex.json.gz` | `json.gz` | `_load_index_json(gz=True)` 1MB 分块解压后再 `json.loads` | 按已解压 MB |
| `fileindex.json` | `json` | 直接 `json.load` | 一次性（无细分） |

所以老包（只有 `fileindex.json.gz`）也能装进新 exe 跑，进度条同样是真的。

## 10.4 找不到时给人话，不给 traceback

`INDEX_ERROR` 现在长这样（`search_report()` 拼的，全是本机真实路径）：

```
找不到资产索引文件。已经找过这些位置：
版本：1.0+2026-10-26.1030
是否打包运行：True
exe 目录：D:\VertexViewer
数据目录 WORK：D:\VertexViewer
索引文件：（没找到）
D:\VertexViewer\data 不存在或是空的
D:\VertexViewer 里有：VertexViewer.exe, _internal
打包版只要把 data 目录跟 VertexViewer.exe 放在一起就行（data 里应有 index.tsv.gz 或
fileindex.json.gz、AESKey1.json、names.json、mesh_catalog.json）。
也可以设置环境变量 VERTEXVIEWER_WORK 指向放这些文件的目录。
```

界面落点：
- 模型库顶栏 `索引不可用：<第一行>`，鼠标悬停看完整诊断；
- 状态栏同步一句「完整诊断见 设置 → 版本与数据」；
- 设置页新增「版本与数据」卡片：版本 / 数据目录 / 索引文件路径，可选中复制；
- `%LOCALAPPDATA%\VertexViewer\logs\startup.log` 第二行就写 `version=... frozen=True` 和整段 `search_report()`。

## 10.5 版本号进标题栏

`core/version.py` 里 `VERSION/BUILD`，窗口标题变成
`VertexViewer · 模型浏览器 · 1.0+2026-10-26.1030`，
`data/版本信息.txt` 也写同一行。**让对方念标题栏那一行**，就能立刻判断是不是新包。

## 10.6 四种「别人电脑」布局实测

| 布局 | 内容 | 结果 |
| --- | --- | --- |
| A 新版 | `data/{index.tsv.gz,AESKey1.json,...}` | `index streamed -> 937088 条`，691 个检视物品 |
| B 只有旧格式 | `data/` 里只放 `fileindex.json.gz` | `index loaded -> 937088 条（fileindex.json.gz）` |
| C 老包布局 | 没有 `data/`，文件在 `_internal/work/` | 自动命中 `_internal/work`，`index streamed -> 937088 条` |
| D 什么都没有 | 删掉 `data/` | 中文诊断 + 真实搜索路径，界面照常打开（库空） |

发布包：`VertexViewer-1.0-2026-10-26.zip`，85,571,791 字节，
sha256 `c28ba3165b7013f17abc18227f7bb53b1c0115c19d0d207c78374b38e72c8eec`。

## 10.7 给对方的话术

1. 把旧目录整个删掉（别覆盖解压，旧文件会混进去）；
2. 解压新 zip，得到 `VertexViewer\`，里面有 `VertexViewer.exe` 和 `data\`；
3. 打开后看标题栏有没有 `1.0+2026-10-26.1030`；
4. 还报错就把「设置 → 版本与数据」那张卡片截图发过来。

## 10.8 再加一层自愈：索引没了就现场从 pak 重建

`core/loader.py::rebuild_index_from_paks()`：直接遍历 `PAK_DIR\*.pak`，用
`PakFile(path, keyvault())` 的 `mount_point + entries`（键是 `Engine/Config/Base.ini`
这种相对路径）拼出 `../../../Engine/Config/Base.ini` 形式的 vpath，
一条条塞进内存表，同时每收一个 pak 就更新一次进度条：

```
正在从游戏 paks 重建索引 · 123/344 个 pak · 已收 412330 个资产
```

实测：344 个 pak（其中 8 个 `no key/mask matched`，是加密方式不同的 patch 包，直接跳过）
→ **937088 条，62.9 秒**，重建完顺手 `_dump_tsv()` 到
`%LOCALAPPDATA%\VertexViewer\index\index.tsv.gz`（8.2MB），下次启动 3.7 秒读完。

`_load_index_any()` 现在的顺序是：

1. `_located_index()` 找到索引 → 按 tsv / json.gz / json 分派加载；
2. 找不到、或加载抛异常（`try/except` + 打印 traceback）→ `rebuild_index_from_paks()`；
3. 重建也失败（比如 `data` 里连 `AESKey1.json` 都没有）→ 写 `INDEX_ERROR`：
   列出找过的目录 + 提示「缺 AESKey1.json 时无法重建索引」。

所以现在**不存在**「读不到 fileindex.json 就废了」这种情况：
最差也是等十几秒到一分钟让进度条把索引重新扫出来。

### 实测矩阵（本轮新增）

| 布局 | 内容 | 结果 |
| --- | --- | --- |
| E 有 data 但没索引 | `data/` 里只有 AESKey1.json、names.json、mesh_catalog.json、pakinfo.json | 日志 `index missing -> rebuilding from 344 paks` → `index rebuilt -> ...（937088 条）`，库 9397 个资产、能正常出图 |
| F 连 data 都没有 | 只有 exe + `_internal` | 走 pak 重建；若连游戏目录也没有，则给中文诊断（缺 AESKey1.json 时提示补齐 data） |

发布包更新为 85,573,375 字节，
sha256 `d861c0624ff4479f325ca28d43d4c61415b287ad5f708fae8a26ec5f73d16d73`，
标题栏版本 `1.0+2026-10-26.1130`。

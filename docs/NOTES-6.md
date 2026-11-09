## 6. 2026-10-25 第三轮修复（报错 / 灯光 / 图标表 / 检视标记 / 1P 多材质）

### 6.1 别人电脑上的两个报错

- `cache: FileNotFoundError: 'G:\xmcl-fetch\work\fileindex.json'`
  `core/loader.py::_work_dir()` 里以前把开发机的 `G:\xmcl-fetch\work` 写死在回落链里，
  别人机器没有这个盘就直接炸。现在顺序是：
  `VERTEXVIEWER_WORK` → `ROOT/work`、`ROOT/../work` → `_bundle_dir()/work`（PyInstaller 的 `_internal/work`）
  → exe 旁边 `work/` → `%LOCALAPPDATA%\VertexViewer\index`。
  打包版只带 `fileindex.json.gz`，第一次启动会解压到本地缓存目录，之后直接用。
- `cache: KeyError: '..._A03_1P.ubulk'`
  `cache.py::get()` 里 sidecar 先失败会把 `.ubulk` 的 KeyError 当主错误抛出来，
  看着像我们把 ubulk 弄丢了。现在分开记录 `main_error`：只报用户真正要的那个文件。
  UI 侧 `_LoadWorker.run()` 也把 `KeyError` / `FileNotFoundError` 翻成人话
  （「这个资产在当前游戏目录里读不到…」/「找不到文件…」），不再把堆栈糊到状态栏。

### 6.2 灯光滑杆没反应（真 bug）

`app/inspector.py` 的滑杆发的是短名 `azimuth / elevation / intensity / fill / rim / ambient / color`，
而 `render/lighting.py::LightingState.merge()` 只认 `key_azimuth / key_elevation / key_intensity /
fill_intensity / rim_intensity / env_intensity / key_color`。短名全落进 `merge()` 的 `unknown`，
渲染器一根手指都没动。修法：`DEFAULT_LIGHTING` 直接改成全名，`Inspector._LIGHT_KEYS` 做短名→全名映射。

验收：真 GL 窗口里把「主光强度」从 1.35 拉到 0.10，视口平均亮度 85.4 → 79.4、最大像素差 210。

### 6.3 自定义图标 + 可分享的图标表

- `core/usertable.py`：表在 `work/icon_table.json`（`{"资产名": "icons/xxx.png"}`），
  图片拷贝到 `work/icons/`；写不进去时回落 `%LOCALAPPDATA%\VertexViewer\icons`。
  接口 `override_for / set_override / clear_override / export_table / count`。
- `app/browser.py`：卡片**右键** → 设置图标 / 恢复默认 / 复制资产名；
  `_IconCache.get()` 先查用户表再查游戏 `UIIcon`；底部新增「图标表」按钮
  （打开目录 / 导出分享包——导出会写一份 `icon_table.json` + `icons/`，发给别人直接放进 `work/` 就能用）。

### 6.4 检视动画标记

- `core/loader.py::inspect_animations()` 扫 `Models/Props/Collect/*/ANI/Knife_Prop_View_<名>_1P|3P`，
  共 **824** 个物品带检视动画；`inspect_anim_for(stem)` 用「逐段去掉前缀再查表」匹配模型名
  （动画名比模型名短一截，互相 contains 会误配）。
- 卡片副标题后面加 `▷ 检视`，tooltip 里写出动画资产路径。
- 说明：**播放**动画需要骨骼蒙皮（shader 里还没有 bone 矩阵），属于下一阶段的工作；
  现在只是把「哪些东西能转着看」标出来。

### 6.5 1P 贴图乱：cooked 数据里没有分段

- 现象资产 `Support_C101_honeycombsmoke_01_1P`：4 个材质，但 `lod.sections` 只有 1 个（覆盖全部 7040 三角形），
  于是整块几何都用材质 0 渲染。`tools/probe_sections.py` 暴力扫 uexp，
  「count≥2 且 first 连续 tile、sum tris 相等、max_vertex+1 = 顶点数」的记录 **0 条** ⇒
  这个包根本没留分段信息（不是我们扫描漏了）。`core/mesh.py::_pick_best()` 会在多个候选里挑 section 最多的那个。
- 兜底方案（已落 UI）：材质页新增「整套网格用这个材质」，`MeshViewer.set_single_material(index)` 把整套网格换成第 N 个材质。
  实测同一资产切到材质 #1 后显示的是黄色「CONTAGION」罐，切回 #0 是灰色滤毒罐 —— 用户可以自己选对的那套贴图。

### 6.6 验收

- `python -m render.selftest` → 24 张预览、`failures: []`
- `python tools/selfcheck.py` → 8/8 PASS（索引 937088 / 可渲染 9443 / 中文名 9933 / 真窗口 1148 三角形）
- 干净环境跑打包版：`LOCALAPPDATA` 指向空目录启动 `dist/VertexViewer/VertexViewer.exe`，
  自动把 `_internal/work/fileindex.json.gz` 解到缓存并正常出图（`work/app_clean.png`）。

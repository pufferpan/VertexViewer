# 30 · 商城皮肤（Commerical）+ 分类变少的两处根因

改动日期：2026-11-07。两个问题都出在「找资产」这一层，不在渲染层。

## 30.1 `Content/Commerical/` 的皮肤模型纳入模型库

游戏里那个目录拼写就是 `Commerical`（少个 c），旧代码只认 `Models/`：

- `core/loader.py::list_models()` 只收 vpath 含 `Models/` 的条目；
- `inspection_catalog.inspectable_paths()` 只留 `mesh_catalog.json` 里标了
  `StaticMesh`/`SkeletalMesh` 的资产，而 catalog 里一条 Commerical 都没有；
- 于是「只显示可检视模型」默认勾着时，皮肤整批被藏掉。

现在的做法：

- `is_commercial()` / `commercial_like_mesh()`：按 `/Content/Commerical/`、
  `/Content/Commercial/` 判定（必须带 `/Content/` 段，否则 `BluePrints/UI/.../Commercial/`
  的 UMG 蓝图会混进来），再过一层目录/后缀/前缀黑名单挡掉材质、贴图、图集、动画、
  蓝图——`Aniamtion/`（游戏里就是这么拼的）、`Icon/`、`Texture/HD/T_*`、
  `Material/MI_*`、`*_Skeleton`、`BP_*` 都在黑名单里。
- `classify()` 对皮肤网格返回 `"mesh"`，`is_mesh()` 不再因为「catalog 里没有」而丢弃。
- `list_models()` 同时收 `Models/` 与 Commerical，`app/browser.py` 的索引 worker
  对 catalog 里没有、但 `commercial_like_mesh()` 为真的条目也放行。
- 新增分类：**武器皮肤 / 角色皮肤 / 道具皮肤 / 活动**，`guess_category()` 先按
  `WeaponAppear` / `CharAppear` / `PropAppear`+`BusinessFiller` / `Event` 分流；
  卡片副标题会显示皮肤系列名（`commercial_series()`）。
- 贴图目录：皮肤贴图不在 `GenTexDirHD/Game/Models/`，`tex_dir_for()` 按三种布局分别
  映射到 `GenTexDirHD/Game/{Models,Commerical,Commercial}/`。

## 30.2 「只显示可检视模型」默认不勾

`inspectable_paths()` 的语义是「有检视动画」（骨骼、动画都在本机才满足），不是
「能渲染」。没装全量 pak 时它会把大量能正常渲染的网格一起藏掉，看着就像「分类空了」。

- 默认值改为不勾选；tooltip 写清楚勾上会隐藏什么；
- 分类 chip 直接带条数（`武器 758`、`道具皮肤 592`），一眼看出哪类有货；
- 侧栏标题改成「N 个模型 / N 个带检视动画的模型」，不再只报可检视数量；
- chip 改成一行 3 个：一行 4 个时「钥匙卡 19」会被裁成「月匙卡 1」。

## 30.3 自动选错游戏目录（「分类很少」的真根因）

`find_game_root()` 以前是「第一个命中就返回」：配置文件里记着 `G:\Delta Force\Delta Force`
（只装了 9 个 pak 的残包），于是隔壁 `E:\WeGameApps\rail_apps\DeltaForce(2001918)`
（118G、218 个 pak）永远轮不到，索引只有 45,891 条。

现在：

- 收集所有候选（环境变量、配置、旧版 `DFViewer`/`DFMapViewer` 的配置、默认路径、
  盘符两层扫描），按 **(pak 个数, pak 总字节)** 挑最全的那份；
- 全都像残包（<20 个 pak）时再做一次三层深度扫描（`盘:\WeGameApps\rail_apps\<游戏>`
  这种布局两层扫不到），结果缓存进配置的 `known_roots`，只扫一次；
- 配置里的目录明显更少（不到最全那份的一半、且对方 ≥20 个 pak）时自动改配置，
  并在 stderr 打一行说明。

索引缓存也加了 pak 集合指纹（`%LOCALAPPDATA%\VertexViewer\index\pakset.txt`，
内容 = 目录 + pak 个数 + 最新 mtime）：换了目录或装了新包就丢掉旧库重建，
不再出现「名字列得出来但打不开」。

本机实测：9 个 pak 的残包 → 45,891 条；218 个 pak 的全量装 → **765,213 条**，
模型库 17,189 个网格（`武器皮肤 6051 / 配件 3933 / 藏品 1033 / 武器 758 / 道具 542 /
角色 534 / 载具 499 / 弹药 443 / 装备 385 / 角色技能 362 / 钥匙卡 19 / 容器 46 /
活动 1`）。重建耗时 40 秒（218 个 pak）。

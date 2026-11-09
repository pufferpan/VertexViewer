# NOTES-21：改枪台（gunsmith）+ 标题栏与窗体合并

## 21.1 标题栏和软件融为一体（m06933）
- 根因：FluentPy 的「外壳色」`_resolved_shell_color()` 默认是硬编码 `#202020`，
  内容区是 `theme.tokens.background = #1f2633` —— 顶部那条异色带就是这么来的。
- 做法：
  1. `self.set_background_colors("#f3f3f3", "#1f2633")`：外壳跟着内容走（`_painted_shell_surface` 直接返回 `_resolved_background_color()`）；
  2. `self.set_title_bar_enabled(True)`：用库自己的 `FluentTitleBar`（和外壳同色），
     原生 caption 那条路（`DwmSetWindowAttribute` 的 35/34/36）在 Win11 26200 上
     调用返回 0 但实际盖不住，只留作兜底；
  3. `_tidy_title_bar()`：把前进/后退按钮藏掉（本程序没有历史栈）；
  4. 窗口标题不再拼副标题两次（`setWindowTitle` 只在 `VertexViewerWindow.__init__` 里设一次）。

## 21.2 改枪台
- `core/gunsmith.py`：`Slot/SLOTS(10 个槽位)`、`guess_slot()`、`PartSpec`、
  `Recipe`、`save_recipe/list_recipes/load_recipe`（`%LOCALAPPDATA%/VertexViewer/gunsmith/*.json`）、
  `bounds/anchor_point/auto_scale/place`、`_transform_lod`、`merge`、`assemble`。
- 关键判断：**该游戏资产没有 socket 数据**（UAsset 里不存挂点，字符串扫描也只有
  `Bone01/MaxBonesPerVertex` 这类构建参数），而同一把枪的配件本来就做在同一套局部坐标里，
  所以默认「缩放 1 / 位移 0 / 旋转 0」直接叠就是对的；跨族拼装才用锚点 + 手动微调。
  > **本条 21.2 的判断已被推翻**：挂点数据不在网格资产里，而在
  > `DataTables/WeaponPart/WeaponPartsMeshSocketNameInfo` 表里（20270 行 mesh→socket），
  > 配合 `PartSocketsTable`（socket id→名字）和 `GunDescTable`（官方预设的装配树）。
  > 现在改枪台按真实 socket 挂接，详见 `docs/NOTES-23.md`。
- `app/gunsmith_page.py`：左（主件 + 10 槽位表）/ 中（`create_viewport`）/ 右
  （已装配件 `ComboBox` + 位置/旋转/缩放 7 个 `Slider` + 自动对齐/复位）；
  底部「保存方案 / 读取方案 / 导出 OBJ」。每次改动 30ms 防抖后 `assemble()` 重算并
  `viewport.set_mesh()` + `frame_all()`。
- 注册：`main_window` 里 `addSubInterface(self.gunsmith_page, icon("play"), "改枪")`（在「导出」前）。
  截图/演示用 `VERTEXVIEWER_START_PAGE=gunsmith`，并且**等索引就绪后再切**（索引期间切会被刷回模型库）。

## 21.3 验收
- 离屏：主件 + 3 配件 → `已装 3 个配件 · 10293 三角形`（`work/gs_page2.png`）；
  选中护木后右栏下拉/滑杆回填（`work/gs_page3.png`）。
- 命令行：`gs.save_recipe(..., "测试M4A1")` → `%LOCALAPPDATA%\VertexViewer\gunsmith\测试M4A1.json`；
  读回 parts/slot 完整；`export_obj` 出 **823,625 字节** OBJ。
- 打包版：`work/gs_pkg4.png`（改枪页、标题栏与主体同色、无前进/后退）。
- 已知：皮肤类 `WeaponAppear` 资产是白模（贴图不在该包内）；标准
  `/Models/Weapons/Parts/` 的部件才带贴图。跨枪族叠放会错位，用右栏微调。

## 21.4 官方建议配件 + 材质复核（第二轮）
- **官方配件**：`core/gunsmith.py::official_loadout(base_vpath)`。该游戏没有能直接读的
  预设表（`GunPresetTable_CombinationTable.uexp` 只有 49 字节，是空 stub；
  `WeaponAttributeTable` 69KB 全是数值、`PartSocketsTable` 只有 14 个名字），
  所以按游戏自己的命名规则还原：
  1. `gun_code()` 从主件名里抠型号码（`Rec_AR_M4A1-Std_001_HavvkTech_p9_3P` → `M4A1-Std_001`）；
  2. 候选 = 名字里带该型号码，或在 `<枪>/Model/` 目录下的 `Bar_/Han_/Muz_/Mag_/Sto_/PisG_/FroG_/Acl_..._3P`；
  3. 打分：同型号码 +10、同目录 +6、同皮肤 +4、同 Model 层 +2，每个槽位取分最高的一件。
  实测 M4A1：护木 `Han_AR15_lvoa_044`、枪管 `Bar_S-370`、枪口 `Muz_S-F`、握把 `PisG_B`、
  弹匣 `Mag_556-45-30R`、枪托 `Sto_A` —— 6 件，11516 三角形。
- **默认变换改成真正的恒等**：`PartSpec.anchored`（默认 False）。只有点过「自动对齐」
  （或写了 `auto_scale`）才按锚点摆；默认 `translate = offset`。该游戏所有配件都在
  `x=前后 / y=上下 / z=左右` 这一套局部坐标里（实测主件 x[-0.05,0.17]、枪管 x[-0.01,0.36]、
  枪托 x[-0.18,0]、弹匣 y[-0.18,0.02]），所以直接叠就是对位。
- **材质复核**：之前看到的白模是**离屏软件着色**的截图（`QT_QPA_PLATFORM=offscreen`
  下 `QOpenGLWidget is not supported`、走 `platform=offscreen: no GL grab, software shading`，
  那条路径不上贴图）。真 GL 下 `[tex]` 日志显示 base/normal/orm 全绑上：
  `Rec_AR_M4A1-Std_001_HavvkTech_p9_C_HD / _N_HD / _MRA_HD` 都对，渲染出来是带皮肤的枪。
  页面截图 `work/gs_official_page.png`、离屏对照 `work/gs_official3.png`。

## 21.5 第一轮修复收尾：位置兜底 + 只列有名字的资产
- **位置**：`PartSpec.anchored`（默认 False）→ 默认 `translate = offset`（恒等）。
  新增 `gunsmith.auto_fit(spec, base_lod, part_lod)`：配件中心落到主件包围盒外
  （放宽 0.6 倍长）就按槽位锚点平移，并置 `anchored=True`；页面在「选配件」和
  「官方配件」两条路径都会调用它，所以跨枪族/皮肤单摆的件会自动拉回枪上。
  实测官方 6 件（Bar_S-370 / Han_AR15_lvoa_044 / Muz_S-F / PisG_B / Mag_556-45-30R /
  Sto_A）全部 `anchored=False offset=[0,0,0]` —— 同一把枪本来就是同一套局部坐标。
- **只列有游戏内中文名的资产**：`_PickerDialog._refresh` 里加 `cnnames.resolve_cn()`，
  空名字直接跳过；排序改成「`_3P` 优先 → 命中关键字 → 路径短」，避免把 `_UI`/`_1P`
  混在前面。顺手修了 `self._key` 没转小写导致「Rec_」筛不出东西的 bug
  （`self._key = (key or "").lower()`）。
- 产物：版本 `1.0+2026-10-30.0930`，打包版与 zip 版都能停在改枪页（`work/pkg_r1.png`）。

## 21.6 模型目录进索引 + 中文名 + 选择后再解包（m07765）
- `core/indexdb.py`：`models(vpath PK, cn, slot, gun, kind) WITHOUT ROWID`，
  `build()/import_from()` 用 `gunsmith.catalog_rows()` 一次写进去；
  `MODELS_REV` 版本号 + `models_look_stale()` 让规则升级时自动重刷。
- `core/gunsmith.py`：`catalog_rows()` 只收 `_3P/_1P` 且**在 mesh_catalog 里有网格**的资产
  （修掉了把 `_C_HD/_N_HD/_MRA_HD/_UI` 当模型的 bug）；`catalog()` 缓存 + 老库自愈；
  `bases()/parts()` 只给 `_3P`；`display_name()` 优先游戏内中文名。
- `official_loadout()` 重写为「主件名片段 + 片段前缀匹配」：该游戏配件按自身型号命名
  （M4A1 的护木叫 `Han_AR15_lvoa_044`、G3 的护木叫 `Han_G3_psg_109`、弹匣 `Mag_76251-30_g3Large_097`），
  只认「整段前缀」能避免 `DarkKnight` 里的 "ar" 被误判成 AR 家族；完整型号码命中额外 +30。
  实测 M4A1/G3 各配出 6 件，中文名齐全（`work/gs_final.png`）。
- `app/gunsmith_page.py`：`_PickerDialog` 改成吃目录行（中文名/槽位/枪族），铺开 400 行 0.69s、
  搜索即时；不再预加载任何模型；`_pump()` 在加载主件/官方配件时刷状态并 `processEvents()`，
  界面不再假死。
- 教训：**整类重写用 write 工具写整个文件**，别拿 heredoc 做「切片替换」——`end` 落在类后半段
  会把整类切掉（本次把 `GunsmithPage` 删了，仓库又没 git，只能按设计手写恢复）。

## 21.7 位置修正 + 官方默认配件（m08090）
- **位置**：`plan_layout` 那种「全部件按接缝重摆」会把枪拉成 1.6 米——因为该游戏的
  枪管/护木/枪托/弹匣/握把本来就做在同一套局部坐标里（恒等就对），只有**枪口**和**瞄具**
  的原点是自己的。新增 `snap_extremes()`：只把枪口顶到当前最前端（横向对齐**枪管轴线**，
  不是机匣中心线）、瞄具骑到最高处，其余一律不动。`assemble()` 里
  `slot_fit`（官方件）走 `snap_extremes`，`auto_scale`（跨族/手动自动对齐）才走 `plan_layout`。
- **官方默认配件**：`_set_base()` 末尾直接调 `_apply_official()`，选完主件即配齐；
  `official_loadout` 对不足 2 件的情况用 `_skin_kit_dir()`（同皮肤 `Model/` 整包）兜底。
- 实测：M4A1 6 件 / MK47 7 件，装配合成后 `x[-0.253,0.528]`（枪托在最尾、枪口在最前），
  真 GL 截图 `work/gs_fix_m4.png`、`work/gs_fix_mk.png`；打包版 `work/pkg_fix.png`（1.0+2026-10-30.1400）。

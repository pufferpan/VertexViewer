# NOTES-24 · 干员（角色）模型与皮肤材质的修复

日期：2026-10-30　范围：`core/mesh.py`、`core/loader.py`、`core/cnnames.py`

## 1. 资产结构（实测）

### 本体干员
```
Models/Characters_HD/Hero_HD/<M_Kai_HD>/<M_Kai_002_HD>/
    M_Kai_002_Body_3P_HD.uasset      ← 3P 全身（骨骼网格）
    M_Kai_002_Body_UI_HD.uasset      ← UI 版（摆姿用）
    M_Kai_002_Face_UI_HD.uasset
    M_Kai_002_Lower_3P_HD.uasset / _Upper_1P_HD.uasset
    Materials/                       ← MI_Kai_Haavk_049_* 等材质实例
    Textures/                        ← T_Kai_Haavk_049_* 贴图
```

### 皮肤（Commerical）
```
Commerical/CharAppear/<皮肤码>/Character/<M_XXX_皮肤>/            ← 骨架、动画、物理资产
Commerical/CharAppear/<皮肤码>/Character/<M_XXX_皮肤>_HD/         ← 网格 + Textures/
Commerical/Event/OperatorSkin/<…>/{Texture,Atlas/BakedSprite,Effect/Materials}
```
**坑**：`M_Kai_Haavk_049_Body_3P_HD` 这种皮肤网格**自己目录里只有网格**，
真正的 `MI_Kai_Haavk_049_*` 材质在**基础干员目录** `M_Kai_002_HD/Materials/` 里，
贴图在 `M_Kai_002_HD/Textures/`。旧逻辑只在模型自己目录里找材质 →
皮肤渲出来是一坨没有贴图的灰模（用户报的「材质异常」）。

## 2. 材质：按名字片段回退（core/loader.py）

新增：
- `_MAT_CATALOG` + `_material_catalog()`：全库材质索引（只收 `*/Materials/*.uasset`），
  构建一次约 1~2 秒，22871 条。
- `_materials_by_name(model_vpath, limit=8)`：把网格名拆词（去掉 `m/mi/sk/hd/mesh`），
  要求**前两段（干员代号 + 皮肤套系）完全一致**，再看公共词数 ≥3 且与两边词数差 ≤2。
- `materials_in()`：自己目录找不到材质时退回上面这条；顺带跳过「自己」
  （`if k == model_vpath: continue`，否则会把网格当材质加载，最后退化成合成材质）。

实测：`M_Kai_Haavk_049_Body_3P_HD` 由「1 个无贴图材质」变成「6 个真材质，
第一个 `MI_Kai_Haavk_049_Body_3p_HD` 带 BaseColor/Normal/MRA」。

## 3. 索引容器的新布局（core/mesh.py）

干员网格的索引不是跟在顶点数据后面，而是**紧挨在位置缓冲之前**：
```
[i32 count][count × u16]  ← 数据末尾精确等于位置缓冲起点
```
校验式 `头部偏移 + 4 + count × elem == pos_off`，实测：

| 资产 | count | 三角 |
| --- | --- | --- |
| `M_Kai_002_Body_3P_HD` | 126753 | 42251 |
| `M_Elio_7DL9D_9j_A_Body_3P_HD` | 120285 | 40095 |

新增 `_locate_leading_container(raw, pos_off, min_start, num_vertices)`：
- numpy 扫 `pos_off` 之前 12MB，u32 按 0/2 两种对齐（起点先对齐到偶数，覆盖两个奇偶）；
- 同时支持 `elem=2` 与 `elem=4` 两种宽度；
- 抽样校验首尾索引都 `< num_vertices`。

`_resolve_indices()` 的取舍顺序改成：
1. **leading 容器**（末尾顶到位置缓冲，几乎不会误判）→ 质量达标就直接用；
2. 尾部定位器 + 整段扫描的候选一起比，取 `(not good, -referenced, degenerate, -size, spread)` 最小；
3. 整段扫描按 `min_count=3000 → 300` 两轮，第一轮就找到好候选就不再扫第二轮。

注意：**不能**给尾部定位器加「够好就早退」——`M_Dragon_Haavk_053_Body_3P_HD`
会因此拿到被截断的半截缓冲（41500 三角掉到 24802）。只有 leading 容器可以早退。

## 4. 性能

`_scan_lod_sections()` 在 5MB 的干员导出体上会扫出 300 多个垃圾候选，白烧 8~10 秒。
现在若能识别出「leading 容器」布局，就直接跳过 section 扫描与 `_find_index_run`：

| 资产 | 修复前 | 修复后 |
| --- | --- | --- |
| `M_Kai_002_Body_3P_HD` | ~10.0s | **2.9s** |

其余干员（尾部布局）仍在 6~8 秒，瓶颈是整段容器扫描，后续可继续做候选剪枝。

## 5. 分类：干员算「角色」（core/cnnames.py）

在「钥匙卡」规则之前插入两条：
- `commerical/charappear/` 或 `commerical/event/operatorskin/` → **角色**
- `commerical/weaponappear/` → **武器**

（`Commerical` 里 3858 个是武器皮肤、干员皮肤另有几打，不分类会全堆进「其他」。
`PendantAppear`/`PropAppear` 继续按名字关键字走。）

## 6. 还没解决的：一个网格只有一个材质

干员网格的 `Materials` 属性有 6~8 个材质槽，但导出体里**找不到
`FSkelMeshRenderSection` 表**（固定 stride、变长 BoneMap、SOA、材质号递增模式、
串联容器、位置缓冲前后若干 KB 的 hexdump 全部试过），`LODInfo` 属性里也没有
section 范围。所以目前整只干员只用 `materials[0]`：衣服/鞋/脸/头发共用一个图集，
颜色靠 UV 蒙对，局部会有错色（例如脸部和头发）。

武器网格同理（1 段 / N 材质）。若以后找到 section 表位置，`_sections_from()` 与
`_load_skeletal()` 的回退分支已经就绪，接上即可。

## 7. 复现命令

```bash
python tools/_op_diag.py  "%M_Kai_Haavk_049_Body_3P_HD.uasset"   # 材质/贴图诊断
python tools/_op_shot.py  "M_Kai_Haavk_049_Body_3P_HD.uasset" kai_haavk pbr
python tools/_op_batch.py 12                                     # 批量体检
python tools/_op_ui.py                                           # 界面实拍（角色分类/模型/皮肤）
```

## 8. 材质槽手动切换（2026-10-31）

`section` 表找不到，整只干员只能用 `materials[0]`，于是：

1. **自动**：`core/loader.py::_order_materials()` 按「网格名 vs 材质名的词重合度」
   重排材质槽，把最像本体（同干员代号 + 同皮肤套系）的那格排第一。词表去掉了
   `m/mi/hd/bp/body/mesh/sk/1p/3p/ui/lay/parts/material...` 这些没有区分度的词。
2. **手动**：右侧检查器「材质覆盖」卡片里新增 **材质槽** 下拉，列出这个模型的全部
   材质，选哪个就把哪个转到第 0 位立即重渲染，并写进 `work/material_table.json`
   （键是资产名，和 `icon_table.json` 一样按变体兜底查找），下次打开这个资产自动套用。

相关代码：
- `core/usertable.py`：`material_table_path()/slot_for()/set_slot()/clear_slot()`
- `app/inspector.py`：`set_material_list(names, current)` + `material_combo`
- `app/main_window.py`：`_apply_material_slot_from_table()/_rotate_materials()/apply_material_slot()`

## 9. 图标自定义（原本点了就崩）

`app/browser.py::_card_menu` 里写的是 `from app.fluent_api import QCursor, QMenu`，
而这两个名字 fluent_api 根本没导出 → 右键一点就 `ImportError`（进「崩溃-*.txt」），
所以「图标改不了」。已改成一律从 PySide6 拿，并顺手补齐：

- 「设置图标（选本地图片）…」：选完自动归一到 256×256 透明底 PNG 存进 `work/icons/`，
  写 `work/icon_table.json`，卡片立即换图；
- 「把当前图标另存为…」：把这张卡现在用的图标（自定义 / 游戏 UIIcon / 图标包 / 占位）
  存成 PNG 到你选的位置；
- 「恢复默认图标」「复制资产名」保留。

`core/usertable.py::_normalize()` 负责归一（Pillow 缺失时退化成原样拷贝）。

## 10. 首次启动向导（2026-10-31）

需求稿（手绘）要求：首次启动进设置向导，背景最大化铺满整屏，右半部分是 3 行 45°
的软件截图，左半部分放向导面板；三步走完，窗口「由大变小」回到加载页。

实现（`app/wizard.py`）：

- `_Backdrop` 自绘背景：`assets/wizard_bg.png` 等比裁切铺满（`KeepAspectRatioByExpanding`）。
- `_Panel` 是左侧半透明深色卡片（`rgba(9,22,38,.74)`，圆角 22），标题/正文/要点/按钮行/状态行/步骤点。
- 三步：`你好呀！` → `接下来，选择我们要工作的目录`（自动检测 / 手动选择…，
  选完显示「等一下哦…」，命中 `DeltaForce\Content\Paks` 变「好耶耶！这是正确的目录！！」）
  → `准备好了！`（按钮变「开始使用」）。
- 收尾：`QPropertyAnimation` 把窗口缩到中央 760×470 并淡出，然后 `finished` 信号退出，
  启动流程继续走「小方框 → 展开」的老路径（`app/__main__.py::_run` 里在 splash 之前跑向导）。
- 状态存 `%LOCALAPPDATA%\VertexViewer\config.json` 的 `wizard_done`；`game_root` 由
  `core/loader.set_game_root()` 写（自动检测/手动选择都会写）。
- 环境变量：`VERTEXVIEWER_WIZARD=1` 强制显示、`=0` 强制跳过、`VERTEXVIEWER_NOSPLASH_WIZARD=1` 临时不弹。

背景图由 `tools/make_wizard_bg.py` 生成（PIL）：先横平竖直排 3 行卡片并转 −45°，
再把整块贴到右半屏，左侧压暗留给面板；`VertexViewer.spec` 里 `assets/wizard_bg.png`
随包进 `_internal/assets`。

### 10.1 文字入场动画（2026-10-31）

`WizardWindow._animate_lines()`：给每个文字控件挂 `QGraphicsOpacityEffect`，
`QParallelAnimationGroup` 同时跑「opacity 0→1」和「pos 从 base+22px 升到 base」，
`OutCubic` 460ms，每行错开 70ms（`QTimer.singleShot(i*stagger, group.start)`）。

- 触发点：`showEvent` 里延 90ms 跑第一屏；每次 `_show_step()` 再跑一遍；
  状态栏文字（`_status`）单独用 `slot="status"`，360ms、不抖位移，避免和主文案的动画互相打断；
  动画组按 slot 分开存 `self._anims[slot]`，重放前先 `stop()` 旧的。
- 注意：`QWidget.grab()` / `render()` **不套用 QGraphicsEffect**，所以 offscreen 截图看不到淡入效果，
  验证得读 `widget.pos().y()` 和 `effect.opacity()`（实测 title: y 117→95、opacity 0→1，body 晚 70ms）。

#### 10.4 向导要出现在「加载动画进行中」（2026-10-31）

需求原话：「是在加载动画的时候询问，不是在启动完成后询问有没有见过用户」。

改法（`app/__main__.py`）：
- 删掉 `_after()` 里「主窗口 show 完再进向导」的 `_then_ask()`；
- splash 亮出来之后 `QTimer.singleShot(760, _start_wizard)` —— 先让加载动画转起来，
  再在它上面弹 `WizardWindow.start()`（小窗 → 长大 → 三行飞入 → 三步）；
- `_wiz_state = {"active", "defer"}`：向导开着的时候 `_open()` 只记 `defer` 不真开，
  向导关闭后 `QTimer.singleShot(300, _open)` 再展开 —— 不能在向导的嵌套 `QEventLoop`
  里直接 `_open()`，否则 splash 的展开动画会被这次重入挤掉，主窗口会以默认小尺寸冒出来；
- `_poll()` 里的 `_open` 排程加 `state["scheduled"]` 闸门，否则每 50ms 排一个；
- 向导弹出时 `splash.hide()`、关闭后 `splash.show()+raise_()` —— 否则那张小蓝卡片会浮在向导的卡片墙上。

实机时间线（打包版采样，窗口尺寸）：`2.2s 560×346(splash)` → `3.9s 760×464(向导小窗，splash 还在)` →
`5.5s 1306×732` → `6.5s 1920×1032` → 三步完成 → `7.7s 1500×940(主窗口)`，`wizard_done: true` 落盘。

## 10.2 重看首次向导（2026-10-31）
`app/pages.py::SettingsPage._replay_wizard()` —— 「设置 → 数据维护」里新增
`重看首次向导` 按钮（排在「恢复出厂设置」后面），点了就新开一个 `WizardWindow`
最大化显示，主窗口不动；向导 `finished` 后如果 `core.loader.PAK_DIR` 变了就
`browser.reload_index()` 刷索引并在状态栏提示。窗口引用存在 `self._wizard` 防 GC。

### 10.3 首启入场的动画（2026-10-31）

顺序按需求改成：**启动动画（小方框 + 进度条）先跑完 → 主窗口露脸 → 才进向导**。

1. `WizardWindow.start()` 不再 `showMaximized()`：先按 `availableGeometry()` 摆一次，
   `processEvents()` 后把 `geometry()` 读回来当 `_full_rect`（高分屏下逻辑/物理像素不一致，
   直接拿 `availableGeometry()` 当目标会差一圈），再缩到居中 `760×470` 显示。
2. 小窗里只放一句话：标题「等一下…」、正文「我还没见过你诶，等一下，让我来带你设置一下吧！」，
   同时 `_park_rows()` 把三条带子 `alpha=0` 停在屏幕外（不然小窗里就看见卡片了）。
3. 1450ms 后 `_grow()`：`QPropertyAnimation(self, b"geometry")` 920ms `OutCubic` 长到全屏，
   结束再钉一次 `_full_rect`。
4. `_fly_rows()`：三条 `QVariantAnimation` 0→1、880ms `OutCubic`、错开 110ms，
   `_tick` 里 `dx=dx0*(1-v)`、`alpha=min(1, v*1.7)`，起点 `[(1.10w,-0.10h),(1.18w,0.42h),(1.26w,-0.55h)]`。
5. 全部落位后 `_finish_intro()`：`_intro=False`、`reset_rows()`、显示「跳过设置」、`_show_step(0)`。

背景素材因此拆成分层：`tools/make_wizard_bg.py` 现在出 `wizard_base.png`（干净底）、
`wizard_row1..3.png`（横平竖直的截图带子，`PER_ROW=6`、`CARD_W=400`、`pitch=art_h+96`）、
`wizard_rows.json`（`{"canvas":[2560,1600],"base":...,"rows":[{"file","cx","cy","angle":-45}]}`），
外加 `wizard_bg.png` 整图兜底。`_Backdrop` 读 json 后把 `_pix` 换成干净底图，
三条带子按 `cx/cy` + `rotate(angle)` 画；`set_row(i, dx, dy, alpha)` 供动画调用。
坐标算法：先把三行排在一条 `band` 里再整体转 −45°，再从 band 上按行裁出来**单独转 −45° 把旋转烤进 PNG**，
清单里记的是旋转后图块的左上角 `x/y`，Qt 端只做「按左上角整块贴图」——
之前记的是 `cx/cy + angle`（画的时候再 rotate），中心点算错一次就会整体歪，而且每帧都要重采样，
既不准又卡。现在 `ImageChops.difference` 平均差 0.85，位置和静态整图一致。

流畅度上踩的三个坑（都修了）：
1. 窗口长大时每帧按新尺寸 `QPixmap.scaled()` 重采样 2560×1600 底图 → 改成 `set_growing(True)` 时
   用一张 760×470 的小底图拉伸铺满（`_small` 必须基于「干净底图」生成，否则会把卡片带进来）。
2. 每次 `resizeEvent` 都重排面板 → 中文每帧重新折行。改成 `_layout_panel()`：入场期面板**尺寸固定**
   （`_panel_intro_size` 只在开头算一次），只跟着窗口居中；入场结束再按大窗口重排一次。
3. 文字动画的基准位置取自「还没排版」的瞬间 → `start()` 里把 `_animate_lines` 推迟到 `show()` 之后 60ms，
   并在每组动画 `finished` 时把控件 `move` 回基准，避免多次动画叠加错位。

`app/__main__.py` 相应调整：向导从 splash 之前挪到 `_after()` 里（`QTimer.singleShot(180, _then_ask)`），
`_then_ask()` 先 `_run_wizard()` 再弹选目录；无 splash 分支也补上 `_run_wizard()`。
`app/pages.py::_replay_wizard()` 改成 `wizard.start()`，重看也走同一套入场动画。

## 11. 全屏闪屏 + 改枪配件缺失（2026-10-31）

### 11.1 全屏下移动鼠标闪屏

Mica 是 DWM 的桌面合成背板（`fluentpy.window_effects.apply_system_backdrop`）。
全屏时窗口铺满整屏，鼠标移动引起的 hover 重绘会让 DWM 重新合成一次，肉眼就是闪。

- `app/main_window.py:198` 原来无条件 `setMicaEffectEnabled(True)`，`_setup_fluent_chrome()`
  在 Win11 又开一次 → 两处都改成**默认关**，要透明磨砂效果设环境变量 `VERTEXVIEWER_MICA=1`；
- 关掉后要补实色底，否则背景全透明（白字看不见）：`_apply_mica(False)` 里 `setBackgroundColor(...)`；
- `toggle_fullscreen()` 进全屏前 `_apply_mica(False)`、退出后按 `_mica_ok` 恢复，
  这样即使有人手动开了 Mica，全屏也不会闪。

### 11.2 改枪「官方配件」缺件 / 串枪件

三个独立原因：

1. **族对不上也照收**：预设节点给的道具 ID 由挂点表映射到的网格，偶尔是**别的族**
   （例：ScarH 默认枪托的道具 `13040000193` → `Other_minimi-1913adapter_048_3P`）。
   现在大件族（`_MAJOR_FAMILIES`：枪管/护木/枪托/握把/弹匣/枪口/瞄具/两脚架）对不上时，
   先换 `guess_part_vpath(base, family)`；换不到才记「缺」。
2. **两字符型号被过滤**：`_match_tokens()` 原来只留长度 ≥3 的片段，`AR_G3_054` 的 `g3`
   被丢掉 → G3 一个候选都匹配不到、grip/stock 全空。现在 `_SHORT_CODE_RE`
   （`^[a-z]{1,2}\d$|^[a-z]\d[a-z]?$`）也放行。
3. **预设挑错**：原来按「件数最多」挑 DesId，会挑到一个配件一多、但大件缺失的预设
   （M16A2 的 13 件版缺瞄具）。现在两档排序：`filled>=4 且大件不缺` 优先，
   否则按 `filled - 4*大件缺口`。
4. 删掉 `_arrange_void_parts()` 的调用 —— 它按包围盒拟合，会把正确件换成别的枪的件。

界面：状态栏会补一句「· 包内缺网格：枪管」这种提示（`core/gunsmith.py::missing_parts()`，
只列大件，战术/两脚架不算）。

60 个机匣抽样：改前 8 个有问题 → 现在只有 `Rec_AR_CAR15_050_3P` 缺枪管，
而包里确实**没有** CAR15 的枪管网格（只有皮肤目录里借 M16A2 那根 `Bar_AR-470_M16A2-Std_016`）。

## 12. 不同 DPI 的界面适配（2026-10-31）

以前窗口按 1500×940 硬开、卡片按 140px 硬排，1366×768@125% 这种机器上会挤出屏幕。
新增 `app/ui_scale.py`：

* `avail()` 当前屏幕可用区域（逻辑像素）
* `fit(w, h, margin=0.92)` / `min_size(w, h, margin=0.62)` 把期望尺寸收进屏幕
* `ui_scale()` = 逻辑 DPI / 96（1.0~1.4，可用 `VERTEXVIEWER_UI_SCALE` 覆盖）
* `px(v)` 设计稿像素 → 当前缩放下的逻辑像素

接线的地方：`app/main_window.py` 的 `resize`/`setMinimumSize`、`app/__main__.py::_target_rect()`、
`app/browser.py` 的 `_ModelCard.card_size()`（图标 58→`_px(58)`、标题高 30→`_px(32)`、列表最小宽 300→`_px(300)`）、
`app/inspector.py` 的 280/360。

验证：`QT_SCALE_FACTOR=1.5` 起 exe，窗口 1766×948 铺满、卡片放大到 210×222、按钮不重叠。

## 13. 「游戏影视 Game」风格（2026-10-31）

* `render/postfx.py`：`STYLE_IDS` 加 `game: 6`，别名 `df/ingame/art/cinematic`；
  `STYLE_PARAMS["game"]` = 饱和 1.05、bloom 0.22、暗角 0.30、颗粒 0.005、对比 1.07、色散 0.0009。
* `render/shaders/scene.frag`：`u_style == 6` 分支 —— 菲涅尔边缘亮线、高光微提、亮部偏暖/暗部偏冷、
  天空补光 + 环境反射（黑枪也能看出形体）、黑位轻抬。
* `render/shaders/post.frag`：新增 `u_contrast`（放在 sRGB 之后做，暗部不会被压死）与 `u_ca`
  （径向色散，三通道分离采样）。
* 默认风格改成 `game`（`SceneState.style`、`MeshViewer.__init__`、`fallback_view`、
  检查器下拉第一项「游戏影视 Game」）。
* 灯光调亮一档：`render/lighting.py` 的 `ambient_top` 0.26/0.31/0.42 → 0.30/0.35/0.46、
  `ambient_bottom` → 0.10/0.093/0.085、`env_intensity` 1.0 → 1.15。
* 对比图：`work/_look_compare.png`（旧 PBR vs 新 Game，同一把 M4A1 官方配件）。

## 14. 瞄具吸附导轨（2026-10-31）

`core/gunsmith.py` 新增 `_lod_bounds_after()` 与 `_snap_optic_to_rail()`：`resolve_placements()`
给瞄准镜挂好 socket 后，再量一次「瞄具底面 − 父件顶面」，偏差超过 1.5cm 且水平位置确实压在父件上时，
沿 Y 平移贴回导轨。实测 M4A1/ScarH/AK12 的瞄具从 −0.8cm 收敛到 −0.3~−0.8cm 区间内不动，
悬空的那些则被拉回。`tools/_optic_scan.py` 可以批量体检（`python tools/_optic_scan.py 24`）。

## 15. HyperOS 光斑背景（2026-11-01）

需求：开屏卡片和向导页的背景改成 `file:///D:/HyperOS.html` 那种「黑底 + 四团流动柔光」。

原版是 WebGL 片元着色器：四个点 `(sin/cos)` 缓慢游走，半径按 UV 单位算（屏幕上就是椭圆），
叠加后用柏林噪声提亮。Qt 里没法直接跑它，所以在 `app/glow.py` 里用 `QPainter` 复刻：

* `render_glow(w, h, time_s, palette="dark", strength=1.0, divisor=3)` —— 先画到
  `w/divisor × h/divisor` 的小图上（省 CPU），每个球 `translate(cx*w, cy*h); scale(rw, rh)`
  再画单位圆 `QRadialGradient`，得到椭圆柔光；色标 0 / 0.30 / 0.62 / 1.0 = α(235·strength) / .88 / .42 / 0；
  最后叠一层径向暗角把四角压回黑。
* `paint_glow(painter, rect, time_s, ...)` —— 直接画到控件上（内部按 rect 尺寸走上面的流程）。
* 两套调色板：`POINTS_DARK/COLORS_DARK`（深夜蓝紫 + 洋红 + 暖橙）、`POINTS_LIGHT/COLORS_LIGHT`（粉紫奶油）。
* `class GlowBackdrop(QWidget)` —— 30fps 自增时间轴的背景控件，备用。

接线：
* `app/wizard.py::_Backdrop`：`paintEvent` 不再画 `wizard_base` 整图，改成
  `paint_glow(painter, self.rect(), self._glow_t, "dark", 1.0, 1.0)`；`__init__` 里挂了
  `QTimer(33ms)` 推进 `_glow_t`，`showEvent/hideEvent` 起停。三条 45° 带子照旧画在光斑之上。
* `app/splash.py::_Card.paintEvent`：先填原渐变、再压一层 `QColor(5,6,10,168)` 把底压暗，
  然后 `paint_glow(..., "dark", 0.95, 0.95)`，时间取自 `self._phase`（和底部四个点同一节奏）。
  ⚠️ 踩过的坑：这里最初抛 `NameError` 被 `try/except: pass` 吞掉 —— `app/splash.py` 顶部
  **忘了 `from app.glow import paint_glow`**，所以「改了没效果」。现在导入已补、except 也去掉了。

验证：`work/_glow_preview.png`（开屏卡片 + 向导页），打包版实机也确认过（`1.0+2026-11-01.0031`）。

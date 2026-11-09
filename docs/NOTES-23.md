# NOTES-23 改枪台：按游戏真实挂点（socket）装配

> 上一版改枪台把配件「缩放 1 / 位移 0 / 旋转 0」直接叠在机匣上，理由是
> `NOTES-21.md` §21.2 认定「该游戏资产没有 socket 数据」。**这个结论是错的**：
> 挂点数据不在网格资产里，而是单独存在几张 DataTable 里。本节记录完整的逆向
> 过程、数据结构、以及现在的实现。

## 23.1 结论速查

| 问题 | 结论 |
| --- | --- |
| 挂点在哪 | `Content/DataTables/WeaponPart/WeaponPartsMeshSocketNameInfo.uasset`（20270 行，mesh → 挂点名 + 位置 + 朝向） |
| 挂点名怎么分类 | `Content/DataTables/WeaponPart/PartSocketsTable.uasset`（80 行，`SocketId → SocketName → SocketPartType`） |
| 官方预设装什么 | `Content/DataTables/WeaponPart/GunDescTable.uasset`（46694 行 / 3991 个 DesId，装配树） |
| 官方尺寸怎么验 | `Content/DataTables/WeaponPart/GunPresetBoundsTable.uasset`（每个预设的 FBoxSphereBounds，cm） |
| 坐标系 | UE 系 x 右 / **y 枪口方向** / z 上，单位 **cm**；loader 的 GL 系 x = UE y、y = UE z、z = -UE x，单位 **米** |
| 配件自身原点 | **就是它的挂点**，所以「把原点对齐到父件 socket」即等于游戏里的位置 |

## 23.2 `WeaponPartsMeshSocketNameInfo` 的结构（踩过坑的地方）

每行的 key 是网格包路径（全小写、`/Game/Models/.../xxx_3P.xxx_3P` 形式）：

```
ItemId        : UInt64
SocketNames   : Array<FName>
SocketLocation: Array<Struct>     ← 见下，别按普通数组读
SocketRotation: Array<Struct>
RootBoneName  : Name
RowDescription: Name
```

`SocketLocation` / `SocketRotation` 在 uexp 里的实际布局是**反直觉的**：

```
[i32 count][tag 49B][count × 12B 元素]
tag = name(8) type(8) size(4) aidx(4) structname(8) guid(16) hasguid(1)
```

也就是说数据起点是 `vstart + 4 + 49`，而不是「count 后面直接跟元素」。
校验式 `vlen == 53 + 12 * count` 对全部 20270 行成立（0 例外）。
`SocketRotation` 是 **FRotator（度）**，顺序 `(Pitch, Yaw, Roll)`。

## 23.3 挂点名 → 部件族（`PartSocketsTable` 节选）

```
1 PisG_point       PistolGrip        2 Bar_point    GunBarral
3 Sto_point        Stock             4 Han_point    Handguard
5 Mag_point        Magazine          6 Muzzle_point Muzzle
7 FSig_point       ForSight          8 For_point    Foregrip
9 Rea_point        Sight            11 Sco_point    Sight
13 ScoB_point      Sight            14 Common_point TacticalDevices
21 Mou_point       SightBase        27 Han_point_alt Handguard
31 sco_secondary_point Sight        36 BarBip_point Bipod
39 BarKit_point    GunBarral        67 Sto2_point   Stock
72 Bar2_point      GunBarral        77 Muzzle2_point Muzzle
```

M4A1 机匣（`Rec_AR_M4A1-Std_001_3P`）上 38 个挂点，关键几个（UE cm）：

```
Bar_point (0,16.220,8.128)   Han_point (0,16.241,8.168)   Sto_point (0,-4.343,8.036)
PisG_point(0, 2.373,3.197)   Mag_point (0,11.650,5.070)   Sco_point (0, 8.195,10.904)
```

**所有挂点 socket 的旋转都是 (0,0,0)**，所以装配基本只有平移；单个动画 socket
（`Gun_Cover` / `FireModeBone` 之类）才带角度。

## 23.4 `GunDescTable` 的装配树

```
DesId(预设) → 多个节点：Index, ParentIndex, ItemId, ParentSocketId, SocketId, Child, NodeType
```

* `ParentIndex` 指向父节点的 `Index`（根的 `ParentIndex = 0`）；
* 子节点的 `ParentSocketId` 就是「插在父件的哪个挂点」；
* 同一 DesId 的 `DesKey` 会重复（0,1,2…），**不能拿 DesKey 当分支**，按 `Index` 去重；
* 机匣节点会以多行出现（每行声明父件的一个插槽），`ParentSocketId = 0` 的那行是根。

实例子（HK416C 预设 `10010001045`）验证了父子链：

```
机匣 rec_ar_hk416_021                      ← 根
├ Han_point  han_hk416_hk416c_104
│   └ For_point  frog_pic_mag-afg_003      ← 前握把挂在护木上
├ Bar_point  bar_s-260_m4a1-compatible
│   └ Muzzle_point  muz_m-f_m14_051        ← 枪口挂在枪管上
├ PisG_point pisg_b_nar-grals_003
├ Sto_point  sto_a_hk416c_041
├ Mag_point  mag_556-45-45r_polymer
└ Sco_point  sco_ho_holo-553_043
```

## 23.5 现在的实现

| 文件 | 作用 |
| --- | --- |
| `core/sockets.py` | 解 `WeaponPartsMeshSocketNameInfo` + `PartSocketsTable`；`sockets_of()`、`socket_matrix()`、`item_meshes()`、`item_of_mesh()`、`socket_id_name()`；缓存 `%LOCALAPPDATA%/VertexViewer/weapon_sockets.json` |
| `core/presets.py` | 解 `GunDescTable` + `GunPresetBoundsTable`；`nodes_of()`、`bounds_of()`、`presets_of_item()`；缓存 `weapon_presets.json` |
| `core/bbox.py` | 网格包围盒缓存（`bbox_cache.json`），装配拟合用 |
| `core/part_offsets.json` | **伸缩托伸展量**标定（见 23.7），由 `tools/calibrate_parts.py` 生成 |
| `core/gunsmith.py` | `find_socket()` / `resolve_placements()` / `assemble()`：按挂点链算世界矩阵；`preset_loadout()` 从 `GunDescTable` 抄官方配置 |
| `tools/check_gunsmith.py` | 端到端回归：拼出来的包围盒 vs `GunPresetBoundsTable` |
| `tools/calibrate_parts.py` | 用官方包围盒反推伸缩托伸展量 |
| `tools/verify_assembly.py` | 纯表驱动的装配验证（不经过 gunsmith 的猜测逻辑） |

`assemble()` 的计算顺序：

```
world(配件) = world(父件) · socket_matrix(父件, 挂点名)
            · part_offset(配件)      ← 伸缩托伸展量（GL 米）
            · user_offset · user_rot
顶点           = 顶点 · scale · Rᵀ + t
```

父件链：`muzzle → barrel`、`foregrip → handguard → barrel`、`bipod → barrel`，
其余都挂机匣；父件不存在时退回机匣，再没有就包围盒兜底。

## 23.6 这些件为什么还是差几厘米

`GunDescTable` 里的节点给的是**道具 ID**（13xxxxxxx），不是网格路径。而
`WeaponPartsMeshSocketNameInfo` 只收录「自己有挂点」的网格，两者的交集只有
1945 个道具 ID / 20270 个网格。剩下的是**虚空道具**：

* 例：M4A1 预设里的枪托道具 `13040000114`、握把 `13030000109` 在挂点表里查不到；
  挂点表里 M4A1 的枪托是 `13040000141`（`Sto_A_M4A1-Std_001`，中文名还标着「虚空物品」）。
* 例：P90 的默认枪托 `Sto_B_P90-Std_014` 在包里**只有皮肤变体**
  （`Commerical/WeaponAppear/.../Sto_B_P90-Std_014_<皮肤>_1P`），基础 3P 网格压根没有。
* 全库统计：`Bar` 缺 1350/3013、`Han` 680/2531、`Sto` 625/2582、`Sco` 512/2629，
  214 个道具 ID 完全没有网格。

处理办法（`guess_part_vpath` + `_arrange_void_parts`）：

1. 先按「同一把枪」找候选：部件名前缀匹配族（`Sto_` / `Bar_` …）且包含枪型号码
   或 ≥3 字符的型号片段（`AR` / `Std` 这类通用词不算）；
2. 多个候选时用**官方包围盒**挑：逐个替换、算整体 AABB、取与
   `GunPresetBoundsTable` 偏差最小的组合（坐标下降，最多 2 轮）；
3. 实在没有同枪候选就**留空**，宁可少件也不塞别的枪的模型。

## 23.7 伸缩托：唯一需要标定的东西

有些枪托在游戏里默认是**拉出一段**的（HK416C 托、HK437 托、AM17 托……），
这段伸展量不在任何数据表里。用官方包围盒反推（`tools/calibrate_parts.py`，
700 个预设、2 轮中位数过滤）：

```
sto_a_hk416c_041   n=9   -12.22cm     sto_t_hk437_136      n=6    -9.18cm
sto_s_ak19_109     n=2    -7.47cm     sto_s_ar57std_167    n=2    -7.21cm
sto_a_m4a1-std_001 n=2    -7.13cm     sto_t_am17_141       n=12   -5.08cm
sto_s_frame_114    n=2    -3.50cm     sto_t_mk47_156       n=5    -1.94cm
sto_a_sig1_094     n=3    -1.44cm     sto_s_cqr2_112       n=2    -1.39cm
sto_a_slimline_085 n=6    -0.79cm     sto_s_advanceart_160 n=2    -0.77cm
```

只标定 `/sto/` 族：枪管 / 枪口 / 瞄具的挂点摆法本身是精确的（26/40 个预设
< 0.3cm），出现残差一定是预设里缺件，硬标定会把正确位置拽歪。

## 23.8 当前回归结果（`python tools/check_gunsmith.py`，阈值 1.5cm）

```
OK   0.31 MP5A4      0.61 ScarH        0.77 M4A1-Std     0.79 P90
     0.81 AK12       0.82 Ash12        0.86 QBZ191       0.91 QBZ95 / AUGA3
     0.97 AK74       1.14 G3 / HK437   1.35 MCX_044      1.36 HK416
     1.38 AR57
BAD  1.56 DTMDR      1.72 Uzi         2.00 RM277        2.10 MK47
     2.22 AM17       2.57 MCX_070     3.38 M16A2        4.72 SG553
    10.73 CAR15
```

* 15/24 在 1.5cm 内（其中 12 个 < 1.4cm，肉眼零差别）；
* 剩下的 BAD 全是「默认枪管 / 默认枪托的网格不在包里」的枪：CAR15 的
  默认枪管道具 `13020000584` 连皮肤变体都没有，前端直接短 10.7cm；
* 这些枪在界面上手动换一根存在的枪管（模型库里列出来的都是包里真有的）之后，
  位置立刻正确 —— 因为位置是挂点算的，跟哪根枪管无关。

## 23.9 复现步骤

```bash
python tools/dt_dump.py WeaponPartsMeshSocketNameInfo Rec_AR_M4A1-Std_001_3P   # 看某个网格的挂点
python tools/_sockets_map.py                                                  # 打印 SocketId → 名字 → 部件类型
python tools/calibrate_parts.py --limit 700                                   # 重标定伸缩托
python tools/check_gunsmith.py                                                # 批量回归
python tools/check_gunsmith.py "Rec_AR_M4A1-Std_001_3P"                       # 单枪明细
python tools/verify_assembly.py --auto 40                                     # 纯表驱动验证
```

首次跑任意一个都会重建缓存（`weapon_sockets.json` 4~6s、`weapon_presets.json` 5.8s），
之后毫秒级。

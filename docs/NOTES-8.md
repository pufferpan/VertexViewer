## 8. 检视动画：全库重扫（2026-10-25 第五轮）

上一轮只认 `Knife_Prop_View_*` 放在 `ANI/` 下的那一种写法，所以只找到 4 件。
用户让再找，于是改成从**类名目录**反查，结果是**远不止 4 件**。

### 8.1 扫法

`work/mesh_catalog.json` 里有全库 62709 条 `{资产路径: 类名}`，其中
`AnimSequence` 12852 条、`AnimMontage` 3888 条。

`core/loader.py::inspect_animations()` 现在这样建表：

1. 从 catalog 分出「动画」和「网格」两拨；
2. 每条动画往上最多 4 层，找到**第一个含网格的物品目录**（动画会放在
   `ANI/`、`Ani/`、`Anim/`、`Animation/`、`Anims/`、`Ainm/`、`anmi/`、`Body/`、`Weapon/`
   这些五花八门的子目录里，所以不能只看一层）；
3. 过滤：物品目录（`Props/Collect`、`Props/Med`、`Props/Food`、`Props/Tactical`、
   `Equipments`…）里的动画**全收**；其它目录只收名字里明确有
   `view`/`inspect`/`examine` 的（`_Show` 那种角色展示动作不算）；
4. 键 = 该目录里每个网格的文件名（`props_collect_Echains_1320_1P`），
   同时登记去掉 `_1P/_3P/_UI/_HD` 的别名，卡片传任意变体都能命中。

### 8.2 结果（比上一轮多两个数量级）

- **228 个物品目录**（去重）、**691 个网格变体**、**867 条动画资产**。
- 名字里带 `Inspect` 的 **266 件**（绝大多数是武器/近战）：
  `Melee_M_Knife_FairbairnSykes_1P_Idle_Inspect`、`PT_M_GLOCK18C_1P_Inspect_Bar`、
  `Bar_M-330_MCX_045_TranAttack_ni_1P_Inspect` …
- `Knife_Prop_View_*` 那一族 **90 个网格**（收藏品 + 少量武器皮肤）。
- `Gesture_*` 手势把玩 **7 件**（如 `Prop_Collect_Stethoscope_1392` →
  `Gesture_C103_Stethoscope_2c_B_1P`）。
- 开合/循环类 **85 件**：红包 `Prop_Collect_Envelope_1393`（35 条，上/下/左/右/loop/end）、
  转盘 `FortuneWheel_1405`（14 条）、盖革计数器 `Porps_Tactical_Geiger_1471`（11 条）、
  巢穴 `SM_Feature_Nest_01`（Open/OpenIdle/Close）、降落伞 `Parachute_Player_001`（22 条）…
- 其余 **243 件**是各物品自己的小动画（鱼、马火箭、火箭小人、台球、医疗包、食物…）。

### 8.3 UI 表现

- 卡片副标题出现 `▷ 检视`（tooltip 里写具体动画路径）——现在覆盖 691 个网格变体；
- 加载这些物品时自动播「同节奏转台」，检查器按钮「播放中 · 3.2s / 点击停止」；
- 实测三件新物品（真 GL 窗口）：
  `Knife_FairbairnSykes_001_1P` 4474 tris / `SM_Feature_Nest_01_3P` 2141 / `Bar_PT-113_Glock18CStd_068_1P` 2692，
  三件都 `playing=True`。

### 8.4 踩到的坑

- `inspect_anim_for()` 建缓存时把键统一转小写、但没登记「去变体后缀」的别名，
  导致传 `Knife_FairbairnSykes_001_1P.uasset` 全 miss。现在两种键都登记。
- 一开始把 `MilitaryProps`/`BattlefieldProps` 也算成物品目录，结果「技能道具的使用动画」
  （投放、架设、开火）全被算成检视，物品数虚高到 1044 —— 这两个目录已从 `_ITEM_DIRS` 移出。

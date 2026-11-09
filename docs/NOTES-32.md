# 改枪装配为什么会错位（NOTES-32）

## 现象

所有枪型的「改枪」页都会出现配件错位：枪托和机匣之间有缝、握把/弹匣垂在半空、
导轨上堆着两三个瞄具、机匣前下方挂着一块不知名的件。

## 三个根因

1. **父件信息被丢掉了。**
   `GunDescTable` 的预设节点是 `[索引, 父节点索引, 道具ID, 父挂点索引]`，也就是
   「这件挂在谁身上」写得很清楚。原实现只取了挂点名，父件没进 `PartSpec`，
   装配时按族名（`PARENT_FAMILY`）反猜父件。导轨件用的 `Common_point` /
   `RailCL_point` 在机匣和护木上都有同名点，猜错就挂到另一根导轨上——所以表
   现为「全枪型差几厘米」。

2. **同族换件换过头。**
   预设里把「握把底座」写成 `other_psgbass1_076`、「弹匣底板」写成
   `other_quickdraw55645_087`，它们挂在 `GripBass_point` / `MagBass_point` 上。
   原来的换件逻辑看到「挂点族 = grip/mag」就把网格换成整只握把、整只弹匣，
   于是枪上多出第二只悬空的握把和弹匣。

3. **伸出量没有数据来源。**
   socket 只给「插入点」，伸缩托拉出多少、两脚架转下来多少、消音器拧多深，
   这些记在 `GunPresetBoundsTable` 的官方包围盒里，之前完全没用上。

## 修法（core/gunsmith.py）

| 位置 | 改动 |
| --- | --- |
| `PartSpec` | 增加 `parent_item` / `parent_socket_id`（`to_dict` / `from_dict` 同步） |
| `preset_loadout` | `node_item_of` 记录「节点索引 → 道具 ID」，把父件写进每件方案；最后 `_dedupe_major` 去掉同族重复 |
| `resolve_placements` | 优先按预设父件挂；同名挂点有多个拥有者时逐个试装，贴住才采纳；父件没摆好就等下一轮 |
| `_snap_mount_face` | 挂点只给点，按族把「该贴的面」贴到父件（枪托前端贴机匣后端、枪口后端贴枪管前端、握把/弹匣上沿贴机匣下沿）；1mm 以内不动、30cm 以外不动、另两轴差 >6cm 不动 |
| `_dedupe_major` | 枪托/枪管/护木/枪口/握把/前握把/两脚架只留第一件；弹匣、瞄具允许两件 |
| `_fit_to_official` | 用官方包围盒对齐六条边，只平移顶在该边上的那一件；**会把它从父件上拽开就不挪** |
| `_close_mount_gaps` | 收尾扫一遍：8cm 以内、另两轴确实对得上、只差一个轴向的缝，直接贴平 |

## 验证

- `probe_gs_scan.py`（每件到最近一件的间隙，118 把主件枪，阈值 3cm）：
  `checked=85 guns_with_floaters=0`。
- `probe_gs_overlap.py` 去噪后：同族重复 4 把 → `_dedupe_major` → 0 把。
- 官方包围盒偏差：M4A1 7.13 → 1.66cm，AK12 12.95 → 1.63cm，CAR15 4.70 → 0.47cm。
  剩下的 1–2cm 是官方预设用了长度不同的同族件（例：AK12 的短托），
  硬拉齐只会把件从机匣上拽开，所以选择「贴住优先」。
- 渲染肉眼确认：M4A1 / AK12 / HK416 / QBZ95 / MCX / M14 / Minimi / AW / M82 /
  LeverAction / AM17 都没有悬空件、没有重复瞄具。
- 单测 41 项全过（新增 `tests/test_gunsmith_fit.py` 5 项：同族去重、弹匣/瞄具保留两件、
  悬空件贴回、远距离不动）。

## 调试入口

- `VERTEXVIEWER_NO_FIT=1` 关掉官方包围盒对齐（对比用）。
- `VERTEXVIEWER_NO_FIT_GUARD=1` 关掉「不许拽开父件」的护栏（对比用）。

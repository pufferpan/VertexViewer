# 改枪错位：逐表核对（XM250）

用户反馈「M250 还是错位」。游戏里这把枪叫 **XM250**（LMG，主件
`Rec_LMG_XM250_056`，道具 `18040000003`），所以先按「游戏档案 ↔ 软件」
一项一项对，再看差在哪。

## 之前为什么会错

`GunDescTable` 的预设节点给的是**道具 ID**，软件把道具 ID 换成网格走了两条路：

1. `WeaponPartsMeshSocketNameInfo`（挂点表）——只收录「自己带挂点」的网格；
2. 查不到时按「枪名 + 部件族」猜名字（`guess_part_vpath`）。

XM250 的预设（DesId `10040001537`）里有三件走了第 2 条：

| 节点 | 道具 ID | 我们猜的 | 游戏里其实是 |
| --- | --- | --- | --- |
| 枪托 | `13040000110` | `Sto_A_XM250STD_090`（错） | `Sto_A_UBR2_036` |
| 战术灯 | `13160000005` | 直接丢了 | `Dev_LAM_peq2_008` |
| 机匣 | `18040000003` | 正确 | `Rec_LMG_XM250_056` |

枪托猜错让整枪**短了 8.76cm**（官方包围盒对不上），少一件则直接缺了 PEQ-2。

## 改了什么

1. **新增 `core/items.py`：道具 ID → 网格的权威表**。
   游戏自己的 `DataTables/CommonItemAsset/CommonItemAssets_Weapon.uasset` 里，
   每行以道具 ID 为键，带 `Item1PMeshPath` / `Item3PMeshPath` / `ItemUIMeshPath`。
   缓存到 `%LOCALAPPDATA%\VertexViewer\item_meshes.json`。
2. `preset_loadout()` 先问这张表，再退回挂点表，最后才按名字猜。
   XM250 因此从 12 件变 13 件，枪托换成 UBR2。
3. `_push_barrel_out()`：枪管整根被机匣盒包住时（XM250 的短机匣布局，
   `Bar_point` 在机匣中部），沿枪长把它推到露出 2cm，挂在它上面的枪口跟着走。
   正常枪（枪管本来就在外面）不触发。
4. 瞄具改按导轨面采样落座（`_seat_on_surface`），不再只信 `Sco_point`
   ——XM250 的 `Sco_point` 在枪身中线，照它摆会把瞄具压进机匣 5.6cm。

## 一对数字（GL 米，越接近 0 越好）

官方预设包围盒 `10040001537` 逐边误差：

| 边 | 改前 | 改后 |
| --- | --- | --- |
| 枪尾 x- | +8.76cm | +1.82cm |
| 枪口 x+ | -7.44cm | -0.63cm |
| 底面 y- | -0.09cm | -0.09cm |
| 顶面 y+ | +4.65cm | +4.65cm（瞄具叠高，属造型） |
| 两侧 z | ±4.93cm | ±4.93cm（75 发弹鼓本来就比机匣宽） |

## 验证

- `python -m unittest discover -s tests` → `Ran 41 tests ... OK`
- 渲染：`gs-shots/big/Rec_LMG_XM250_056_3P.png`（侧视 1600x700）、
  `gs-shots/xm250-front.png`（前视 1200x700）、`gs-shots/xm250-zoom.png`（局部）
  ——枪管伸出、枪口在外、UBR2 枪托贴住机匣、PEQ-2 在护木右侧、弹鼓在机匣下。
- 同批回归：M4A1 / HK416 / Minimi / AW / M82 / LeverAction / AM17 / DTMDR
  的包围盒误差都在 2~6cm 内，没有因为这次改动恶化的枪。

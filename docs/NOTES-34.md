# NOTES-34 剥离游戏派生素材 + 代号生成显示名

## 为什么改

仓库里原来直接跟踪了四类从游戏包里抽出来的东西：`Weapon.locres.bin`、
`Auctioneers.locres.bin`（本地化表明文）、`work/names.json`（9,933 条物品名，
条目里带 `src: LOC_CommonItemAssets_Vehicle:39001101001` 这种指向）、
`work/icons.db`（2,491 张物品图标 PNG，11MB）。这些都是游戏的美术/文本资产，
放在公开仓库里就是复制发行，和「工具本身」是两码事。

## 做了什么

1. **删除**：`Weapon.locres.bin`、`Auctioneers.locres.bin`、`work/names.json`、
   `work/icons.db`；`.gitignore` 里加 `work/icons.db`、`work/names.json`、
   `*.locres`、`*.locres.bin`、`*.ustbin`，防止以后又被带进来。
2. **新增 `core/humanize.py`**：从资产代号拼显示名，词典是本仓库自己的通用词
   （机匣/枪管/枪口/弹匣/枪托/护木/瞄具/两脚架/消音器/补偿器…），不读任何游戏文本。
   - `Rec_AR_M4A1-Std_001_3P` → `M4A1 机匣`
   - `Bar_AR-227_SG553-Std_015_1P` → `SG553 枪管`
   - `Muz_M-S_M250Silencer_097_3P` → `M250 消音器 枪口`（驼峰里的型号+词会拆开）
   - `Prop_Collect_5C5P2_up_1479_1P` → `5C5P2 藏品`（通用类别词在有描述词时不重复）
3. **兜底接线**（`core/cnnames.py`）：`resolve_cn()` 名字表查不到就返回 humanize 的
   结果；`category_of()` 没有名字时也用同一套显示名判类，避免整库落到「其他」。
   `CAT_RULES` 的配件组补了 `机匣 / 两脚架 / 前握把 / 消焰器 / 补偿器 / 护盖 /
   战术装置 / 后照门`，让生成名能正确归到「配件」。
4. **打包脚本**：`VertexViewer.spec` 的 `WORK_FILES` 去掉 `names.json`，
   删掉 `icons.db` 的 datas 条目；`tools/package_source.py` 的必含清单同步
   （数据文件改成「存在才收」），源码包不再要求 locres/图标库/名字表。
5. **文档**：`README.md` 的功能表第 7、8 行与「产物里带什么」小节改写；
   `README-source.md` 的包内内容同步。

## 影响

- 界面默认显示「型号 + 部件」的生成名，图标是分类色块 + 首字（`app/browser.py`
  的 `placeholder()`，本来就有）。
- 想用游戏原名：使用者自己把 `names.json` 放进 `work/`（或 exe 旁 `data/`）即可覆盖，
  仓库与安装包都不提供。
- 图标同理：`I:\Game\UIIcon` 指到自己导出的目录，或 `VERTEXVIEWER_ICONS` 指定。
- 单测 `Ran 49 tests ... OK`，其中 `tests/test_humanize.py` 8 项专门盯生成名。

## 未动的东西

- `work/mesh_catalog.json`（路径→类名）、`work/pakinfo.json`（pak 元数据）仍在仓库里：
  它们是索引元数据，不含美术/文本表达，删掉会让首次索引慢一截。
- 代码里的 `DeltaForce/Content` 路径常量：UE pak 挂载路径，删了读不了包。

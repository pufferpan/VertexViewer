# VertexViewer — 项目现状备忘（给协作 agent / 未来自己看）

> 该游戏模型查看器。所有结论都是在本机实测出来的，别重新踩。

## 0. 环境

| 项 | 值 |
|---|---|
| python | 3.12.10，`C:\Users\32816\AppData\Local\Programs\Python\Python312\python.exe`（PATH 里的 `python`） |
| 已装 | **PySide6 6.12.0**（+Addons/Essentials/WebEngine）、numpy 2.3.5、Pillow、cryptography、pycryptodome |
| pip 源 | 必须用 `-i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com`（清华源对 pyside6 返回 403，pypi.org 不通） |
| 网络 | `github.com` / `api.github.com` 通；**raw.githubusercontent.com 不通**，要取 GitHub 文件走 `https://api.github.com/repos/<owner>/<repo>/contents/<path>` 拿 base64；`git clone` 会 `early EOF` 失败 |
| 游戏 | `G:\Game\Game\Game\`（110G） |
| paks | `G:\Game\Game\Game\Content\Paks\` 344 个 .pak，84G，纯 legacy pak（**没有 .utoc/.ucas**） |
| Oodle DLL | `G:\Game\Game\Game\Binaries\Win64\oo2core_8_win64.dll` |
| AES 密钥 | `G:\xmcl-fetch\work\AESKey1.json`（源 https://github.com/Alpace123/AESkey ，取 `$.['MainKey','Keys']`，200 条） |
| 全局文件索引 | `G:\xmcl-fetch\work\fileindex.json`：`{virtual_path: [pak文件名, location]}`，257 个 pak / 93 万条（部分 pak 未索引，缺了再跑 `tools/list_all.py`） |

## 1. pak 容器格式（已完全破解，别改）

`core/pak.py` 是唯一实现，直接用：

```python
import sys; sys.path.insert(0, r"G:\xmcl-fetch\vertexviewer")
from core.pak import PakFile, load_keyvault

vault = load_keyvault(r"G:\xmcl-fetch\work\AESKey1.json")
pak = PakFile(r"G:\Game\Game\Game\Content\Paks\pak-0-2-pakchunk61-WindowsClient.pak", vault)
print(pak.info())            # key guid / mask / 文件数 / mount / 压缩方法
data = pak.read(vpath, oodle)   # vpath 形如 "../../../DeltaForce/Content/Models/..."
pak.close()
```

要点（踩过的坑，别重复验证）：

1. **footer 204 字节**在文件末尾：`u32 magic 0x5A6F12E1 | u32 version=11 | i64 index_offset | i64 index_size | u8 sha1[20] | char methods[5][32]`。
   没有 bEncryptedIndex、没有 EncryptionKeyGuid（读出来恒 0）。
2. 每个 pak 的 **AES key 是 Keys[] 200 条里的某一条**（MainKey 用不上），**mask 是每 pak 不同的单字节**。
   `PakFile` 会自动用「201 key × 256 mask」爆破并缓存（`PakFile._key_cache`），一个 pak 约 0.1~1s。
3. 解密公式（= CUE4Parse `GameTypes//Encryption/Aes/DeltaForceAes.cs`）：
   `plain = AES-256-ECB-decrypt(cipher, pak_key)` **再整段 XOR mask 单字节**。
   index 的 mask 可从明文首字节反推（seed 为 0 ⇒ `mask = decrypted[0]`）；**文件数据用同一个 mask**。
4. 索引内层是 **bit-packed FPakEntry**（UE4 `FPakFile::DecodePakEntry`），不是定长数组：
   `flags u32`（bit22=encrypted, bit23=compressed）→ offset / uncompressed / 三选一的 compressed+blocksize → 可选 SHA1。
5. **加密条目在磁盘上按 16 字节对齐**：`usize` 可能是 835 这种非对齐值，要读 `align16(csize)` 再解密后截断。
6. 压缩统一是 **Oodle**（methods 表 `['None','Oodle']`），用 ctypes 调 `OodleLZ_Decompress`。
   现成封装：`tools/pakpick.py` 的 `Oodle()` / `oodle()` / `extract(vpath)`。
7. 单文件取用：`python tools/pakpick.py "<virtual path>" out.bin`。

**已验证**：pak-0-2-pakchunk61 + pak-0-1-pakchunk31 里 35536 个加密 .uasset 全部解出，magic `0x9E2A83C1` 正确。

## 2. uasset 版本信息（实测自解出的文件头）

```
0x000  u32 magic           = 0x9E2A83C1
0x004  i32 LegacyFileVersion = -517      (UE5 系列)
0x008  i32 LegacyUE3Version = 864
0x00C  i32 FileVersionUE4   = 522
0x010  i32 FileVersionLicenseeUE4 = 1
0x014  i32 FileVersionUE5   = 1004       (待解析确认)
0x018  i32 FileVersionLicenseeUE5 = 5
...
```
即 **UE5 包格式**：Summary 里有 `FileVersionUE5`、custom versions、`TotalHeaderSize`、
`FolderName`、`PackageFlags`、NameTable、Import/Export 表；Export 里属性用 UE5 的
`FPropertyTag`（含 `bHasPropertyGuid`、`FName` 带 UTF-8 fallback 等）。

样本文件已落盘方便直接开搞：
* `G:\xmcl-fetch\work\s1.uasset`、`G:\xmcl-fetch\work\enc1.uasset`（加密→解出的完整 uasset，835 字节，含 header 部分）

## 3. 目标资产位置（虚拟路径以 `../../../DeltaForce/Content/` 开头）

```
Models/<分类>/.../SM_xxx.uasset            静态网格
GenTexDirHD/Game/Models/<分类>/.../M_xxx/Textures/T_VMGen_*Map_<hash>.uasset   贴图
GenTexDirHD/Game/Models/<分类>/.../<模型名>/ 材质 json / UMaterialInstanceConstant
```
实测例子：
`GenTexDirHD/Game/Models/Characters/AI/HS/M_DT-Firebat_146/Textures/T_VMGen_BaseColorMap_44cb999d...uasset`
`Models/Weapons/Parts/Mag/Mag_AK74_545x39-30R-Std_004/SM_Mag_AK74_545x39-30R-Std_004_3P.uasset`

**模型与贴图的对应规则（用户原话）**：模型文件夹里可能有材质 json，材质实际文件夹在 `GenTexDirHD`，
与模型文件夹**一一对应**（`Models/X/Y/Z` ↔ `GenTexDirHD/Game/Models/X/Y/Z`）。需要实测确认命名/层级差异。

### 已知限制：87 个 pak 打不开
`tools/index_missing.py` 跑完 344 个 pak：**257 个能解开，87 个 `no key/mask matched`**——全部是
`*optional* / *uhd* / sensicommon_* / 1.103.37117.36.11_WindowsNoEditor_*.pak` 这类补丁包。
footer 格式与别的 pak 完全一致（magic/ver=11/Oodle），但索引用现有 200 条 key × 256 mask 解不出。
AESkey 仓库只有 AESKey1.json(25-09-04) 和 key.json(25-07-3)，都试过了 ⇒ **这批包要更新的 key，等上游更新**。
不影响模型：`Models/` 的 116760 条全在已解开的 257 个 pak 里。UI 里加载这批包时要给友好提示而不是崩。

## 4. 目录结构约定

```
G:\xmcl-fetch\vertexviewer\
  core\pak.py        pak 读取（已完成，别重写）
  core\types.py      共享数据契约：Mesh/MeshLOD/Section/Material/Texture/ModelBundle + ue_to_gl()
  core\uasset.py     ★ uasset 包头/名字表/Import/Export/属性解析（待写）
  core\mesh.py       ★ StaticMesh → MeshLOD（vertex buffer、section、.ubulk bulk data）
  core\texture.py    ★ Texture2D → RGBA（BC1/BC3/BC5/BC7 解码）
  core\material.py   ★ UMaterialInstanceConstant → Material（金属度/粗糙度等参数）
  core\cnnames.py    ★ 中文名映射（DataTable / .locres）
  cache.py           ★ 临时缓存目录管理（软件关闭即删）
  render\            ★ PySide6 OpenGL 渲染（PBR + 艺术化风格 + 灯光）
  app\               ★ FluentPy UI 主程序 + OBJ 导出
  tools\             探针脚本（一次性）
```

## 4.5 「贴图错位」的根因与修法（2026-10-25 已修，别回退）

**症状**：同一个模型，有时贴图正常、有时整张图上下颠倒（连拍两张截图不一样）；
`VERTEXVIEWER_NO_VFLIP` 开关看起来没作用（开关前后截图只有 0.13% 像素不同）。

**根因**：`render/viewer.py::prepare_lod` 里

```python
uv = np.ascontiguousarray(uv, np.float32)   # wrond: 这是 lod.uv_sets 的视图，不是副本
uv[:, 1] = 1.0 - uv[:, 1]                   # 原地翻 V ⇒ 把缓存里的 UV 数据改掉了
```

`uv` 来自 `lod.uv(channel)` 的切片，`ascontiguousarray` 对已是连续的切片**不复制**，
于是 V 翻转直接写回 `MeshLOD.uv_sets`。而 `mesh_bounds()`（取景/切 LOD/加载都会调）
内部也走 `prepare_lod`，`_sync_mesh` 每帧还会再调一次 ⇒ **奇偶次调用决定贴图朝上还是朝下**，
表现就是「贴图错位/忽正忽反」。

**修法**：必须真复制 —— `uv = np.array(uv, dtype=np.float32, copy=True)`。
回归探针：`python tools/uv_probe.py`，它会
① 连调 3 次 `prepare_lod`/`mesh_bounds` 检查 UV 数据是否被改写；
② 用 4 象限色贴图验「左上=红 右上=绿 左下=蓝 右下=黄」（UE 口径 v=0 在图集顶部）。

**顺带修的**：
- `_sync_mesh` 的缓存 key 以前用 `id(state.mesh)`，CPython 地址复用会「换模型后还显示上一个」，
  改成 `(lod_index, mesh_version, uv_channel)` + 对象身份比较。
- `_as_texture_array` 不认 `_OverrideTexture` 包装 ⇒ `set_texture_override` 静默失效
  （调试图换不上去，看着像「贴图没生效」），现在同时接受带 `.rgba` 的对象。

## 4.6 UV 通道（多套 UV）

该游戏的网格普遍带 2~3 套 UV（`Counter({2:4, 3:1})` 抽样）。`MeshLOD.uv_sets` 现在存
`(N, tc, 2)` 全通道，`MeshLOD.uv(channel)` 取某一套，检查器「显示 → UV 通道」下拉可切换
（`MeshViewer.set_uv_channel`）。切错通道时贴图还在、但整块位置全错 —— 这正是排查
「贴图错位」时必须能当场对比的东西。`.uemodel` 只存一套 UV，`load_mesh` 往返后会把
`uv_sets` 从原网格补回。

## 4.7 模型中文名（StringTable 才是主力文本源，别只看 locres）

- 资源：`/DataTables/` 的 `.uasset` 4042 个、StringTable 的 `.ustbin` 855 个、
  `.locres` 496 个。
- **locres 不够用**：locres 的 key/namespace 里不含资产 stem（拿 `MagFollower_54539_012`
  这类去搜是 0 命中），所以「用 locres 反查缺名字的模型」这条路走不通；
  locres 还比 StringTable 少 74 个 namespace、5046 个 key。
- `.ustbin` 是真包（首 4 字节 `0x9E2A83C1` = uasset magic），布局：
  `[0:48)` 包头 + `[48:]` zlib；解开后是
  `i32 size / u16=2 / u16 表名哈希 / FString table_name / i32 row_count /`
  `逐行 FString key + FString text`，**行间偶尔夹 4 字节哈希**，所以必须带重同步
  （长度不合理就 `pos += 1`）。实现见 `tools/ustbin.py::parse_ustbin`。
- 名字来源的真相：DataTable 的**同一行**里既有 `TextProperty`（namespace + key，
  如 `15200000056_Name`）又有 `SoftObjectPath`（如
  `.../props_collect_Catgoods_1199_3P.props_collect_Catgoods_1199_3P`）。
  但很多行只有路径没有文本、或者文本在别的表里，所以 `tools/harvest_names2.py`
  走三步合并：①同行配对（conf 0.95/0.75）②按行号跨表补齐（conf 0.7/0.5）
  ③派生名兜底（conf 0.35，`derived=True`）。
- 踩过的坑：跨表补齐一开始把 `props_keycard_Dam_Gold_710` 配成「耐久度：20」
  （挑到了 `15050300001_SimpleDescription`）。修法是 `_rank()` 打分：
  字段名在 `NAME_KEYS` −4、key 以 `_Name` 结尾 −3、key 前缀等于行号 −6、
  对不上 +4、带 desc/attribute/tip/hint/_shortname/_subname +5（并直接跳过）。
  修后 →「东楼经理室」；`props_collect_Catgoods_1199_3P` →「小猫饰品」。
- 另一个坑：`texts_by_id` 里存 `(字段名, namespace, key)` 三元组时字段顺序写错
  （存了 `(ns, key, table_path)`），`key.startswith(row_name)` 永远 False，
  会造成「明明有名字却全丢」——查覆盖率先确认这个。
- 现状：`work/names.json` **9933 条 / 覆盖 7261/9443 个网格**；分类
  配件 5901 / 武器 1598 / 道具 1549 / 装备 381 / 载具 236 / 角色 74 / AI 50 / 其他 144。
- 还有一个坑：`LOC_BattleSectorTable` / `LOC_DisplayInputActionMappingSettings` 这类表
  同一个行号挂的是评级（A~F）或界面文案（返回/关闭），按行号跨表补齐会把枪管配成「C」。
  修法：`looks_like_name()` 过滤单字母/两字符以内的值 + 跨表补齐时跳过
  `DisplayInputAction/InputAction/Settings/Options` 这些 namespace 与 `/Curve/` 资产。
- 派生名只认「真实型号 + 部件」：家族名必须命中 `FAMILY_RE`（AK74/M4A1/AAV7…），
  部件词必须落在词边界上（`Butt` 能匹配 `Butt_02`，不能匹配 `Butterfly`）。
  早先按「第一个不是噪声的 token」当家族，会拼出 `SeasonQuest`、`Government`、
  `CCOLD` 这种把目录当型号的假名字，已废弃；拿不到就只显示「头盔」/「护甲」，
  再拿不到就留空让 UI 显示资产名。

## 4.8 模型库 UI（卡片视图，2026-10-25 重写）

- `app/browser.py`：顶部搜索 + 一排分类 chip（武器/配件/装备/道具/载具/角色/AI/其他）
  + 卡片网格（`_CardGrid` + `_ModelCard`，140x148，图标 58）+ 「合并变体」开关
  + 「目录视图」切换。
- **不要用 QListWidget 的 IconMode 铺卡片**：图标尺寸/文字换行混在一起时，
  `setResizeMode(Fixed)`、`setUniformItemSizes`、`setGridSize` 全都调不稳，
  实测会出现「一行一个、行距过大、文字被裁」。自己用 `QGridLayout` 按
  `cols = max(1, (width-12)//(CARD_W+8))` 排，`resizeEvent` 重排最省心。
- **分类 chip 不要用 Fluent 的 `PushButton` + `setFixedHeight(26)`**：会渲染成
  看不见字的小方块。改成 `QPushButton` + objectName `categoryChip` +
  `CHIP_ON`/`CHIP_OFF` 两套样式表。
- 卡片副标题 = `分类 · 变体`（`1P/3P/UI/LAY/HD`）；「合并变体」打开时同一件东西的
  多份网格只显示一张卡片，副标题写「N 个变体」。
- 排序 `_sort_key`：`(分类顺序, 有中文名的优先, 名字, 路径)`，所以第一屏不会
  全是 `AI_Crow` 这种没名字的英文资产名。
- 图标：`core/icons.py` 去 `I:\Game\UIIcon` 找产品小图标，找不到就
  `_IconCache.placeholder()` 画分类色块 + 变体字（`1P`/`3P`/`UI`）或名字首字。
- `app/pages.py` 的库页 splitter 改成 `setSizes([372, 880, 310])`，给两列卡片留位置。

## 4.9 「一大坨白」的两类根因（2026-10-25）

手机上那种「有贴图、但整块白得看不清」的，实测是两个完全不同的原因，都已经修掉：

1. **无贴图的屏幕/序列帧面**（`Boss_C501_CellPhone`、手表序列帧这类）：
   材质是 `Masked`/`Translucent` 且**四张贴图全空**（父材质 `M_Weapon_Watch_Sequence`），
   在游戏里靠 Canvas / 渲染目标出图，我们画出来就是一整片纯白盖住本体。
   - `Material.is_untextured_overlay` 判定：四张贴图全空 **且**（blend 属于
     masked/translucent/additive/modulate/alpha，或者名字带 screen/sequence/ui_）。
   - `render/viewer.py::_build_draws` 默认 `continue` 掉这些 draw；
     `SceneState.show_untextured`（检查器「显示无贴图部件」开关）可以临时打开看几何。
2. **`EmissionColor_Bright` 被当成自发光颜色**：`_apply_scalar_defaults` 原来
   「参数名里含 emissive/emission/glow 就写进 `material.emissive`」，于是
   `EmissionColor_Bright=(1,1,1,5)` 把 emissive 写成纯白，再乘上 Screen 材质那张
   几乎全白的 `EmissiveMap`，整个模型被加成一坨白（把 albedo 改成纯黑渲出来**还是白**，
   这就是判定「是加法项在过曝」的决定性实验）。
   - 修法：`_EMISSIVE_BOOST_WORDS`（bright/boost/highlight/flash/mult/scale/intensity/
     power/strength）+ `_is_emissive_boost()`，命中这些词的自发光参数跳过不读。
   - 回归：`tools/shot_one.py "Boss_C501_CellPhone_3P.uasset" ...` 现在能看到
     深灰机身、红色按键、PHS 标志、天线和锥头。

另外顺手修了 `_sync_textures` 的贴图缓存：原来只按 `id(tex)` 存 GL 贴图，Texture 被
GC 后 id 会被新对象复用，新模型就套上了上一件的贴图（`_tex_keep` 现在保强引用）。

## 4.10 分类口径（2026-10-25 重排）

`core/cnnames.category_of(path, cn)` 是唯一分类入口（UI 不再读 names.json 里烘焙的
旧 `cat`，改规则不用重跑 harvest）。顺序 = 优先级：

钥匙卡 → 藏品 → 容器 → 角色技能 → 弹匣/瞄具/配件/弹药/武器 → 角色/AI → 载具 → 装备 → 道具 → 其他

- 钥匙卡：路径含 `keycard/key_card/cardkey/doorcard`，或中文名含 钥匙卡/门卡/房卡/通行卡。
- 藏品：路径含 `/props/collect/`，或名字是 摆件/雕像/手办/盲盒/纪念币/古董。
- 容器：路径含 crate/container/locker/cabinet/safebox/chest/box/case/toolbox/briefcase/
  suitcase/barrel/drum 等，或名字含 容器/箱子/货箱/收纳/保险柜/柜子/弹药箱/手提箱；
  `/backpacks`、`/equipments` 下的背包**不算**容器。
- 角色技能：`/Weapons/MilitaryProps/` 下的东西（手机、弩、无人机、PDA、声呐陷阱、钩枪）。
- 其余按名字规则（`CAT_RULES`）再按路径兜底。

模型库默认就是**卡片视图**（分好类、带中文名和图标），底部的「详细文件」按钮切到原来的
目录树；「合并变体」默认打开，同一件东西的 `1P/3P/UI` 收成一张卡片。

## 5. 用户要的 7 个功能（验收清单）

1. 直接解包游戏内文件 → 加载到缓存 → **关闭软件后删除缓存**
2. 可调**金属度、粗糙度**
3. 可调**灯光**
4. 模型与贴图分离，走 GenTexDirHD 对应关系（含材质 json）
5. **导出 OBJ**
6. **艺术化渲染**
7. 找到模型的**具体中文名字**

UI 用 **FluentPy**（https://github.com/XDDXMT/FluentPy ，PySide6 的 Fluent 风格组件库）。

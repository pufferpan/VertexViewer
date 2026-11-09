# 从 FModel / UEFormat 搬过来的原理 · 对照表

本工程没有调用 FModel 或 UEFormat 的任何二进制，是把它们的**读取与导出原理**用 Python 重写了一遍。
下表是「哪一块功能 → 对应 FModel / UEFormat 的哪段实现 → 我们落在哪个文件」。

## 一、容器与解包（FModel: CUE4Parse）

| 功能 | CUE4Parse / FModel 位置 | 本工程实现 | 说明 |
| --- | --- | --- | --- |
| Pak footer 解析 | `FPakInfo.cs` | `core/pak.py::_read_footer` | 204 字节尾部：magic `0x5A6F12E1`、ver=11、index offset/size、sha1、压缩方法名表 |
| 索引解密 | `GameTypes//Encryption/Aes/DeltaForceAes.cs` | `core/pak.py::_decrypt` | `AES-256-ECB(pak_key)` 解完再**整段 XOR 单字节 mask**；mask 取解密后首字节 |
| 加密 key/mask 定位 | `FPakFile.cs` 的 key 试解 | `core/pak.py::_find_key` | 201 个候选 key × 256 个 mask，用「seed==0 + count 合理 + mount 可打印含 `/`」判别 |
| 条目编码 | `FPakFile::DecodePakEntry` | `core/pak.py::_open_index` | **bit-packed 记录**（不是定长数组）：bit22=加密、bit23=压缩，offset/size 变长 |
| 目录索引 | `FPakFile::DecodeDirectoryIndex` | `core/pak.py::_parse_fdi` | `FString dir` + 文件数 + `FString name + u32 location` |
| Oodle 解压 | `OodleLZ_Decompress` | `tools/pakpick.py::Oodle` | ctypes 调 `oo2core_8_win64.dll`（游戏自带） |
| 一条资产 = 多文件 | `PackageReader` 的 uasset/uexp/ubulk/uptnl | `core/loader.py::load_blobs` | 该游戏把导出体拆进 `.uexp`，大块进 `.ubulk`，**最大 mip 进 `.uptnl`** |

## 二、uasset 解析（FModel: CUE4Parse/UnrealTypes）

| 功能 | CUE4Parse 位置 | 本工程实现 |
| --- | --- | --- |
| 包头与版本 | `FUnrealAr.cs` / `FPackageFileSummary` | `core/uasset.py::read_summary` — DF 的 `LegacyFileVersion=-4613`（= -7×659，CUE4Parse 里对 DeltaForce 除以 659） |
| 名字表 | `FNameEntrySerialized` | `core/uasset.py` — DF 的 `names[0]` 不是 `None` 而是全路径，单独兼容 |
| 导入/导出表 | `FObjectImport/FObjectExport` | `core/uasset.py`；`export_class` 的 `ClassIndex<0 → import.object_name`、`==0 → "Class"` |
| 属性标签 | `FPropertyTag` | `core/uasset.py::_read_value` — 补了 `BoolProperty` 的 BoolVal 排在 `HasPropertyGuid` 之前的坑 |
| 虚拟坐标 | uasset+uexp 拼接 | `core/mesh.py` — 导出体位置 = `serial_offset - len(uasset)` |

## 三、几何（UEFormat 的 VERTICES/INDICES/NORMALS/TANGENTS/TEXCOORDS/MATERIALS）

| UEFormat 块 | 本工程实现 | 注意点 |
| --- | --- | --- |
| VERTICES | `core/mesh.py::_assemble_lod` | `.ubulk` 里每个 LOD 一块：`strip(2) + 12 + n + 12 + n + positions(n*12)` |
| TANGENTS | 同上 | `FPackedNormal` 实测是 `int8 / 127`，第 4 字节是 bitangent 符号 |
| TEXCOORDS | 同上 | **逐顶点**存 `num_texcoords` 个 (u,v)；顶点数×通道数都是奇数时 UE 补空顶点，长度是 `(n + tc%2)*tc`，按 `n*tc` 切会整体错位 |
| INDICES | 同上 | 三种容器头 `(elemSize,count)` / `(1,byte_size)` / `(01 00 + 8×0 + 01 00 00 00 + byte_size)`，靠 `(zero%, ref%)` 打分择优 |
| MATERIALS | `core/loader.py::materials_in / load_materials_for` | 见第四节 |

## 四、材质与贴图（FModel 的 "导出后目录里贴图已摆好" 语义）

| 规则 | 出处 | 本工程实现 |
| --- | --- | --- |
| 材质只从包里读，不读 json | FModel 只认 uasset | `core/material.py`；`load_model` 不调 `materials_from_json` |
| 贴图按材质自己的包目录解析 | FModel 的 `../Textures/` 相对路径 | `core/loader.py::resolve_texture_ref`（先材质目录 → 模型目录 → `GenTexDirHD` 镜像 → `MaterialLib` 共享图集池，按 hash 唯一命中） |
| 共享图集池 | `GenTexDirHD/Game/MaterialLib/Textures/T_VMGen_*Map_<hash>` | `_pool_tex_lookup`（hash 名唯一，不是猜） |
| 通道顺序 | UE 的 MRA：R=Metallic G=Roughness B=AO | `render/shaders/scene.frag`，`u_metal_mode/u_rough_mode` 让滑杆覆盖贴图 |
| `*_NRMMap` 打包 | RG=法线XY（B=粗糙度） | 只取 RG 当法线（与用户 .blend 一致），`NRM_ROUGHNESS=False` |
| BC7/BC5/BC1 解码 | `DirectXTex` / `texconv` | `core/texture.py`（`texture2ddecoder`），BC5 只存 XY，B 必须补 `sqrt(1-x²-y²)` |
| 解码方向 | FModel 输出的 PNG 是自上而下 | `load_texture` 统一转 RGBA top-down；**渲染时 V 翻一次** |

## 五、渲染端的三条口径（跟 FModel/Blender 对齐）

1. **坐标系手性**：UE 左手（x 前, y 右, z 上）→ GL 右手。必须翻一个轴：
   `x=y, y=z, z=-x`（`core/types.py::ue_to_gl`）。
   早先用循环置换 `(y, z, x)`，行列式 +1 但手性没变，结果**整只模型是镜像的**——贴图左右反着长、贴花上的字是反的、看起来像"缺面"。
2. **UV**：UE V 向下，GL V 向上 → 采样前 `v' = 1 - v`（`render/viewer.py::prepare_lod`）。
   **U 不翻**（翻了 UV 岛会碎）。
3. **双面**：该游戏网格里缠绕方向混着，强制关剔面；但**背面采样时 U 翻回来**
   （`scene.frag`: `gl_FrontFacing ? v_uv : vec2(1-v_uv.x, v_uv.y)`），否则从背面看到的贴花字是反的。

## 六、导出（对齐 UEFormat 的产物形态）

| 产物 | 实现 | 形态 |
| --- | --- | --- |
| `.uemodel` | `exporters/uemodel.py` | 单文件（`format=vertexviewer.uemodel`），几何 base64，材质只留引用；`materialize()` 再回填 |
| FModel 目录树 | `exporters/fmodel_layout.py` | 按包路径还原：`DeltaForce/Content/Models/.../<模型>.uemodel + <模型>.json + Textures/*.png` |
| OBJ | `exporters/obj.py` | `v/vt/vn/f` + `.mtl` + 贴图 PNG；UV 写**原始值**（Blender/FModel 口径），不写翻过的 |

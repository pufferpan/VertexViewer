## 7. 检视动画（2026-10-25 第四轮）

### 7.1 哪些物品真的有检视动画

`core/loader.py::inspect_animations()` 扫 `Models/**` 下的动画目录（`ANI` 和 `anmi` 两种拼法都有，
`Prop_Collect_HoodieFigureA_1400/anmi/` 就是后者），文件名是
`Knife_Prop_View_<物品名>_1P|3P[_wawa]`，去掉前缀/后缀后当物品名索引（`_wawa` 是花絮版，跳过）。

实际带检视动画的收藏品只有 **4 件**（8 个模型变体）：

| 物品 | 动画 |
| --- | --- |
| `props_collect_Echains_1320` | `Knife_Prop_View_Echains_1320_1P/3P` |
| `props_collect_Buliding_500` | `Knife_Prop_View_Buliding_500_1P/3P` |
| `Prop_Collect_TacFigureA_1414` | `Knife_Prop_View_TacFigureA_1414_1P/3P`（+ `_wawa`） |
| `Prop_Collect_HoodieFigureB_1401` | `Knife_Prop_View_HoodieFigureB_1401_1P/3P` |

（`inspect_animations()` 一共返回 826 条，剩下的都是角色 `Ani/*_Show_*` 的展示动画，不是物品检视。）

### 7.2 只能做「同节奏转台」，不能真解骨骼

动画资产是 `AnimSequence`，骨骼压缩用的是
`/Game/CommonAsset/CommonAnimBoneCompressionSettingsACL`，蒙皮骨架是
`/Game/Models/Characters/C_Test_001/C_Test_001_1P_Skeleton`。

- 想真正播放：要 ACL 解码器（解 `ACL` 压缩片段）+ 每顶点骨骼权重 + `scene.vert` 里的 bone 矩阵数组。
  我们现在的 shader 只有 `a_pos/a_nrm/a_uv/a_tan`，没有蒙皮管线，这一步是「新写一条渲染分支」的量级。
- 时长也拿不到：cooked 包里 `SequenceLength` / `NumFrames` 属性块被裁掉了
  （`core/anim.py` 的定位器能识别正常属性，但这几个包里根本没有），所以时长回退到 **3.2s**。
  `core/anim.py` 保留着完整的读取逻辑，等哪天包里有这俩属性就自动用真实时长。

### 7.3 现在给用户看到的是什么

- `MeshViewer.start_inspect(duration)`：16ms 定时器推进相机 `yaw` 一圈 360°，
  `pitch` 叠一个 ±6° 的正弦摆动 —— 观感就是游戏里「拿起物品转一圈看」，
  时长用动画资产的时长（拿不到就 3.2s），循环播放。
- 加载带检视动画的物品时**自动开播**（`_auto_inspect` 默认开），检查器里出现
  「播放检视动画 · 3.2s」按钮，播放中变成「播放中 · 3.2s / 点击停止」，再点即停。
- 模型库卡片早在上一轮就有 `▷ 检视` 标记。

### 7.4 顺手修的两个真 bug

1. `inspect_anim_for()` 传入带 `.uasset` 的文件名时匹配不上（后缀表里没有 `.uasset`），
   导致主窗口里按钮永远是灰的。现在先 `os.path.splitext(os.path.basename())` 再匹配。
2. `props_collect_Buliding_500_1P` 这个包**只有壳没有几何**（`uasset 2389B / uexp 2971B`，连 `ubulk` 都没有），
   点卡片是白屏。`core/loader.py::_load_mesh_fallback()` 现在会按 `_3P/_1P/_LAY/_HD` 的顺序
   换个变体再试，实测回退到 `_3P` 拿到 12 个三角形。

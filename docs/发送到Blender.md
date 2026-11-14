# 送模型进 Blender

## 怎么用

1. 在模型库里选一个模型
2. **按住 `Ctrl + Shift`，在视口里按住左键拖一段（≥36 像素），松手**
3. 模型会先导出（有骨骼走 GLB、纯静态走 OBJ），然后 Blender 自动打开并导入

不想记快捷键：工具栏「发送到 Blender」按钮、或 `Ctrl+Shift+B` 菜单效果一样。

## 为什么是「拖动」

视口左键本来就是转视角。按住 Ctrl+Shift 时左键不再转相机，改成画一条投放手势；
拖动不足 36 像素当误触，不触发，也不会把相机转乱。

## 导出格式选择

| 模型 | 格式 | 原因 |
| --- | --- | --- |
| 有骨骼（SkeletalMesh） | `.glb` | 带 joints / inverseBindMatrices / 权重，Blender 里能继续摆姿势 |
| 纯静态网格 | `.obj` + `.mtl` | 最稳，材质和贴图直接落地，不依赖 glTF 材质扩展 |

文件落在 `<导出目录>/blender/<资产名>.glb|.obj`（默认导出目录见设置页），
同名会被覆盖——要留版本自己改文件名。

## Blender 在哪找

1. 环境变量 `VERTEXVIEWER_BLENDER`
2. `%LOCALAPPDATA%\VertexViewer\config.json` 里的 `blender` / `blender_exe`
3. 常见安装位置（Program Files\Blender Foundation、Steam 库里的 Blender）

找不到时弹提示，不会静默失败。

## 导入脚本做了什么

写一份临时脚本再让 Blender 执行：按扩展名选 `wm.obj_import` 或
`import_scene.gltf` → 选中刚导入的网格 → `view3d.view_selected()` 把视角框上去 →
打印 `[vertexviewer] imported N objects`。

**不动当前场景**：不删对象、不清集合，导入是追加；场景里原有的东西保持原样。脚本路径
`%TEMP%\vertexviewer_blender_import.py`，可以直接打开看，没有隐藏动作。

## 实测

- `AI_Crow`（SkeletalMesh，111 根骨骼）导出的 GLB，用生成的脚本在 Blender 5.2.3
  后台导入：`[vertexviewer] imported 2 objects`，退出码 0。
- 单测 8 项（手势阈值、脚本内容、启动参数、环境变量优先、找不到 Blender 报错），
  整个包 44 项全过。

## 边界

- 只支持本机已安装的 Blender（不自动下载）
- 导入是追加式的，不会清空当前场景；重复按会得到多份模型，自己删多余的就行
- 贴图是外部文件，移动 `.glb/.obj` 时要连贴图一起带走

# 2026-11-01 · 改枪渲染与启动动画修复

构建：`1.0+2026-11-01.fix1`。

## 模型与渲染

- NCE / BC5 法线使用 RG 重建 Z；NCE 的蓝通道是额外数据，不能直接当作法线 Z。实际 M4A1 表面的杂色、异常高光因此消除。
- 双面绘制保持原始 UV，取消按三角形绕序翻转 U。双面法线方向在光照前处理，并在法线贴图采样后计算 NoV。
- 缺失解码数据的 Texture 返回空贴图，使用默认材质继续绘制。修复 HK416 部分可选贴图缺失导致整帧失败。
- 渲染直接使用当前解析的几何，停止从未经来源/版本验证的旧 `.uemodel` 文件反向覆盖几何；导出功能保留。
- 改枪合并保留全部 UV 通道；缺少的通道回退到该部件的 UV0。每段绑定独立材质，缺材质时补默认材质，避免材质序号错位。
- 合并前按各部件自己的顶点范围过滤坏三角形；渲染器也过滤无效三角形并重映射 section 范围，取消把坏索引钳到边界顶点的行为。
- 换网格时释放旧 VAO/VBO/EBO。改枪滑杆采用单个合并计时器，同一主件的修改保留当前相机视角。
- 页面主窗口引用改名为 `host_window`，避免覆盖 QWidget 的 `window()` 方法。修复 FluentPy eventFilter 反复抛出 `VertexViewerWindow object is not callable`。

## 打包依赖

打包启动检查发现 QtCore 在进入应用前导入失败。原因是 PyInstaller 从当前工具环境的 Poppler 目录收集了 ICU 78（导出 `ucnv_open_78`），而 Qt 需要 Windows ICU 的 `ucnv_open` 等无版本后缀接口。

`VertexViewer.spec` 现在从打包搜索 PATH 排除外部文档工具的 `dependencies/native` 目录，并在 Analysis 后过滤这些来源的 DLL，避免增量缓存继续带入错误 ICU 和系统 API shim。修改只作用于打包进程，不改变系统 PATH。

## 开屏与首次向导

- 开屏底色与向导主色统一为 `#2B579A`。
- `app/transitions.py` 提供固定透明原生窗口内的内容区域动画，避免逐帧修改系统窗口尺寸。
- 开屏移除整张卡片的 QGraphicsOpacityEffect，内容自绘淡入淡出；计时使用单调时钟与 PreciseTimer。已知进度显示真实进度，无进度时使用滚动指示。
- 向导缓存背景、预缩放截图条，飞入时只改变位置与透明度；展开/收起时复用绘制数据。
- 文字错峰入场由可取消的序列动画管理，快速翻页时停止旧动画并还原布局位置。
- 修复向导收尾引用未定义变量而直接关闭的问题；关闭时取消尚未开始的入场与截图条动画。
- 已完成首次设置时，启动流程不再为检查向导而隐藏/显示一次开屏。

## 验证

- `python tools/test_model_regressions.py`：9 项通过。
- `python tools/verify_texture_winding.py`：正反绕序像素差 0；NCE 蓝通道变化像素差 0；缺图仍可绘制。
- `python tools/verify_ui_transitions.py`：固定窗口几何、快速翻页、正常收尾、入场中退出通过，无 Qt 异常。
- `python tools/verify_gunsmith_models.py`：M4A1、HK416、SCAR-H 官方配件实际加载、几何/UV/材质检查及 GPU 释放验证通过。图片与 JSON 在 `work/fix-20261101/`。
- `python render/selftest.py`：5 个着色器、24 张风格/材质预览及稳定性检查通过。
- 主程序离屏截图启动正常退出；398 个控件的 `window()` 方法可调用。

上述验证覆盖三把抽样枪械和指定回归场景，没有遍历全部游戏资产。配件选择、挂点与伸缩托标定沿用原有算法。

改动前源码备份在 `work/fix-20261101/original/`，原打包目录备份在 `work/fix-20261101/previous-build/`。

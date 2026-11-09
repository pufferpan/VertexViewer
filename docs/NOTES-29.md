# fix5：干员皮肤分段、LOD 与共享贴图

修复骨骼网格旧解析器只给整套角色使用一个材质、在顶点数据中扫描到伪 LOD 头的问题。新增严格的 native SkeletalMesh 解析，按真实材质槽、每档 LOD 的索引、分段与 LODMaterialMap 读取。适配 DF 切线掩码后的额外三个字节、重复顶点数组及 16 字节高精度切线。分段索引完整覆盖和顶点范围均验证。

材质保持源路径和分段绑定，加载后续 LOD 才使用的合并材质；不再用整个模型的图集替换脸、衣服、头发或其他部位。原始空材质槽显示中性色，不挪用相邻材质。修复材质 import 路径被截断为裸名：皮肤引用默认外观的裤子、鞋等共享贴图时，准确读取其 /Game 包路径。

本机当前游戏库批量检查 484 个干员骨骼模型和 1342 个去重材质，native 解析错误 0、非空材质引用缺失 0。额外修复 _C1、_CSSS、_HD 等非标准贴图名被误剔除，以及 Textures/UI 下真实角色贴图被当图标过滤的问题。五个资产含源文件本来就是 null 的材质槽，不伪造其原始材质。完成 Kai、Luna、Elio、C204 的真实资源验证，Kai/Luna/Elio 截图检查，54 项单元回归通过。保留 fix4 枪械皮肤、附件定位、独立部件导出、空感谢名单与向导功能。

格式交叉参考：
- https://github.com/FabianFG/CUE4Parse/blob/master/CUE4Parse/UE4/Assets/Exports/SkeletalMesh/USkeletalMesh.cs
- https://github.com/FabianFG/CUE4Parse/blob/master/CUE4Parse/UE4/Assets/Exports/SkeletalMesh/FSkelMeshSection.cs
- https://github.com/FabianFG/CUE4Parse/blob/master/CUE4Parse/UE4/Assets/Exports/SkeletalMesh/FSkeletalMaterial.cs

批量报告位于 work/operators-20261101/operator-audit.json；源码及打包版验证报告分别位于同目录 source-release-check 与 frozen-release-check。

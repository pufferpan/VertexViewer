"""功能开关（谁不想要某个功能，改这里一行就行）。

`INSPECT_ENABLED = False` 的意思是：检视动画整套关掉 ——
- 扫描动画表的 `loader.inspect_animations()` 直接返回空表，不读 `mesh_catalog.json`
  （省掉每次启动那 691 条的匹配工作）；
- 卡片副标题不再追加「· 检视」、tooltip 不再写动画路径；
- 检查器里「播放检视动画」按钮整个隐藏；
- 打开带动画的物品不再自动转台。

代码都还在，想要回来说一声把这里改回 True 即可。
"""
from __future__ import annotations

INSPECT_ENABLED = False

# 改枪页选择皮肤，并可同步该皮肤的官方配件。
SKINS_ENABLED = True

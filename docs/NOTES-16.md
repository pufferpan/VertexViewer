# 16 · 诊断报告（一页定位别人电脑上的问题）

## 16.1 为什么要有它

远程帮人排障最耗时间的不是修，是**问信息**：什么版本？装在哪？`data/` 在不在？
索引建了没？名字表读到了吗？显卡驱动行不行？日志在哪？

现在这些一次性打成一页文本，对方点一下就生成，复制发过来即可。

## 16.2 三个入口

| 入口 | 说明 |
| --- | --- |
| 设置 → 数据维护 → **生成诊断报告** | 写盘 + 弹窗预览（详细文本可展开），按钮「复制全文」「打开所在目录」 |
| 环境变量 `VERTEXVIEWER_DIAG=1` | 启动时静默生成一份（不弹窗），适合让用户「带参数开一次」 |
| 崩溃自动 | 未捕获异常 → `%LOCALAPPDATA%\VertexViewer\logs\崩溃-时间.txt`，内含完整诊断 |

报告落到 `%LOCALAPPDATA%\VertexViewer\logs\诊断报告-YYYYmmdd-HHMMSS.txt`。

## 16.3 报告里有什么

```
版本 / 是否打包版 / exe 路径 / 程序目录 / 打包资源目录 / WORK / 游戏 pak 目录
Python / 系统 / CPU / Qt / OpenGL 渲染器字符串
--- 静态数据 ---
names.json        实际使用的是哪一个文件 + 体积 + 修改时间
mesh_catalog.json 同上
AESKey1.json      同上
pakinfo.json      同上
--- 资产索引（SQLite）---
数据库路径 / 状态（条数·体积·时间）/ 索引条数 / 可渲染网格数 / 中文名条数 / 检视动画数
--- 目录清单 ---
exe/data、_internal/dfdata 各有几项、分别是什么
--- 配置 ---
config.json 原文
--- 日志 ---
startup.log 末尾 24 行
```

判定逻辑一眼可用：

- **全英文名** → 看 `names.json` 那行：指向 `data/` 说明用户在用它自己的（可能是坏的），
  指向 `_internal/dfdata/` 才是内置那份；`缺失` 就是包不完整。
- **提示没有索引** → 看「索引状态」：`缺失` + 「索引错误」段里会写清是没选游戏目录、
  还是 `AESKey1.json` 缺失导致解不开 pak。
- **界面全黑** → 看 `OpenGL` 行：写着 `QOpenGLContext` 创建失败 / 软件渲染，就是驱动问题。
- **版本不对** → 第一行就有版本号，能立刻判断对方是不是还在跑旧包。

## 16.4 实现要点

- `core/diag.py`：`collect()` 收数据 → `render()` 排版 → `write_report(path="")` 落盘；
  `install_excepthook()` 挂 `sys.excepthook`。
- 报告生成**先调用一次 `loader.index()`**：早期启动时数据库可能还没建好，先确保
  建完再统计条数，避免报告写着「0 条」误导判断。
- `OpenGL` 一行用 `QOffscreenSurface + QOpenGLContext.glGetString(GL_RENDERER)`；
  Qt 还没起来时写「启动早期生成，未测」，不抛异常。
- 报告不含任何游戏文件内容、不联网。

## 16.5 顺带修掉的两个真问题

1. `core/loader.py::_catalog_classes()` 还在读 `WORK/mesh_catalog.json`（`data/` 里已不放），
   导致**检视动画统计变 0**、卡片上的「· 检视」标记消失。改成统一走 `catalog()`，
   也就走 `data_file()` 的查找链（`_internal/dfdata` → `data/` 覆盖）。
2. `core/diag.py` 的目录清单拼路径时多套了一层 `_internal`，显示成
   `...\_internal\_internal\dfdata`，已修正。

## 16.6 验收

- 源码：`python -c "from core import diag; print(diag.write_report())"` → 生成
  `诊断报告-20261026-213333.txt`，可渲染网格 9443、中文名 9933、检视动画 691。
- 打包版（空 `%LOCALAPPDATA%`）：`VERTEXVIEWER_DIAG=1` 启动 → 报告里
  `静态数据` 四行全部指向 `_internal\dfdata\`、`索引状态 937088 条 · 137.4MB`。
- 设置页按钮：文本落盘 + 弹窗（详细文本里就是整份报告），截图
  `work/diag_settings.png`。

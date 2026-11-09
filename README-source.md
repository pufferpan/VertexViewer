# VertexViewer 完整源码包

归档日期：2026-11-07。程序版本：`1.0+2026-11-04.credits`。
归档包含本机当前源码；归档日期不改变程序版本，也不表示重新验证了全部游戏资产。

当前功能包括模型与贴图查看、武器改装及皮肤、自定义配件与位置手动输入、与所选模型关联的第一人称检视和角色手臂、改枪检视、动画 GLB 导出、机器码与名称/期限授权、启动音乐和感谢名单。具体实现和已知边界见 `README.md`、`NOTES.md` 和 `docs/`。

## 包内内容

- `app/`、`core/`、`render/`、`exporters/`、`cache.py`、`__main__.py`：桌面程序、渲染器、着色器和导出逻辑。
- `assets/`：向导截图、字体、启动音乐、感谢名单、授权公钥、现成的动画解码组件及所需 Windows x64 运行时。
- `work/`：仅保留 `mesh_catalog.json`、`names.json`、`pakinfo.json`、`icons.db` 四项静态资源。
- `tools/animation_bridge/`：动画桥接器 C# 源码、项目文件、SDK 校验记录；`sdk/` 含本机编译时使用的 37 个依赖程序集。
- `third_party/CUE4Parse-native/`：本机动画原生解码组件所用的 CUE4Parse 源码快照，包含 ACL、RTM 等已展开子模块和许可证；不含 Git 历史和编译目录。
- `third_party/fluentpy-qt/`：当前使用的 FluentPy 0.7.3 源码、资源和发行元数据。
- `tests/`、`tools/`、`docs/`、`_cue/`：测试、维护工具、文档与早期解析参考材料；根目录 locres 数据为原有语言提取输入。
- `VertexViewer.spec`、`build-source.ps1`、`requirements*.txt`：打包入口和固定依赖。
- `SOURCE-MANIFEST.json`：包内所有文件的大小和 SHA256。

不包含历史 EXE/ZIP、缓存、日志、已导出的模型/工程、机器上的授权文件、个人设置、签发私钥或游戏包。游戏解包密钥 `AESKey1.json` 需从自己保管的配置另行放到源码根目录 `work/AESKey1.json`；本包没有附带实际密钥。第三方依赖程序集保留用于编译和运行，除上述单独收录的源码外，不代表包含全部依赖的上游源代码。

## 运行

使用 Windows x64、Python 3.12（当前环境为 3.12.10）。在解压后包含 `__main__.py` 的目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe __main__.py
```

先放好自己保管的 `work/AESKey1.json`，首次运行选择本机游戏目录，并使用对应的机器码激活。程序保留原有激活逻辑；私钥仍由所有者单独保管。设置和索引写入 `%LOCALAPPDATA%\VertexViewer`，不在源码包内。现成动画组件为自包含运行时，直接运行不需要另装 .NET。

## 编译桌面程序

```powershell
powershell -ExecutionPolicy Bypass -File .\build-source.ps1 -PythonExe .\.venv\Scripts\python.exe
```

默认运行回归测试并生成 `dist/VertexViewer/VertexViewer.exe`，发布时需携带整个目录。加上 `-Format SingleFile` 生成单文件；`-Format Both` 一次生成两种格式。默认保留包内已构建并验证过的动画组件。

如果修改了 C# 动画桥接器，安装 .NET 10 SDK 后执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build-source.ps1 -PythonExe .\.venv\Scripts\python.exe -RebuildAnimation -Format Both
```

该命令校验 `tools/animation_bridge/sdk/` 的三个核心程序集，编译到 `build/animation-publish/`，再更新动画组件。`CUE4Parse-Natives.dll` 与解码器许可证会保留。

如果修改了原生 ACL 解码器，需要另装 Visual Studio C++ 构建工具和 CMake：

```powershell
cmake -S third_party/CUE4Parse-native/CUE4Parse-Natives -B build/cue-native -A x64
cmake --build build/cue-native --config Release
Copy-Item -LiteralPath build/cue-native/Release/CUE4Parse-Natives.dll -Destination assets/animation/CUE4Parse-Natives.dll -Force
```

源码已包含原生组件所需的 ACL 子模块内容；修改解码器后仍需做真实游戏资源的功能验证。

## 归档校验与重打包

ZIP 旁的 `.sha256` 校验整个压缩包；包内清单逐项校验源文件。归档工具先完成 ZIP CRC、文件数、必需资源、SDK 固定哈希和逐文件 SHA256 核对，再将 `.partial` 改为最终 ZIP。

```powershell
.\.venv\Scripts\python.exe tools/package_source.py --output VertexViewer-full-source.zip
Get-FileHash -LiteralPath VertexViewer-full-source.zip -Algorithm SHA256
```

# 取消激活（2026-11-10）

## 删了什么

| 文件 | 作用 | 现在 |
| --- | --- | --- |
| `core/activation.py` | Ed25519 签名校验、token 解析、机器码、授权记录读写 | 已删除 |
| `app/activation.py` | 激活对话框、设置页「激活与授权」卡片、运行期到期检查 `LicenseGuard` | 已删除 |
| `assets/activation-public.json` | 签发公钥 + 签发站点地址 | 已删除 |
| `tools/activation_owner.py` | 自己给自己签码的脚本 | 已删除 |
| `tools/verify_activation.py` | 自检：启动门槛与对话框 | 已删除 |
| `tests/test_activation.py` | 授权相关 13 项用例（含与签发站点的互操作用例） | 已删除 |
| `docs/机器码激活.md` | 用户说明 | 已删除 |

## 改了哪里

- `app/__main__.py`：去掉 `require_activation()` 门槛与 `LicenseGuard`，去掉 `--verify-activation` 入口。
- `app/pages.py`：设置页不再插入 `authorization_widget` 卡片。
- `VertexViewer.spec`：不再打 `activation-public.json`；不再复制 `docs/机器码激活.md`；版本行去掉「名称与限时激活」。
- `tools/package_source.py`：必含清单去掉 `core/activation.py`。
- `docs/使用说明.txt`：新增「取消激活」一节；启动音乐描述去掉「通过激活后」。
- `README-source.md`：去掉机器码/授权描述。

## 行为差异

- 启动直接进主窗口，没有激活框、没有机器码、没有到期检查、没有任何网络请求。
- 旧版本留在 `%LOCALAPPDATA%\VertexViewer\activation.json`（或旧目录 `%LOCALAPPDATA%\DFViewer\activation.json`）的文件不再被读取，留着或删掉都无影响。
- 原先「激活后才播放启动音乐」的限制自然消失，音乐照旧播一次。

## 验证

- `python -m unittest discover -s tests` → `Ran 33 tests ... OK`（原 36 项里属于授权的用例随文件一起删除；其余全部通过）。
- 用干净的 `LOCALAPPDATA` 起打包版：直接出现主窗口，未弹激活框。
- 源码里 `grep -rn "activation\|激活\|机器码" app core tools tests` 只剩本文件与使用说明里的历史说明。

"""Extract a single pak entry by its virtual path（CLI 小工具）。

真正的读取逻辑现在只有一份：`core.loader.read_entry`（索引走 SQLite、
密钥/游戏目录/Oodle 都由 loader 自己解析）。这个模块保留只是为了命令行
`python tools/pakpick.py <vpath> [out.bin]` 还能用。

历史坑：以前这里硬编码了开发机的 `IDX = r"G:\\xmcl-fetch\\work\\fileindex.json"`、
`PAK_DIR`、`VAULT`、`OODLE` 四个常量，`cache.default_extract()` 在 loader
抛异常时又会静默回退到这里 —— 别人机器上没有 G 盘，于是报
「读不到 fileindex.json」。别再加回来。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def oodle():
    """兼容旧脚本：`from tools.pakpick import oodle`（实现在 core/oodle.py）。"""
    from core.oodle import get_oodle

    return get_oodle()


def extract(vpath: str) -> bytes:
    """读一个 pak 条目（等同 loader.read_entry，保留旧名字避免调用方报错）。"""
    from core import loader

    return loader.read_entry(vpath)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法： python tools/pakpick.py <资产虚拟路径> [输出文件]")
        raise SystemExit(2)
    data = extract(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else "out.bin"
    with open(out, "wb") as fh:
        fh.write(data)
    print(f"{len(data)} bytes -> {out}")

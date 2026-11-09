"""版本与构建信息（报问题时让对方念这一行，最容易判断他跑的是不是新包）。"""
from __future__ import annotations

VERSION = "1.0"
BUILD = "2026-11-04.credits"    # 每次发版改这里（打包脚本会读它写进 版本信息.txt）
TITLE = "VertexViewer · 模型浏览器"


def stamp() -> str:
    return f"{VERSION}+{BUILD}"

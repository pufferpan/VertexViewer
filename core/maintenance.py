"""索引重建 / 恢复出厂设置：给设置页和启动失败提示用的维护接口。"""
from __future__ import annotations

import glob
import gzip
import io
import json
import os
import shutil
import sys


def _ld():
    from core import loader
    return loader


def index_dirs() -> list:
    """索引现在只存一个 SQLite 文件（旧格式路径只用于导入）。"""
    from core import indexdb
    ld = _ld()
    return [indexdb.db_path(), os.path.join(ld.WORK, "index.tsv.gz")]


def _write_json_gz(out: dict, path: str) -> None:
    """和旧版 fileindex.json.gz 完全同构：{路径: [pak, 偏移]}。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8") as fh:
                json.dump(out, fh)
    os.replace(tmp, path)


def rebuild(write_json: bool = False) -> tuple:
    r"""从游戏 pak 现场重建索引，写进 %LOCALAPPDATA%\VertexViewer\index.db。

    `write_json=True` 时额外导出一份旧格式 fileindex.json.gz（兼容别人给的脚本），
    默认不写：现在索引只存一个 SQLite 文件，不再散落多个文件。
    """
    ld = _ld()
    from core import indexdb

    try:
        pairs = ld.rebuild_index_from_paks()
    except Exception as exc:                                     # noqa: BLE001
        import traceback
        traceback.print_exc()
        return False, f"重建失败：{type(exc).__name__}: {exc}"
    if not pairs:
        return False, (ld.INDEX_ERROR or "没有从游戏 pak 里读到资产。").strip()

    written = []
    try:
        indexdb.build()
        written.append(indexdb.db_path())
    except Exception as exc:                                     # noqa: BLE001
        return False, f"数据库写入失败：{type(exc).__name__}: {exc}"
    try:
        ld._INDEX = pairs
    except Exception:                                            # noqa: BLE001
        pass

    if write_json:
        try:
            path = os.path.join(ld.WORK, "fileindex.json.gz")
            _write_json_gz(pairs, path)
            written.append(path)
        except Exception as exc:                                 # noqa: BLE001
            print(f"[maintenance] json.gz failed: {exc}", file=sys.stderr)

    msg = "已重建索引：%d 个资产" % len(pairs)
    msg += "\n存到：" + "\n".join(written)
    return True, msg


def factory_reset(keep_index: bool = False) -> tuple:
    """恢复出厂设置：清缓存、配置、图标覆盖、导出的 .uemodel。

    `keep_index=True` 时保留已重建好的索引文件（一般人都希望保留，
    不然下次启动又要等一次重建）。
    """
    ld = _ld()
    localapp = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    targets = [
        os.path.join(localapp, "VertexViewer", "cache"),
        os.path.join(localapp, "VertexViewer", "uemodel"),
        os.path.join(localapp, "VertexViewer", "icons"),
        os.path.join(localapp, "VertexViewer", "logs"),
        os.path.join(localapp, "VertexViewer", "config.json"),
        os.path.join(ld.WORK, "icon_table.json"),
        os.path.join(ld.WORK, "icons"),
    ]
    if not keep_index:
        targets.append(os.path.join(localapp, "VertexViewer", "index"))   # 旧格式目录
        targets.append(os.path.join(localapp, "VertexViewer", "index.db"))  # 现在的 SQLite
    removed, failed = [], []
    for path in targets:
        if not os.path.exists(path):
            continue
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=False)
            else:
                os.remove(path)
            removed.append(path)
        except Exception as exc:                                 # noqa: BLE001
            failed.append(f"{path}（{exc}）")
    text = "已清理 %d 项" % len(removed)
    if removed:
        text += "：\n" + "\n".join(removed)
    if failed:
        text += "\n\n以下没清理成功（可能被占用）：\n" + "\n".join(failed)
    return not failed, text


def open_data_dir() -> str:
    """设置页「打开数据目录」用。"""
    ld = _ld()
    path = ld.WORK
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:                                            # noqa: BLE001
        pass
    return path

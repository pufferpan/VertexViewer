"""Disk cache for pak entries.

Requirement #1 of the user: "解包游戏内文件 -> 加载到缓存 -> 关闭软件后删除缓存".
So the cache is *session scoped* on purpose:

    %LOCALAPPDATA%\\VertexViewer\\cache\\<2 hex>\\<sha1>\\<asset>.uasset
                                                 <asset>.uexp
                                                 <asset>.ubulk
                                                 _meta.json

The hash is derived from the asset **stem** (path minus `.uasset`/`.uexp`/
`.ubulk`), so the three pak entries that make up one UE asset always land in
the same group directory -- a parser that gets `Cache.blobs(vpath)` has the
whole trio available next to each other.

Cleanup happens twice:
  * `atexit` + `QApplication.aboutToQuit` -> `purge()` the whole cache root,
  * on start-up -> `cleanup_stale()` drops group dirs older than one day
    (left behind by a crash / a killed debug session).
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from typing import Callable, Dict, Iterable, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

APP_NAME = "VertexViewer"
CACHE_SUBDIR = "cache"
MAX_AGE_DAYS = 1.0

#: extensions handled as one asset group
_GROUP_EXTS = (".uasset", ".uexp", ".ubulk", ".uptnl")


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def localappdata() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.abspath(base)


def default_root() -> str:
    return os.path.join(localappdata(), APP_NAME, CACHE_SUBDIR)


def asset_stem(vpath: str) -> str:
    """`x/SM_Foo.uasset` and `x/SM_Foo.ubulk` share the same stem."""
    root, ext = os.path.splitext(vpath)
    if ext.lower() in _GROUP_EXTS:
        return root
    return vpath


def group_hash(stem: str) -> str:
    return hashlib.sha1(stem.encode("utf-8")).hexdigest()


def sibling_paths(vpath: str) -> Dict[str, str]:
    """Best-effort trio paths for one asset, without touching the pak index."""
    stem = asset_stem(vpath)
    name = os.path.splitext(vpath)[1].lower()
    out = {"uasset": stem + ".uasset"}
    if name in ("", ".uasset", ".uexp", ".ubulk", ".uptnl"):
        out["uexp"] = stem + ".uexp"
        out["ubulk"] = stem + ".ubulk"
    return out


# --------------------------------------------------------------------------- #
# extraction backends
# --------------------------------------------------------------------------- #
def _extract_via_loader(vpath: str) -> bytes:
    from core import loader  # lazy: pulls the pak layer only when needed

    return loader.read_entry(vpath)


def default_extract(vpath: str) -> bytes:
    """Read one pak entry via `core.loader.read_entry`.

    这里必须**只**走 loader：
    以前失败会回退到 `tools.pakpick.extract`，而那个模块当年写死了开发机的
    `G:\\xmcl-fetch\\work\\fileindex.json` —— 别人机器上根本没这个文件，
    于是用户看到的是「读不到 fileindex.json」。现在 pakpick 也只是转手调
    loader，所以没必要再兜一层（兜了反而把真实异常吃掉）。
    """
    return _extract_via_loader(vpath)


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #
class Cache:
    """Session cache. One instance is enough, but several are harmless."""

    def __init__(
        self,
        root: Optional[str] = None,
        *,
        extract: Optional[Callable[[str], bytes]] = None,
        max_age_days: float = MAX_AGE_DAYS,
        cleanup_on_start: bool = True,
    ) -> None:
        self.root = os.path.abspath(root or default_root())
        self._extract_fn = extract or default_extract
        self.max_age_seconds = max_age_days * 86400.0
        self._lock = threading.RLock()
        self._extract_lock = threading.Lock()
        self.purged = False
        self._session_dirs: set[str] = set()
        os.makedirs(self.root, exist_ok=True)
        if cleanup_on_start:
            self.cleanup_stale()

    # -- layout ------------------------------------------------------------ #
    def group_dir(self, vpath: str) -> str:
        h = group_hash(asset_stem(vpath))
        return os.path.join(self.root, h[:2], h)

    def path_for(self, vpath: str) -> str:
        return os.path.join(self.group_dir(vpath), os.path.basename(vpath))

    # -- api --------------------------------------------------------------- #
    def get(self, vpath: str, *, sidecars: bool = True) -> bytes:
        """Cached bytes of one pak entry, extracting them on first use."""
        target = self.path_for(vpath)
        if self._valid(target):
            with open(target, "rb") as fh:
                return fh.read()

        stem = asset_stem(vpath)
        wanted = sibling_paths(vpath) if sidecars else {"uasset": vpath}
        if os.path.splitext(vpath)[1].lower() not in ("", ".uasset"):
            wanted = {"uasset": vpath}          # explicitly asked for one sidecar only

        with self._extract_lock:
            last_error: Optional[BaseException] = None
            main_error: Optional[BaseException] = None
            data: Optional[bytes] = None
            for kind, spath in wanted.items():
                out = self.path_for(spath)
                if self._valid(out):
                    if os.path.normcase(out) == os.path.normcase(target):
                        with open(out, "rb") as fh:
                            data = fh.read()
                    continue
                try:
                    payload = self._extract_fn(spath)
                except Exception as exc:                       # noqa: BLE001
                    last_error = exc
                    if os.path.normcase(spath) == os.path.normcase(vpath):
                        main_error = exc
                    continue
                self._store(out, payload, spath, stem=stem)
                if os.path.normcase(out) == os.path.normcase(target):
                    data = payload
            if data is None:
                if self._valid(target):
                    with open(target, "rb") as fh:
                        return fh.read()
                # 报错要报用户真正想要的那个文件，而不是顺带失败的 .ubulk ——
                # 别人机器上游戏版本不同时，索引里只有 uasset/uexp、没有 ubulk，
                # 之前就会抛 KeyError("...xxx.ubulk")，看着像是 ubulk 丢了。
                if main_error is not None:
                    raise main_error
                if last_error is not None:
                    raise last_error
                raise KeyError(vpath)
            return data

    def blobs(self, vpath: str) -> Dict[str, bytes]:
        """`{'uasset':…, 'uexp':…, 'ubulk':…}` for one asset (missing kinds omitted)."""
        out: Dict[str, bytes] = {}
        for kind, spath in sibling_paths(vpath).items():
            try:
                out[kind] = self.get(spath)
            except Exception:                                  # noqa: BLE001
                continue
        if "uasset" not in out:
            out["uasset"] = self.get(vpath)
        return out

    def has(self, vpath: str) -> bool:
        return self._valid(self.path_for(vpath))

    def size_bytes(self) -> int:
        total = 0
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for name in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
        return total

    def stats(self) -> Dict[str, object]:
        return {"root": self.root, "bytes": self.size_bytes(), "purged": self.purged}

    def files(self) -> Iterable[str]:
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for name in filenames:
                yield os.path.join(dirpath, name)

    # -- cleanup ----------------------------------------------------------- #
    def purge(self) -> None:
        """Delete the whole cache tree (silently retries locked files once)."""
        with self._lock:
            if not os.path.isdir(self.root):
                self.purged = True
                return
            self._rmtree(self.root)
            self.purged = not os.path.isdir(self.root)

    def cleanup_stale(self, *, max_age_days: Optional[float] = None) -> int:
        """Remove group dirs left behind by a crash (default: older than a day)."""
        limit = (self.max_age_seconds if max_age_days is None
                 else max_age_days * 86400.0)
        now = time.time()
        removed = 0
        if not os.path.isdir(self.root):
            return 0
        for entry in os.listdir(self.root):
            path = os.path.join(self.root, entry)
            if not os.path.isdir(path):
                continue
            try:
                newest = os.path.getmtime(path)
                for dirpath, _d, filenames in os.walk(path):
                    for name in filenames:
                        try:
                            newest = max(newest, os.path.getmtime(os.path.join(dirpath, name)))
                        except OSError:
                            pass
            except OSError:
                newest = 0.0
            if now - newest > limit:
                self._rmtree(path)
                removed += 1
        return removed

    def install_cleanup(self, app=None) -> None:
        """Hook `aboutToQuit` when a QApplication exists, always hook atexit."""
        if app is None:
            try:
                from PySide6.QtWidgets import QApplication

                app = QApplication.instance()
            except Exception:                                  # noqa: BLE001
                app = None
        if app is not None:
            try:
                app.aboutToQuit.connect(self.purge)
                app.aboutToQuit.connect(lambda: None)       # keep the slot list alive
            except Exception:                                  # noqa: BLE001
                pass
        if not getattr(self, "_atexit_hooked", False):
            atexit.register(self.purge)
            self._atexit_hooked = True

    # -- internals --------------------------------------------------------- #
    @staticmethod
    def _valid(path: str) -> bool:
        try:
            return os.path.getsize(path) > 0
        except OSError:
            return False

    def _store(self, out: str, payload: bytes, vpath: str, *, stem: str) -> None:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = out + ".part"
        with open(tmp, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, out)
        # touch the group dir so cleanup_stale() sees this session as "fresh"
        try:
            os.utime(os.path.dirname(out))
        except OSError:
            pass
        self._session_dirs.add(os.path.dirname(out))
        meta = os.path.join(os.path.dirname(out), "_meta.json")
        if not os.path.exists(meta):
            try:
                with open(meta, "w", encoding="utf-8") as fh:
                    json.dump({"asset": stem, "created": int(time.time()),
                               "source": vpath}, fh)
            except OSError:
                pass

    @staticmethod
    def _rmtree(path: str) -> None:
        for _attempt in range(3):
            try:
                shutil.rmtree(path, ignore_errors=False)
                return
            except Exception:                                  # noqa: BLE001
                time.sleep(0.05)
        shutil.rmtree(path, ignore_errors=True)


# --------------------------------------------------------------------------- #
# module level convenience
# --------------------------------------------------------------------------- #
_default: Optional[Cache] = None
_default_lock = threading.Lock()


def get_cache(root: Optional[str] = None, **kwargs) -> Cache:
    """Process wide singleton (the UI creates it once at start-up)."""
    global _default
    with _default_lock:
        if _default is None or (root and os.path.abspath(root) != _default.root):
            _default = Cache(root, **kwargs)
        return _default


def purge() -> None:
    if _default is not None:
        _default.purge()


def install_cleanup(app=None) -> None:
    get_cache().install_cleanup(app)


if __name__ == "__main__":                        # tiny manual smoke test
    c = Cache()
    print("cache root:", c.root)
    print("size:", c.size_bytes())
    print("stale dirs removed:", c.cleanup_stale())
    if len(sys.argv) > 1:
        data = c.get(sys.argv[1])
        print("bytes:", len(data), "->", c.path_for(sys.argv[1]))
        print("group files:", sorted(os.listdir(c.group_dir(sys.argv[1]))))
        print("size now:", c.size_bytes())
        c.purge()
        print("purged, exists:", os.path.isdir(c.root), "size:", c.size_bytes())

"""探测 .ustbin（StringTable 编译产物）能不能用 core.uasset 解析出 key→文本。

    python tools/probe_ustbin.py [资产名过滤] [数量]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import loader, uasset as mu  # noqa: E402

LOCRES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "work", "locres_zh.json")


def read_fstring(buf, pos):
    """UE FString: int32 len（含结尾 NUL，负数=UTF-16），返回 (text, newpos)。"""
    import struct
    if pos + 4 > len(buf):
        return "", pos
    n = struct.unpack_from("<i", buf, pos)[0]
    pos += 4
    if n == 0:
        return "", pos
    if n > 0:
        raw = buf[pos:pos + n]
        return raw.split(b"\x00", 1)[0].decode("utf-8", "replace"), pos + n
    n = -n
    raw = buf[pos:pos + n * 2]
    return raw.decode("utf-16-le", "replace").split("\x00", 1)[0], pos + n * 2


def parse_table(data):
    """FStringTable: int32 count, 然后每行 key(FString) text(FString)。"""
    import struct
    if len(data) < 4:
        return []
    count = struct.unpack_from("<i", data, 0)[0]
    if count <= 0 or count > 2_000_000:
        return []
    rows, pos = [], 4
    for _ in range(count):
        key, pos = read_fstring(data, pos)
        text, pos = read_fstring(data, pos)
        if not key:
            break
        rows.append((key, text))
        if pos >= len(data):
            break
    return rows


def main():
    filt = sys.argv[1] if len(sys.argv) > 1 else ""
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    index = loader.index()
    targets = [p for p in index if p.endswith(".ustbin") and filt.lower() in p.lower()]
    print("候选 .ustbin", len(targets))
    locres = {}
    if os.path.exists(LOCRES):
        locres = json.load(open(LOCRES, encoding="utf-8"))
    done = 0
    for path in targets:
        if done >= limit:
            break
        try:
            blobs = loader.load_blobs(path)
        except Exception as exc:                              # noqa: BLE001
            print("  读取失败", path.rsplit("/", 1)[-1], repr(exc)[:60])
            continue
        data = blobs.get("ustbin") or b""
        if not data:
            continue
        ns = os.path.basename(path).rsplit(".", 1)[0]
        rows = []
        # 1) 直接按 FStringTable 解
        rows = parse_table(data)
        # 2) 不行就当 uasset 包解析，取导出数据再解
        if not rows:
            try:
                upk = mu.Upk(data)
                if upk.exports:
                    rows = parse_table(upk.export_data(upk.exports[0]))
            except Exception:                                 # noqa: BLE001
                pass
        have = len(locres.get(ns) or {})
        print(f"{ns}: 解出 {len(rows)} 行，locres 里已有 {have} 条")
        for key, text in rows[:3]:
            print("    ", key[:60], "=", text[:40])
        done += 1


if __name__ == "__main__":
    main()

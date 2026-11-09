"""把 .ustbin（StringTable 编译产物）解成 key → 文本。

实测布局（Game / UE5 自定义序列化）：

    [0:48)     包头（前 4 字节 0x9E2A83C1 魔数）
    [48:]      zlib 流；解压后：

        i32  size            —— 载荷剩余字节数
        u16  ?               —— 恒为 2（格式版本）
        u16  hash            —— 表名哈希
        FString table_name
        i32  row_count
        row_count × (FString key, FString text[, u32 附加哈希])

行与行之间偶尔还夹 4 字节的附加字段（看着是 key 的哈希），所以解析时
**不硬等到 count 行**：每次读完一对 key/text，如果下一个 4 字节解不出合理
的 FString 长度，就往后挪 1 字节重新同步（`_resync`），直到数据末端。
这样即使行内字段有出入，也能把整表啃下来。

    python tools/ustbin.py "ST_Interactor" 3
"""
import struct
import sys
import zlib

ZLIB_WINDOW = 48


def read_fstring(buf, pos):
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


def _plausible_len(buf, pos):
    """(kind, n)：'u' 正长度 / 'w' 负长度 UTF-16；不可信返回 (None, 0)。"""
    if pos + 4 > len(buf):
        return None, 0
    n = struct.unpack_from("<i", buf, pos)[0]
    if n == 0:
        return None, 0
    if n > 0:
        if n > 4096 or pos + 4 + n > len(buf):
            return None, 0
        return "u", n
    m = -n
    if m > 4096 or pos + 4 + m * 2 > len(buf):
        return None, 0
    return "w", m


def _read_key(buf, pos):
    kind, n = _plausible_len(buf, pos)
    if kind is None:
        return None, pos
    text, end = read_fstring(buf, pos)
    if not text or "\x00" in text:
        return None, pos
    printable = sum(1 for ch in text if " " <= ch <= "~" or ord(ch) > 0x7F)
    if printable < len(text) * 0.9:
        return None, pos
    return text, end


def parse_ustbin(blob):
    """-> (table_name, [(key, text), ...])；解不出来返回 ('', [])。"""
    if len(blob) <= ZLIB_WINDOW:
        return "", []
    try:
        raw = zlib.decompressobj().decompress(blob[ZLIB_WINDOW:])
    except zlib.error:
        raw = b""
    if len(raw) < 12:
        return "", []
    pos = 8                       # i32 size + u16 version + u16 hash
    name, pos = read_fstring(raw, pos)
    if pos + 4 > len(raw):
        return name, []
    count = struct.unpack_from("<i", raw, pos)[0]
    pos += 4
    rows = []
    while pos < len(raw) - 8 and (count <= 0 or len(rows) < count + 8):
        key, after_key = _read_key(raw, pos)
        if key is None:
            pos += 1
            continue
        text, after_text = read_fstring(raw, after_key) if _plausible_len(raw, after_key)[0] else ("", after_key)
        if not text and not _plausible_len(raw, after_key)[0]:
            pos += 1
            continue
        rows.append((key, text))
        pos = after_text
    return name, rows


def table_of(blob):
    return parse_ustbin(blob)


def main():
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core import loader

    filt = sys.argv[1] if len(sys.argv) > 1 else ""
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    targets = [p for p in loader.index()
               if p.endswith(".ustbin") and filt.lower() in p.lower()]
    print("候选 .ustbin", len(targets))
    shown = 0
    for path in targets:
        if shown >= limit:
            break
        try:
            blob = loader.load_blobs(path).get("ustbin") or b""
        except Exception as exc:                              # noqa: BLE001
            print("  读取失败", path.rsplit("/", 1)[-1], repr(exc)[:60])
            continue
        name, rows = parse_ustbin(blob)
        print(f"{name or os.path.basename(path)}: {len(rows)} 行")
        for key, text in rows[:4]:
            print("    ", key[:52], "=", text[:46])
        shown += 1


if __name__ == "__main__":
    main()

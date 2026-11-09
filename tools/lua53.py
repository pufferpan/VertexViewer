"""Lua 5.3 bytecode reader + tiny emulator (该游戏 .lua 是 luac 5.3 产物).

用法:
    python tools/lua53.py <file.lua> [--list] [--dump]

--dump   解码 main chunk 里的表构造，输出成 Lua 字面量文本
--list   只打印常量/结构统计
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

MAGIC = b"\x1bLua"

# ---- opcodes (Lua 5.3) -------------------------------------------------
OPNAMES = """MOVE LOADK LOADKX LOADBOOL LOADNIL GETUPVAL GETTABUP GETTABLE SETTABUP SETUPVAL
SETTABLE NEWTABLE SELF ADD SUB MUL MOD POW DIV IDIV BAND BOR BXOR SHL SHR UNM BNOT NOT LEN
CONCAT JMP EQ LT LE TEST TESTSET CALL TAILCALL RETURN FORLOOP FORPREP TFORCALL TFORLOOP
SETLIST CLOSURE VARARG EXTRAARG""".split()
OP = {n: i for i, n in enumerate(OPNAMES)}


class Reader:
    __slots__ = ("b", "p")

    def __init__(self, b: bytes):
        self.b = b
        self.p = 0

    def take(self, n: int) -> bytes:
        r = self.b[self.p:self.p + n]
        if len(r) != n:
            raise EOFError(f"want {n} bytes at {self.p}, got {len(r)}")
        self.p += n
        return r

    def u8(self) -> int:
        return self.take(1)[0]

    def i4(self) -> int:
        return int.from_bytes(self.take(4), "little", signed=True)

    def i8(self) -> int:
        return int.from_bytes(self.take(8), "little", signed=True)

    def sz4(self) -> int:
        return int.from_bytes(self.take(4), "little")

    def sz8(self) -> int:
        return int.from_bytes(self.take(8), "little")

    def dbl(self) -> float:
        return struct.unpack("<d", self.take(8))[0]


class Proto:
    def __init__(self):
        self.source = None
        self.linedefined = 0
        self.lastlinedefined = 0
        self.numparams = 0
        self.is_vararg = 0
        self.maxstack = 0
        self.code: list[int] = []
        self.k: list = []
        self.upvals: list[tuple[int, int, int]] = []
        self.protos: list[Proto] = []
        self.upvalnames: list[str | None] = []

    # ---- instruction decode
    def dec(self, i: int):
        op = i & 0x3F
        a = (i >> 6) & 0xFF
        kflag = (i >> 14) & 1
        b = (i >> 23) & 0x1FF
        c = (i >> 14) & 0x1FF
        bx = (i >> 14) & 0x3FFFF
        sbx = bx - 131071
        return op, a, kflag, b, c, bx, sbx


class Chunk:
    """Lua 5.3 chunk. 该游戏 luac 头里多写了 sizeof(int)/sizeof(size_t) 两字节。"""

    def __init__(self, data: bytes, intsize=4, sizesize=8):
        self.intsize = intsize
        self.sizesize = sizesize
        r = Reader(data)
        hdr = r.take(4)
        assert hdr == MAGIC, hdr
        self.version = r.u8()
        self.format = r.u8()
        assert r.take(6) == b"\x19\x93\r\n\x1a\n", "LUAC_DATA mismatch"
        self.sizes = [r.u8() for _ in range(5)]
        # [int, size_t, Instruction, lua_Integer, lua_Number]
        self.ints = r.i8()
        self.num = r.dbl()
        self.sizeupvalues = r.u8()
        self.main = self._function(r, None)
        self.endpos = r.p
        self.total = len(data)
        self.strip = self.main.source is None

    # ---- strings
    def _string(self, r: Reader) -> str | None:
        n = r.sz8() if self.sizesize == 8 else r.sz4()
        if n == 0:
            return None
        raw = r.take(n - 1)
        r.u8()  # trailing \0
        return raw.decode("utf-8", "replace")

    def _int(self, r: Reader) -> int:
        return r.i4() if self.intsize == 4 else r.i8()

    def _function(self, r: Reader, parent: Proto | None) -> Proto:
        f = Proto()
        f.source = self._string(r)
        f.linedefined = self._int(r)
        f.lastlinedefined = self._int(r)
        f.numparams = r.u8()
        f.is_vararg = r.u8()
        f.maxstack = r.u8()
        n = self._int(r)
        f.code = [int.from_bytes(r.take(4), "little") for _ in range(n)]
        n = self._int(r)
        for _ in range(n):
            t = r.u8()
            if t == 0:          # nil
                f.k.append(None)
            elif t == 1:        # boolean
                f.k.append(bool(r.u8()))
            elif t == 3:        # integer
                f.k.append(r.i8())
            elif t == 0x13:     # float
                f.k.append(r.dbl())
            elif t in (4, 0x14):  # short / long string
                f.k.append(self._string(r))
            else:
                raise ValueError(f"const type {t:#x} at {r.p}")
        n = self._int(r)
        f.upvals = [(r.u8(), r.u8(), r.u8()) for _ in range(n)]
        n = self._int(r)
        f.protos = [self._function(r, f) for _ in range(n)]
        if not self.strip:
            n = self._int(r)
            r.take(n)  # lineinfo
            n = self._int(r)
            for _ in range(n):
                self._string(r)   # varname
                self._int(r); self._int(r)
            n = self._int(r)
            f.upvalnames = [self._string(r) for _ in range(n)]
        return f


def load(path) -> Chunk:
    raw = Path(path).read_bytes()
    last = None
    for sizesize in (8, 4):
        for intsize in (4, 8):
            try:
                c = Chunk(raw, intsize, sizesize)
            except Exception as e:      # noqa: BLE001
                last = e
                continue
            if c.endpos == c.total:
                return c
            last = ValueError(f"trailing {c.total - c.endpos} bytes "
                              f"(int={intsize} size_t={sizesize})")
    raise SystemExit(f"{path}: parse failed: {last}")


# ---- disassembler ------------------------------------------------------
def listing(p: Proto, depth=0, out=None) -> list[str]:
    out = [] if out is None else out
    pad = "  " * depth
    out.append(f"{pad}function <{p.source or '?'}:{p.linedefined}-{p.lastlinedefined}> "
               f"params={p.numparams} vararg={p.is_vararg} stack={p.maxstack} "
               f"code={len(p.code)} consts={len(p.k)}")
    for i, c in enumerate(p.k):
        out.append(f"{pad}  K[{i}] = {c!r}")
    for i, ins in enumerate(p.code):
        op, a, kf, b, c, bx, sbx = Proto.dec(None, ins)
        nm = OPNAMES[op] if op < len(OPNAMES) else f"?{op}"
        extra = ""
        if nm in ("LOADK", "LOADKX", "CLOSURE"):
            extra = f" const={p.k[bx]!r}" if bx < len(p.k) else ""
        out.append(f"{pad}  [{i:3}] {nm:9} A={a} B={b} C={c} k={kf} Bx={bx} sBx={sbx}{extra}")
    for sub in p.protos:
        listing(sub, depth + 1, out)
    return out


# ---- emulator: rebuild the tables the main chunk builds ----------------
class Tbl:
    """Lua table stand-in: keeps insertion order, array part separately."""
    __slots__ = ("hash", "arr")

    def __init__(self):
        self.hash: dict = {}
        self.arr: list = []

    def set(self, key, val):
        if isinstance(key, float) and key.is_integer():
            key = int(key)
        if isinstance(key, int) and key >= 1 and key == len(self.arr) + 1:
            self.arr.append(val)
            return
        self.hash[key] = val

    def get(self, key):
        if isinstance(key, float) and key.is_integer():
            key = int(key)
        if isinstance(key, int) and 1 <= key <= len(self.arr):
            return self.arr[key - 1]
        return self.hash.get(key)

    def items(self):
        for i, v in enumerate(self.arr, 1):
            yield i, v
        yield from self.hash.items()


class Frame:
    __slots__ = ("p", "r", "pc", "varargs")

    def __init__(self, p, maxstack):
        self.p = p
        self.r = [None] * max(maxstack, 8)
        self.pc = 0
        self.varargs: list = []


def emulate(main: Proto, env: Tbl, depth=0) -> Tbl:
    """Run enough of the chunk to materialise the global tables it defines."""
    if depth > 6:
        return env
    f = Frame(main, main.maxstack)
    p = main
    code = p.code
    K = p.k

    def rk(val, is_const):
        return K[val] if is_const else f.r[val]

    while f.pc < len(code):
        ins = code[f.pc]
        f.pc += 1
        op, a, kf, b, c, bx, sbx = Proto.dec(None, ins)
        nm = OPNAMES[op] if op < len(OPNAMES) else "?"

        if nm == "MOVE":
            f.r[a] = f.r[b]
        elif nm == "LOADK":
            f.r[a] = K[bx]
        elif nm == "LOADKX":
            nxt = code[f.pc]
            f.r[a] = K[(nxt >> 14) & 0x3FFFF]
            f.pc += 1
        elif nm == "LOADBOOL":
            f.r[a] = bool(b)
            if c:
                f.pc += 1
        elif nm == "LOADNIL":
            for i in range(a, b + 1):
                f.r[i] = None
        elif nm == "LOADI":
            f.r[a] = sbx
        elif nm == "GETUPVAL":
            f.r[a] = env
        elif nm == "GETTABUP":
            t = env if b == 0 else f.r[b]
            f.r[a] = t.get(rk(c, kf)) if isinstance(t, Tbl) else None
        elif nm == "GETTABLE":
            t = f.r[b]
            f.r[a] = t.get(rk(c, kf)) if isinstance(t, Tbl) else None
        elif nm == "SETTABUP":
            t = env if a == 0 else f.r[a]
            if isinstance(t, Tbl):
                t.set(rk(b, (ins >> 23) & 0x1FF and False) if False else rk(b, False), rk(c, kf))
        elif nm == "SETUPVAL":
            pass
        elif nm == "SETTABLE":
            t = f.r[a]
            if isinstance(t, Tbl):
                t.set(rk(b, False), rk(c, kf))
        elif nm == "NEWTABLE":
            f.r[a] = Tbl()
        elif nm == "SELF":
            t = f.r[b]
            f.r[a + 1] = t
            f.r[a] = t.get(rk(c, kf)) if isinstance(t, Tbl) else None
        elif nm == "ADD":
            f.r[a] = _num(rk(b, (ins >> 23) & 0x1FF and False)) + _num(rk(c, kf))
        elif nm == "SUB":
            f.r[a] = _num(rk(b, False)) - _num(rk(c, kf))
        elif nm == "MUL":
            f.r[a] = _num(rk(b, False)) * _num(rk(c, kf))
        elif nm == "DIV":
            f.r[a] = _num(rk(b, False)) / _num(rk(c, kf))
        elif nm == "UNM":
            f.r[a] = -_num(f.r[b])
        elif nm == "LEN":
            t = f.r[b]
            f.r[a] = len(t.arr) if isinstance(t, Tbl) else 0
        elif nm == "CONCAT":
            f.r[a] = "".join(str(f.r[i]) for i in range(b, c + 1))
        elif nm == "JMP":
            f.pc += sbx
        elif nm == "SETLIST":
            t = f.r[a]
            if isinstance(t, Tbl):
                base = (c - 1) * 50 if c > 0 else getattr(f, "_lastset", 0)
                if c > 0:
                    f._lastset = base  # noqa: SLF001
                for i in range(b or (len(f.r) - a - 1)):
                    t.set(base + i + 1, f.r[a + 1 + i])
        elif nm == "CLOSURE":
            f.r[a] = Tbl()
        elif nm == "VARARG":
            for i in range(0, b if b else 0):
                f.r[a + i] = f.varargs[i] if i < len(f.varargs) else None
        elif nm == "CALL":
            if self_call(f.r[a]):
                f.r[a] = None
        elif nm in ("RETURN", "TAILCALL"):
            break
        elif nm == "EXTRAARG":
            pass
        elif nm == "TEST" or nm == "TESTSET":
            pass
        elif nm in ("EQ", "LT", "LE"):
            if not _cmp(nm, rk(b, (ins >> 23) & 0x1FF and False), rk(c, kf)):
                f.pc += 1
        elif nm in ("FORLOOP", "FORPREP", "TFORCALL", "TFORLOOP"):
            if nm == "FORPREP":
                f.pc += sbx
        elif nm == "LOADNIL":
            pass
        else:
            pass
    return env


def self_call(v):
    return False


def _num(v):
    return v if isinstance(v, (int, float)) else 0


def _cmp(nm, x, y):
    try:
        return {"EQ": x == y, "LT": x < y, "LE": x <= y}[nm]
    except TypeError:
        return False


def to_lua(v, indent=0, seen=None):
    seen = seen or set()
    pad = "  " * indent
    if isinstance(v, Tbl):
        if id(v) in seen:
            return "<recursion>"
        seen = seen | {id(v)}
        parts = []
        for k, val in v.items():
            if isinstance(k, str) and k.isidentifier():
                parts.append(f"{pad}  {k} = {to_lua(val, indent + 1, seen)},")
            elif isinstance(k, int) and 1 <= k <= len(v.arr):
                parts.append(f"{pad}  {to_lua(val, indent + 1, seen)},")
            else:
                parts.append(f"{pad}  [{k!r}] = {to_lua(val, indent + 1, seen)},")
        if not parts:
            return "{}"
        if all(not isinstance(k, int) or k > len(v.arr) for k, _ in v.items()):
            return "{\n" + "\n".join(parts) + f"\n{pad}}}"
        return "{\n" + "\n".join(parts) + f"\n{pad}}}"
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    return repr(v)


def main(argv):
    path = argv[1] if len(argv) > 1 else None
    if not path:
        print(__doc__)
        return 2
    ch = load(path)
    print(f"{Path(path).name}: lua {ch.version:#x} format={ch.format} "
          f"sizes={ch.sizes} int={ch.ints} num={ch.num} strip={ch.strip} "
          f"consumed={ch.endpos}/{ch.total}")
    if "--list" in argv:
        print("\n".join(listing(ch.main)))
        return 0
    if "--dump" in argv:
        env = emulate(ch.main, Tbl())
        print(to_lua(env))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

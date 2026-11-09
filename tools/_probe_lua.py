import pathlib

def u32(b, o):
    return int.from_bytes(b[o:o + 4], 'little')

def try_parse(b, start, nul):
    log = []
    o = start
    n = u32(b, o); o += 4
    if not (1 <= n <= 4000):
        return None
    code_from = o
    o += 4 * n
    if o > len(b):
        return None
    log.append(f"ncode={n} code@{code_from}..{o}")
    nk = u32(b, o); o += 4
    if not (0 <= nk <= 6000):
        return None
    log.append(f"nconst={nk}")
    for i in range(nk):
        if o >= len(b):
            return None
        t = b[o]; o += 1
        if t in (0, 1):
            pass
        elif t in (3, 0x13):
            o += 8
        elif t in (4, 0x14):
            if o >= len(b):
                return None
            sz = b[o]; o += 1
            if sz == 0:
                return None
            o += sz - 1 + (1 if nul else 0)
            log.append(f"  k{i}=str {b[o-1-(sz-1):o-(1 if nul else 0)]!r}" if False else f"  k{i}=str")
        else:
            return None
        if o > len(b):
            return None
    nu = u32(b, o); o += 4
    if not (0 <= nu <= 200):
        return None
    log.append(f"nupval={nu}")
    o += 3 * nu
    np = u32(b, o); o += 4
    if not (0 <= np <= 200):
        return None
    log.append(f"nproto={np}")
    return o, log

b = pathlib.Path('work/lua/GunsmithWeaponSocketData.lua').read_bytes()
for nul in (False, True):
    print("=== string trailing NUL written:", nul)
    for start in range(60, 100):
        r = try_parse(b, start, nul)
        if r:
            print("  ncode at", start, "-> ends", r[0], "of", len(b), r[1])

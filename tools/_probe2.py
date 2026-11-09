import pathlib

b = pathlib.Path('work/lua/GunsmithWeaponSocketData.lua').read_bytes()

def u32(o):
    return int.from_bytes(b[o:o + 4], 'little')

# walk constants starting at 167 (after nconst=10 at 163)
o = 167
for i in range(10):
    t = b[o]
    print(f"k{i} at {o} type={t:#04x}", end=" ")
    if t == 0:
        o += 1
        print("nil")
    elif t == 1:
        print("bool", b[o + 1]); o += 2
    elif t in (3, 0x13):
        print("num", b[o + 1:o + 9].hex()); o += 9
    elif t in (4, 0x14):
        sz = b[o + 1]
        s = b[o + 2:o + 2 + sz - 1]
        print(f"sz={sz} len(sz-1)={sz-1} start={o+2} end={o+2+sz-1} next={o+2+sz-1} {s[:50]!r}")
        o += 2 + sz - 1
    else:
        print("UNKNOWN"); break
print("after constants o =", o, "bytes:", b[o:o+16].hex())
print("u32 there:", u32(o))
print()
print("expected 'class' path: ", b[356:366])

"""Use mini_upk on the AH_64E BaseColor texture: properties + platform data dump."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.mini_upk import Upk, parse_properties  # noqa: E402

S = r"G:\xmcl-fetch\work\samples"
base = "T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a"
ua = open(os.path.join(S, base + ".uasset"), "rb").read()
ue = open(os.path.join(S, base + ".uexp"), "rb").read()
ub = open(os.path.join(S, base + ".ubulk"), "rb").read()

upk = Upk(ua, ue, ub)
print("legacy", upk.legacy_version, "ue3", upk.legacy_ue3, "ue5", upk.ver_ue5,
      "ue4", upk.ver_ue4, "lic", upk.ver_lic, "customver", len(upk.custom_versions))
print("header", upk.total_header_size, "flags 0x%08X" % upk.package_flags,
      "folder", repr(upk.folder_name))
print("names", upk.name_count, "imports", upk.import_count, "exports", upk.export_count,
      "depends@", upk.depends_offset)
print("names:", upk.names)
for i, imp in enumerate(upk.imports):
    print(f"  imp[{i}] {imp.class_package} :: {imp.class_name} outer={imp.outer} name={imp.name!r} path={upk.path_of(-(i + 1))}")
for i, e in enumerate(upk.exports):
    print(f"  exp[{i}] {e} class={upk.class_name_of(e)} flags=0x{e.object_flags:X} deps={e.deps}")

data = upk.export_data(upk.exports[0])
print("\nexport data len", len(data), "uexp len", len(ue))
props, end = parse_properties(upk, data)
for p in props:
    print(f"  prop {p.name:28s} {p.type:20s} size={p.size:6d} idx={p.array_index} extra={p.extra} val={p.value[:24].hex()}")
print("property list end offset 0x%x" % end)
print("\n--- tail after properties (platform data) ---")
tail = data[end:]
for i in range(0, min(len(tail), 0x260), 16):
    chunk = tail[i:i + 16]
    hx = " ".join(f"{c:02x}" for c in chunk)
    asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
    print(f"{end + i:04x}  {hx:<47}  {asc}")

import base64
import json
import os

base = r"G:\xmcl-fetch\work"
for src, dst in (("fe.json", "FPakEntry.cs"), ("fi.json", "FPakInfo.cs")):
    d = json.load(open(os.path.join(base, src), encoding="utf-8"))
    open(os.path.join(base, dst), "wb").write(base64.b64decode(d["content"]))
    print(dst, d["size"])

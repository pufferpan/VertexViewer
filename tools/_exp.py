import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for _p in (os.path.join(BASE, "work"), os.path.join(BASE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import mini_upk as mu                                 # noqa: E402
from core import loader                               # noqa: E402

for vp in sys.argv[1:]:
    try:
        ua = loader.read_entry(vp)
        ue = loader.read_entry(vp[:-7] + ".uexp")
    except Exception as e:
        print("!!", vp, e)
        continue
    upk = mu.Upk(ua, ue)
    print("==", os.path.basename(vp), "names", len(upk.names), "exports", len(upk.exports), "imports", len(upk.imports))
    for i, e in enumerate(upk.exports):
        cls = upk.class_name_of(e)
        print(f"   [{i}] {e.name}  class={cls}  size={e.size} off={e.offset}")

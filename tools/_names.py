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

for VP in sys.argv[1:]:
    ua = loader.read_entry(VP)
    ue = loader.read_entry(VP[:-7] + ".uexp") or b""
    upk = mu.Upk(ua, ue)
    print(f"=== {VP.rsplit('/',1)[-1]} names={len(upk.names)}")
    for i, n in enumerate(upk.names):
        print(f"  [{i:3}] {n}")

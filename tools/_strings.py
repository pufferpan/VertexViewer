import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
pat = re.compile(rb"[ -~]{4,}")
for p in sys.argv[1:]:
    b = pathlib.Path(p).read_bytes()
    print("==", p, len(b))
    seen = set()
    for m in pat.finditer(b):
        s = m.group().decode("ascii", "replace")
        if s in seen:
            continue
        seen.add(s)
        print("   ", s)

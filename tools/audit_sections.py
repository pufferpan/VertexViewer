"""审计多 section 网格的「section → 材质」解析情况。

重点看两件事：
1. `material_path` 为空的 section 有多少（只能靠下标兜底，等于依赖材质列表顺序）；
2. `material_path` 里写的名字在本模型材质列表里找不找得到（找不到就落到下标兜底，
   多材质网格一旦顺序错，就是「贴图在、但贴到了别的部件上」）。

    python tools/audit_sections.py [上限]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("VERTEXVIEWER_NO_UEFORMAT", "1")

from core import loader  # noqa: E402

CATALOG = r"G:\xmcl-fetch\work\mesh_catalog.json"


def fix(path: str) -> str:
    path = path.replace("\\", "/")
    return path if path.startswith("..") else "../../../" + path


def stem(path: str) -> str:
    name = os.path.basename(str(path or "").replace("\\", "/"))
    return name.rsplit(".", 1)[0].lower()


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    catalog = json.load(open(CATALOG, encoding="utf-8"))
    targets = [k for k, v in catalog.items() if v in ("StaticMesh", "SkeletalMesh")]

    checked = nomesh = multi = no_path = mismatch = 0
    samples = []
    for raw in targets:
        try:
            bundle = loader.load_model(fix(raw), want_textures=False)
        except Exception:                                   # noqa: BLE001
            continue
        mesh = getattr(bundle, "mesh", None)
        if mesh is None or not getattr(mesh, "lods", None):
            nomesh += 1
            continue
        checked += 1
        lod = mesh.lods[0]
        sections = list(getattr(lod, "sections", []) or [])
        mats = list(bundle.materials or [])
        if len(sections) > 1:
            multi += 1
            paths = [str(getattr(s, "material_path", "") or "") for s in sections]
            mnames = [stem(getattr(m, "pak_path", "") or getattr(m, "name", "")) for m in mats]
            if any(not p for p in paths):
                no_path += 1
                if len(samples) < 10:
                    samples.append((os.path.basename(raw), len(sections), len(mats), paths))
            elif any(stem(p) not in mnames for p in paths):
                mismatch += 1
                if len(samples) < 10:
                    samples.append((os.path.basename(raw), len(sections), len(mats), paths))
        if checked >= limit:
            break

    print(f"检查 {checked} 个网格（无网格 {nomesh}）：多 section {multi} 个，"
          f"其中 material_path 为空 {no_path}，路径名对不上材质 {mismatch}")
    for name, nsec, nmat, paths in samples:
        print(f"  {name}  sections={nsec} mats={nmat} paths={paths}")


if __name__ == "__main__":
    main()

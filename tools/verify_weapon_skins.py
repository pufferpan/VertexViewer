"""Verify skin receivers, exact part links and real assembly from installed paks."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import gunsmith as gs, loader, weapon_skins as ws


report = []
for receiver, selected in (("Rec_AR_M4A1-Std_001", "HavvkTech_p9"),
                           ("Rec_AR_HK416_021", "RecordAction_6b"),
                           ("Rec_AR_ScarH_045", "Obsidian_uc")):
    base = next(p for p in loader.index()
                if p.endswith("/" + receiver + "_3P.uasset"))
    skins = ws.list_skins(base)
    print(receiver, "skins:", [s.name for s in skins], flush=True)
    skin = next(s for s in skins if s.name == selected)
    recipe = gs.Recipe(base=base, parts=gs.official_loadout(base))
    linked = ws.apply_skin(recipe, skin)
    official = ws.official_parts(linked.recipe)
    assert official.recipe.base == skin.base
    assert len(official.recipe.parts) >= 2
    restored = ws.apply_skin(linked.recipe, base).recipe
    assert [p.vpath for p in restored.parts] == [p.vpath for p in recipe.parts]
    bundle = loader.load_model(skin.base)
    assert bundle.mesh and bundle.mesh.lods
    pairs = []
    for part in official.recipe.parts:
        print("  loading", Path(part.vpath).name, flush=True)
        assert ws._is_mesh(part.vpath), part.vpath
        data = loader.load_model(part.vpath)
        assert data.mesh and data.mesh.lods, part.vpath
        pairs.append((part, data))
    combined = gs.assemble(bundle, pairs, base_vpath=skin.base)
    lod = combined.mesh.lods[0]
    assert np.isfinite(lod.positions).all()
    assert lod.indices.max() < len(lod.positions)
    assert len(combined.materials) == len(lod.sections)
    row = dict(receiver=receiver, skins=len(skins), skin=skin.name,
               kit_parts=skin.part_count, linked_parts=len(linked.changed),
               retained_parts=len(linked.retained), official_parts=len(pairs),
               triangles=lod.triangle_count)
    print(json.dumps(row), flush=True)
    report.append(row)
out = Path(__file__).resolve().parents[1] / "work/fix-20261101/skin-verification.json"
out.write_text(json.dumps(report, indent=2), encoding="utf-8")
print("Verified exact links, original restoration and real skin assemblies", flush=True)

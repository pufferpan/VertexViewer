"""Audit real skin kit additions against official instances and parent sockets."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import gunsmith as gs, weapon_skins as ws
from core.types import MeshLOD


report = []
for receiver, selected in (("Rec_AR_M4A1-Std_001", "HavvkTech_p9"),
                           ("Rec_AR_HK416_021", "RecordAction_6b"),
                           ("Rec_AR_ScarH_045", "Obsidian_uc")):
    base = next(p for p in ws._model_paths()
                if p.endswith("/" + receiver + "_3P.uasset"))
    skin = next(s for s in ws.list_skins(base) if s.name == selected)
    original = gs.official_loadout(base)
    recipe = gs.Recipe(base=skin.base, skin_base=base, skin_id=skin.id)
    result = ws.official_parts(recipe)
    identities = {ws.part_identity(p.vpath) for p in original}
    added = []
    for part in result.recipe.parts:
        if ws.part_identity(part.vpath) in identities:
            continue
        family = gs.mount_family(part.vpath, part.slot)
        assert family in ws._PRIMARY_ORDER, part.vpath
        parent = result.recipe.base
        for wanted in gs.PARENT_FAMILY.get(family, ()):
            candidate = next((p for p in result.recipe.parts
                              if gs.mount_family(p.vpath, p.slot) == wanted), None)
            if candidate is not None:
                parent = candidate.vpath
                break
        hit = gs.find_socket(parent, gs.socket_candidates(family), prefer=part.socket)
        assert hit and part.socket and hit[0] == part.socket, (part.vpath, parent)
        added.append(dict(part=Path(part.vpath).stem, socket=part.socket,
                          parent=Path(parent).stem))
    paths = [p.vpath for p in result.recipe.parts]
    assert not any("Other_sr25-cqbRailcover_014_HavvkTech" in p for p in paths)
    if receiver == "Rec_AR_HK416_021":
        body = next(p for p in result.recipe.parts
                    if ws.part_identity(p.vpath) == "sto_a_hk416c_041")
        rods = next(p for p in result.recipe.parts
                    if ws.part_identity(p.vpath) == "sto_a_hk416c-b_089")
        assert rods.socket == "416cPart_point"
        assert gs._sockets.socket_matrix(result.recipe.base, rods.socket) is not None
    mounts = ws._preset_mounts(base)
    lod = MeshLOD(positions=np.array([[0, 0, 0], [.001, .001, .001]], np.float32))
    with patch.object(gs, "_bbox_fallback", wraps=gs._bbox_fallback) as fallback:
        plan = gs.resolve_placements(result.recipe.base, lod,
                                     [(p, lod) for p in result.recipe.parts])
    assert fallback.call_count == 0, [call.args[0].vpath for call in fallback.call_args_list]
    auxiliary_matrices = []
    for part in result.recipe.parts:
        if gs.asset_prefix(part.vpath) not in ("Other", "Dev"):
            continue
        owners = [(p, n) for p in result.recipe.parts if p is not part
                  for n in gs._sockets.socket_names(p.vpath)
                  if n.casefold() == part.socket.casefold()]
        assert len(owners) == 1, (part.vpath, part.socket, owners)
        owner, socket = owners[0]
        expected = plan[id(owner)] @ gs._sockets.socket_matrix(owner.vpath, socket)
        np.testing.assert_allclose(plan[id(part)], expected, atol=1e-6)
        auxiliary_matrices.append(dict(part=Path(part.vpath).stem, socket=socket,
                                       parent=Path(owner.vpath).stem))
    row = dict(receiver=receiver, skin=skin.name, parts=len(paths),
               verified_new_primary_mounts=added, omitted=list(result.omitted),
               fallback_count=fallback.call_count,
               verified_auxiliary_matrices=auxiliary_matrices,
               sr25_railcover_has_same_gun_instance=(
                   "other_sr25-cqbrailcover_014" in mounts),
               parts_and_sockets=[dict(part=Path(p.vpath).stem, socket=p.socket)
                                  for p in result.recipe.parts])
    print(json.dumps(row, ensure_ascii=False), flush=True)
    report.append(row)
out = Path(__file__).resolve().parents[1] / "work/features-20261101/skin-mount-verification.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("Verified no uninstanced auxiliary additions and all new primary parent sockets", flush=True)

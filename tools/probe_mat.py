"""Acceptance probe for core/material.py.

Prints, for a set of real material instances:
    parent material, scalar/vector/texture parameters, resolved slots,
    metallic/roughness and the GenTexDirHD twin-dir texture lookup.

Run:  python tools/probe_mat.py [count]
"""
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import pakpick                                  # noqa: E402
from core.material import (load_material_from_path,          # noqa: E402
                           load_material_json, resolve_texture_path)

PATH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_mat_paths.json")


def read_fn(vpath):
    return pakpick.extract(vpath)


def pick(count=6):
    with open(PATH_FILE, "r", encoding="utf-8") as fh:
        paths = json.load(fh)
    models = [p for p in paths
              if "DeltaForce/Content/Models/" in p and "/MI_" in p
              and p.endswith(".uasset")]
    random.seed(11)
    picks = random.sample(models, min(count, len(models)))
    # a character material showcases the _C/_MRA/_N suffix scheme
    for extra in models:
        if "Hero_HD" in extra and extra not in picks and len(picks) < count + 1:
            picks.append(extra)
            break
    return picks


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    started = time.time()
    ok = fail = 0
    slots_seen = {}
    parents = []
    for i, vpath in enumerate(pick(count), 1):
        print("=" * 100)
        print(f"[{i}] {vpath}")
        try:
            t0 = time.time()
            mat = load_material_from_path(vpath, read_fn)
            dt = time.time() - t0
        except Exception as exc:                            # noqa: BLE001
            fail += 1
            print(f"  LOAD FAILED: {type(exc).__name__}: {exc}")
            continue
        if mat is None:
            fail += 1
            print("  LOAD FAILED: no material (missing .uasset?)")
            continue
        ok += 1
        print(f"  name={mat.name!r}  ({dt * 1000:.0f} ms)")
        print(f"  parent={mat.parent or '-'}")
        if mat.parent:
            parents.append(mat.parent)
        print(f"  metallic={mat.metallic:.3f} roughness={mat.roughness:.3f} "
              f"base_color={tuple(round(c, 3) for c in mat.base_color)} "
              f"two_sided={mat.two_sided} blend={mat.blend_mode}")
        print(f"  slots: base_color={mat.base_color_texture or '-'}")
        print(f"         normal    ={mat.normal_texture or '-'}")
        print(f"         orm       ={mat.orm_texture or '-'}")
        print(f"         emissive  ={mat.emissive_texture or '-'}")
        if mat.scalar_params:
            shown = ", ".join(f"{k}={v:.3f}" for k, v in list(mat.scalar_params.items())[:8])
            print(f"  scalars ({len(mat.scalar_params)}): {shown}")
        else:
            print("  scalars: -")
        if mat.vector_params:
            shown = ", ".join(f"{k}={tuple(round(c, 2) for c in v)}"
                              for k, v in list(mat.vector_params.items())[:5])
            print(f"  vectors ({len(mat.vector_params)}): {shown}")
        if mat.texture_params:
            print(f"  textures ({len(mat.texture_params)}):")
            for pname, asset in mat.texture_params.items():
                base = os.path.basename(asset)
                slot = next((s for s in ("base_color_texture", "normal_texture",
                                         "orm_texture", "emissive_texture")
                             if getattr(mat, s, "") == asset), "")
                slots_seen[slot or "unmapped"] = slots_seen.get(slot or "unmapped", 0) + 1
                print(f"     {pname:<22} -> {base:<52} {slot or ''}")
        else:
            print("  textures: -")

    print("=" * 100)
    print(f"materials ok={ok} fail={fail} in {time.time() - started:.1f}s")
    print(f"slot census {slots_seen}")

    # ---- resolve_texture_path against the parent models of the parsed materials
    print("-" * 100)
    print("resolve_texture_path checks")
    for vpath in pick(3):
        mdir = os.path.dirname(vpath)
        for hint in ("BaseColor", "Normal", "ORM"):
            got = resolve_texture_path(mdir, hint)
            print(f"  {os.path.basename(mdir):<40} {hint:<10} -> "
                  f"{os.path.basename(got) if got else '-'}")
    # a model dir with a GenTexDirHD twin
    for probe in (
        "../../../DeltaForce/Content/Models/Weapons/Parts/Mag/"
        "Mag_AK74_545x39-30R-Std_004",
        "../../../DeltaForce/Content/Models/Vehicles/AH_64E/Appearance_Base",
    ):
        for hint in ("BaseColor", "MRA", "Normal"):
            got = resolve_texture_path(probe, hint)
            print(f"  {os.path.basename(probe):<40} {hint:<10} -> "
                  f"{os.path.basename(got) if got else '-'}")

    # ---- json sidecar round trip
    print("-" * 100)
    print("load_material_json checks")
    sample = {
        "name": "TestMat",
        "parent": "/Game/MaterialLib/Masters/M_Test",
        "textures": {
            "BaseColorMap": "/Game/Models/x/Textures/T_x_BaseColorMap_ab12cd34.uasset",
            "NormalMap": "/Game/Models/x/Textures/T_x_NormalMap_ab12cd34.uasset",
            "MRAMap": "/Game/Models/x/Textures/T_x_MRAMap_ab12cd34.uasset",
        },
        "scalars": {"Metallic": 0.75, "Roughness": 0.32},
        "vectors": {"BaseColor": [0.5, 0.4, 0.3, 1.0]},
    }
    mat = load_material_json(json.dumps(sample))
    print(f"  name={mat.name} parent={mat.parent} metallic={mat.metallic} "
          f"roughness={mat.roughness} base_color={mat.base_color}")
    print(f"  slots: bc={os.path.basename(mat.base_color_texture or '-')} "
          f"n={os.path.basename(mat.normal_texture or '-')} "
          f"orm={os.path.basename(mat.orm_texture or '-')}")
    # a flat/loose shape must not explode
    mat2 = load_material_json('{"Whatever": "x", "Values": [1, 2, 3]}')
    print(f"  loose json ok: name={mat2.name!r} scalars={mat2.scalar_params}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

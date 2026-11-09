"""Official weapon skins and their matching component meshes.

Matching is deliberately exact: a receiver's complete part number identifies
the weapon, and a component's complete part number identifies its compatible
skin variant. Commercial skin kits are confined to their weapon subdirectory.
No texture is borrowed from another gun or selected by a fuzzy name search.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import List, Tuple, Union

from core import gunsmith as gs

_PART_NUMBER = re.compile(r"^(.+?_\d{2,3})(?:_|$)")
_VIEW = re.compile(r"_(?:1p|3p)$", re.I)
_ASSET_PREFIXES = frozenset(("rec", "bar", "han", "muz", "mag", "sto",
                             "pisg", "frog", "acl", "sco", "att", "mou",
                             "other", "bip"))


def _stem(path: str) -> str:
    stem = _VIEW.sub("", os.path.splitext(os.path.basename(path))[0])
    # A few real skin receivers (e.g. QBZ95 Outers_1u) add this explicit
    # export prefix while retaining the same complete receiver number.
    return stem[6:] if stem.lower().startswith("parts_rec_") else stem


def part_identity(path: str) -> str:
    """Stable part identity, e.g. ``Rec_AR_M4A1-Std_001`` (lower case)."""
    hit = _PART_NUMBER.match(_stem(path))
    return hit.group(1).lower() if hit else ""


def _suffix(path: str) -> str:
    stem = _stem(path)
    hit = _PART_NUMBER.match(stem)
    return stem[len(hit.group(1)):].strip("_") if hit else ""


def _view(path: str) -> str:
    return "1p" if path.lower().endswith("_1p.uasset") else "3p"


@lru_cache(maxsize=1)
def _model_paths() -> Tuple[str, ...]:
    from core import loader
    out = []
    for path in loader.index():
        low = path.lower()
        if not low.endswith(("_3p.uasset", "_1p.uasset")):
            continue
        if any(piece in low for piece in ("/material/", "/materials/",
                                         "/texture/", "/textures/")):
            continue
        filename = os.path.basename(low)
        if (filename.split("_", 1)[0] not in _ASSET_PREFIXES
                and not filename.startswith("parts_rec_")):
            continue
        if part_identity(path):
            out.append(path)
    return tuple(sorted(out))


@lru_cache(maxsize=4096)
def _is_mesh(path: str) -> bool:
    from core import loader
    known = loader.is_mesh(path)
    if known is not None:
        return known
    # mesh_catalog is incomplete for new WeaponAppear assets. The uasset
    # header is small; verifying its export class needs no geometry decoding.
    try:
        from core.uasset import Package
        package = Package(loader.read_entry(path), path=path)
        return any(package.export_class(e) in ("StaticMesh", "SkeletalMesh")
                   for e in package.exports)
    except Exception:                           # unavailable/stale index entry
        return False


def clear_cache() -> None:
    """Call after rebuilding the asset index or switching the game directory."""
    _model_paths.cache_clear()
    _is_mesh.cache_clear()
    _canonical.cache_clear()
    _parts_in_kit.cache_clear()
    _skin_choices.cache_clear()
    _variant.cache_clear()
    _preset_mounts.cache_clear()
    _kit_gun_index.cache_clear()
    _kit_part_for.cache_clear()


def _kit_dir(path: str) -> str:
    marker = "/weaponappear/"
    offset = path.lower().find(marker)
    if offset < 0:
        return ""
    start = offset + len(marker)
    pieces = path[start:].split("/")
    if len(pieces) < 4:
        return ""
    # Ma2/HavvkTech_p9/M4A1/ and She4/ColdHunter_qt/M4A1/ both
    # bind a skin to one weapon, even when there is no Model/ layer.
    return path[:start] + "/".join(pieces[:3]) + "/"


@lru_cache(maxsize=2048)
def _canonical(path: str) -> str:
    identity = part_identity(path)
    if not identity:
        return path
    candidates = [p for p in _model_paths()
                  if part_identity(p) == identity and not _suffix(p)
                  and _is_mesh(p)]
    if not candidates:
        return path
    candidates.sort(key=lambda p: (_view(p) != _view(path),
                                   "/models/weapons/parts/" not in p.lower(),
                                   len(p), p))
    return candidates[0]


_WEAPON_CLASSES = frozenset((
    "ar", "smg", "dmr", "lmg", "mp", "pt", "sg", "sr", "bow", "melee",
    "pistol", "hmg", "gl", "launcher", "rifle", "shotgun", "sniper",
))


def _gun_key(text: str) -> str:
    """从机匣部件号 / 皮肤目录里取出枪名：``rec_ar_m4a1-std_001`` → ``m4a1``。"""
    low = text.strip().lower().replace("\\", "/")
    if "/" in low:
        low = low.rstrip("/").rsplit("/", 1)[-1]
    if low.startswith("parts_rec_"):
        low = low[10:]
    pieces = [p for p in low.split("_") if p]
    if pieces and pieces[0] in ("rec", "bar", "han", "muz", "mag", "sto"):
        pieces = pieces[1:]
    if pieces and pieces[0] in _WEAPON_CLASSES:
        pieces = pieces[1:]
    if not pieces:
        return ""
    head = pieces[0].split("-")[0]
    return re.sub(r"[^a-z0-9]", "", head)


@lru_cache(maxsize=1)
def _kit_gun_index() -> dict:
    """皮肤套装目录 → 枪名键：``…/WeaponAppear/Ma2/HavvkTech_p9/M4A1/`` → ``m4a1``。"""
    index = {}
    for path in _model_paths():
        kit = _kit_dir(path)
        if not kit:
            continue
        key = _gun_key(kit)
        if key:
            index.setdefault(key, set()).add(kit)
    return {key: tuple(sorted(dirs)) for key, dirs in index.items()}


def _kit_receiver(kit: str) -> str:
    """这个套装目录里的主件机匣（3P，确认有网格）。"""
    found = [p for p in _model_paths()
             if p.lower().startswith(kit.lower()) and _view(p) == "3p"
             and part_identity(p).startswith("rec_") and _is_mesh(p)]
    if not found:
        return ""
    found.sort(key=lambda p: (bool(_suffix(p)), len(p), p))
    return found[0]


def _skin_label(kit: str, receiver: str) -> str:
    """套装显示名：优先用皮肤目录名（玩家认这个），没有就退回部件后缀。"""
    pieces = [p for p in kit.rstrip("/").split("/") if p]
    name = pieces[-2] if len(pieces) >= 3 else ""
    if name and name.lower() not in ("model", "materials", "material"):
        return name
    return _suffix(receiver) or os.path.splitext(os.path.basename(receiver))[0]


@dataclass(frozen=True)
class WeaponSkin:
    id: str                         # receiver vpath; stable combo-box userData
    name: str                       # 原版, or the official asset's skin code
    base: str                       # selected receiver mesh
    family: str                     # exact receiver identity
    kit_dir: str = ""                # skin + weapon directory, never global
    is_default: bool = False
    part_count: int = 0              # verified mesh candidates, not mounted instances
    cross: bool = False              # kit receiver uses another part number than 原版


@dataclass(frozen=True)
class SkinApplication:
    recipe: gs.Recipe
    skin: WeaponSkin
    changed: Tuple[str, ...] = ()    # component display names that changed
    retained: Tuple[str, ...] = ()   # selections with no matching skin mesh
    omitted: Tuple[str, ...] = ()    # kit candidates without a verified instance


@lru_cache(maxsize=256)
def _parts_in_kit(skin: WeaponSkin) -> Tuple[str, ...]:
    if not skin.kit_dir:
        return ()
    return tuple(p for p in _model_paths()
                 if p.lower().startswith(skin.kit_dir.lower())
                 and _view(p) == "3p" and not part_identity(p).startswith("rec_")
                 and _is_mesh(p))


def list_skins(base: str) -> List[WeaponSkin]:
    """List every appearance skin that belongs to this weapon.

    Entries can be passed directly to :func:`apply_skin`. Original appearance
    is first. An ammo counter mesh is an accessory, not a selectable receiver.
    """
    family = part_identity(base)
    return list(_skin_choices(family, _gun_key(family)))


@lru_cache(maxsize=256)
def _skin_choices(family: str, gun_key: str = "") -> Tuple[WeaponSkin, ...]:
    if not family.startswith("rec_"):
        return ()
    skins = []
    seen = set()
    for path in _model_paths():
        if (part_identity(path) != family or _view(path) != "3p"
                or _suffix(path).lower().endswith(("_counter", "_forparts"))
                or not _is_mesh(path)):
            continue
        original = not _suffix(path)
        skin = WeaponSkin(id=path, name="原版" if original else _suffix(path),
                          base=path, family=family, kit_dir=_kit_dir(path),
                          is_default=original)
        count = len(_parts_in_kit(skin))
        skins.append(WeaponSkin(**{**skin.__dict__, "part_count": count}))
        seen.add(path)
    # 同一把枪的整套皮肤：套装里的机匣部件号常常和原版不同（换皮连模具都换），
    # 以前只认「部件号完全一致」就整批漏掉。目录本身已经把这套模型绑死在这把
    # 枪上，所以按枪名键把它们一并收进来，用套装自己的机匣当主件。
    if gun_key:
        for kit in _kit_gun_index().get(gun_key, ()):
            receiver = _kit_receiver(kit)
            if not receiver or receiver in seen:
                continue
            skin = WeaponSkin(id=receiver, name=_skin_label(kit, receiver),
                              base=receiver, family=part_identity(receiver),
                              kit_dir=kit, is_default=False,
                              cross=part_identity(receiver) != family)
            count = len(_parts_in_kit(skin))
            skins.append(WeaponSkin(**{**skin.__dict__, "part_count": count}))
            seen.add(receiver)
    # A receiver without an unskinned counterpart still remains selectable.
    skins.sort(key=lambda s: (not s.is_default, s.name.casefold(), s.id))
    return tuple(skins)


@lru_cache(maxsize=2048)
def _kit_part_for(source: str, skin: WeaponSkin) -> str:
    """套装里和原件「同槽位」的部件（部件号不同时靠它配对）。

    换皮套装是一整套换模具的模型：机匣号和原版不同，配件号自然也不同。
    部件号严格匹配不到时，按槽位在同一套装目录里找最像的一件——套装本身是
    成套做的，这一件就是这套皮肤装在这把枪上的那个配件。跨号套装靠它，
    同号套装缺件时也靠它补齐，否则会出现「换了皮肤只有机匣变色」。
    """
    if not skin.kit_dir:
        return ""
    slot = gs.guess_slot(source)
    want = {t for t in gs._match_tokens(source) if len(t) >= 3}
    scored = []
    for path in _model_paths():
        if not path.lower().startswith(skin.kit_dir.lower()):
            continue
        if part_identity(path).startswith("rec_") or not _is_mesh(path):
            continue
        if gs.guess_slot(path) != slot:
            continue
        hits = len(want & {t for t in gs._match_tokens(path) if len(t) >= 3})
        scored.append((hits, _view(path) != _view(source), len(path), path))
    if not scored:
        return ""
    scored.sort(key=lambda row: (-row[0], row[1], row[2], row[3]))
    return scored[0][3]


@lru_cache(maxsize=2048)
def _variant(source: str, skin: WeaponSkin) -> str:
    identity = part_identity(source)
    if not identity:
        return ""
    if skin.is_default:
        canonical = _canonical(source)
        return canonical if not _suffix(canonical) else ""
    candidates = []
    for path in _model_paths():
        if part_identity(path) != identity:
            continue
        if skin.kit_dir:
            if not path.lower().startswith(skin.kit_dir.lower()):
                continue
        else:
            # Legacy skins live alongside original parts. An exact component
            # identity AND exact skin suffix are both required here.
            if _suffix(path).casefold() != _suffix(skin.base).casefold():
                continue
        if _is_mesh(path):
            candidates.append(path)
    candidates.sort(key=lambda p: (_view(p) != _view(source), len(p), p))
    if candidates:
        return candidates[0]
    return _kit_part_for(source, skin)


def apply_skin(recipe: gs.Recipe,
               skin_id: Union[str, WeaponSkin]) -> SkinApplication:
    """Copy a recipe, change receiver, and link exact matching skin parts.

    Manual positioning and selection survive. A component with no matching
    skin variant returns to its pre-skin selection; the old skin is not leaked
    into another kit. Unknown/cross-weapon skin IDs raise ``ValueError``.
    """
    wanted = skin_id.id if isinstance(skin_id, WeaponSkin) else str(skin_id)
    choices = list_skins(recipe.skin_base or recipe.base)
    skin = next((s for s in choices if s.id == wanted), None)
    if skin is None:
        raise ValueError("该皮肤不属于当前枪械，或皮肤模型不可用")
    result = gs.Recipe.from_dict(recipe.to_dict())
    result.skin_base = _canonical(recipe.skin_base or recipe.base)
    result.skin_id = skin.id
    result.base = skin.base
    result.base_name = gs.display_name(skin.base)
    changed, retained = [], []
    for part in result.parts:
        source = part.skin_source or _canonical(part.vpath)
        # Keep an unsupported manually selected appearance rather than guess.
        if not source:
            source = part.vpath
        target = _variant(source, skin)
        label = part.name or os.path.splitext(os.path.basename(part.vpath))[0]
        previous = part.vpath
        part.vpath = target or source
        part.skin_source = "" if skin.is_default else source
        if part.vpath != previous:
            part.name = os.path.splitext(os.path.basename(part.vpath))[0]
            changed.append(label)
        if not target and not skin.is_default:
            retained.append(label)
    return SkinApplication(result, skin, tuple(changed), tuple(retained))


@lru_cache(maxsize=128)
def _preset_mounts(base: str) -> dict:
    """Exact component/socket/parent instances from this gun's preset trees."""
    from core import presets, sockets
    mounts = {}
    item = sockets.item_of_mesh(base)
    if not item:
        return mounts
    for desid in presets.presets_of_item(item):
        nodes = presets.dedup(presets.nodes_of(desid))
        by_index = {node[0]: node for node in nodes}
        for _idx, parent, child, socket in nodes:
            if not parent or parent not in by_index:
                continue
            name = sockets.socket_id_name(socket)
            if not name:
                continue
            parent_item = by_index[parent][2]
            parents = {part_identity(p) for p in sockets.item_meshes(parent_item)}
            for mesh in sockets.item_meshes(child):
                identity = part_identity(mesh)
                if identity:
                    mounts.setdefault(identity, set()).update(
                        (name, parent_id) for parent_id in parents if parent_id)
    return {identity: tuple(sorted(instances))
            for identity, instances in mounts.items()}


_PRIMARY_ORDER = ("barrel", "handguard", "stock", "grip", "mag",
                  "muzzle", "foregrip", "optic", "bipod")

# A compound stock is split between its adjustable body and an internal
# component. The 041 mesh has the rear cylinder; 089 has the two guide rods and
# butt plate. The receiver's 416cPart_point places 089's rear at -0.2366 m,
# matching the calibrated 041 rear (-0.2350 m), and its front inside the receiver.
# This is an explicit mesh/socket relation, never inferred from a directory.
_COMPOUND_COMPONENTS = (
    ("sto_a_hk416c_041", "sto_a_hk416c-b_089", "416cPart_point"),
)


def _add_compound_components(recipe: gs.Recipe, skin: WeaponSkin) -> None:
    selected = {part_identity(p.vpath) for p in recipe.parts}
    for body, component, socket in _COMPOUND_COMPONENTS:
        if body not in selected or component in selected:
            continue
        names = [n for n in gs._sockets.socket_names(skin.base)
                 if n.casefold() == socket.casefold()]
        if len(names) != 1 or gs._sockets.socket_matrix(skin.base, names[0]) is None:
            continue
        originals = [p for p in _model_paths()
                     if part_identity(p) == component and not _suffix(p)
                     and _view(p) == "3p" and _is_mesh(p)]
        if len(originals) != 1:
            continue
        source = originals[0]
        target = _variant(source, skin)
        # A skinned assembly may only add the explicitly corresponding skin
        # component. An unrelated kit's guide rods must not fill the gap.
        if not target:
            continue
        recipe.parts.append(gs.PartSpec(
            vpath=target, slot="stock", name=os.path.splitext(os.path.basename(target))[0],
            socket=names[0], slot_fit=True,
            skin_source="" if skin.is_default else source))
        selected.add(component)


def _mounted_primary(path: str, skin: WeaponSkin, parts: List[gs.PartSpec],
                     mounts: dict) -> gs.PartSpec | None:
    """Require an actual typed socket on the parent assembly in use."""
    family = gs.mount_family(path, gs.guess_slot(path))
    parents = gs.PARENT_FAMILY.get(family, ())
    parent_path = skin.base
    for wanted in parents:
        parent = next((p for p in parts
                       if gs.mount_family(p.vpath, p.slot) == wanted), None)
        if parent is not None:
            parent_path = _variant(parent.skin_source or parent.vpath, skin) or parent.vpath
            break
    prefer = next((name for name, parent_id in mounts.get(part_identity(path), ())
                   if parent_id == part_identity(parent_path)), "")
    hit = gs.find_socket(parent_path, gs.socket_candidates(family), prefer=prefer)
    if hit is None:
        return None
    slot = ("tactical" if family in ("foregrip", "bipod")
            else gs.guess_slot(path))
    return gs.PartSpec(vpath=path, slot=slot,
                       name=os.path.splitext(os.path.basename(path))[0],
                       socket=hit[0], slot_fit=True, skin_source=_canonical(path))


def official_parts(recipe: gs.Recipe) -> SkinApplication:
    """Reset to the selected skin's official kit, with original-part fallback.

    This is the explicit 'official parts' action. Ordinary skin changes call
    apply_skin and retain the user's configuration. A commercial kit may use a
    different barrel/stock design. Primary designs are used only when their
    actual parent has a matching socket. Auxiliary meshes need an existing
    preset instance or an explicit compound-component relation with a real
    socket; a skin directory is a candidate library, not mounted instances.
    """
    skin_id = recipe.skin_id or recipe.base
    choices = list_skins(recipe.skin_base or recipe.base)
    skin = next((s for s in choices if s.id == skin_id), None)
    if skin is None:
        raise ValueError("当前枪械没有可用的官方外观模型")
    working = gs.Recipe.from_dict(recipe.to_dict())
    canonical = _canonical(recipe.skin_base or recipe.base)
    working.parts = gs.official_loadout(canonical)
    kit = _parts_in_kit(skin)
    if kit:
        mounts = _preset_mounts(canonical)
        for family in _PRIMARY_ORDER:
            candidates = [p for p in kit
                          if gs.mount_family(p, gs.guess_slot(p)) == family]
            if not candidates:
                continue
            current = [p for p in working.parts
                       if gs.mount_family(p.vpath, p.slot) == family]
            # Existing instances, including repeated rail covers, retain their
            # exact sockets. Do not add every alternative mesh of the family.
            if any(_variant(p.skin_source or p.vpath, skin) in candidates for p in current):
                continue
            candidates.sort(key=lambda p: (part_identity(p) not in mounts, len(p), p))
            for path in candidates:
                # Multiple meshes in one primary family may include adapters
                # or optional child pieces. Without an official instance, we
                # cannot select another one just because it shares a prefix.
                if len(candidates) > 1 and part_identity(path) not in mounts:
                    continue
                spec = _mounted_primary(path, skin, working.parts, mounts)
                if spec is None:
                    continue
                working.parts = [p for p in working.parts
                                 if gs.mount_family(p.vpath, p.slot) != family]
                working.parts.append(spec)
                break
    _add_compound_components(working, skin)
    result = apply_skin(working, skin)
    selected = {part_identity(p.vpath) for p in result.recipe.parts}
    omitted = tuple(os.path.splitext(os.path.basename(p))[0] for p in kit
                    if part_identity(p) not in selected)
    return replace(result, omitted=omitted)

"""Material instance parsing for Game (UE4.26 cooked, split packages).

Game does not ship plain ``UMaterialInstanceConstant`` for its in-game
models -- the class is ``VirtualMaterialInstanceConstant`` (a plugin class under
``/Script/VirtualMaterialRuntime``), but the serialised property layout is the
stock one::

    Parent                    ObjectProperty  -> import index of the parent material
    ScalarParameterValues     ArrayProperty   -> FScalarParameterValue[]
    VectorParameterValues     ArrayProperty   -> FVectorParameterValue[]
    TextureParameterValues    ArrayProperty   -> FTextureParameterValue[]
    BasePropertyOverrides     StructProperty  (MaterialInstanceBasePropertyOverrides)
    StaticParameters          StructProperty  (StaticParameterSet)
    TextureStreamingData      ArrayProperty   (MaterialTextureInfo[] -- ignore)

The three parameter arrays share a peculiar serialisation: the value starts with
an ``int32`` count followed by *one* tagged ``StructProperty`` whose name is the
array's own name, whose struct type is the element type (e.g.
``ScalarParameterValue``) and whose size covers **all** elements.  Inside that
block the elements are written back-to-back as ordinary *tagged* property lists
terminated by ``None``::

    ParameterInfo     StructProperty (MaterialParameterInfo)
        Name          NameProperty   FName
        Association   ByteProperty   EMaterialParameterAssociation
        Index         IntProperty
    ParameterValue    FloatProperty / ObjectProperty / StructProperty(LinearColor)
    ExpressionGUID    StructProperty (Guid)

Everything here is verified against real assets (see ``tools/_diag_mat*.py``).
"""
from __future__ import annotations

import json
import os
import re
import struct
from typing import Dict, Iterable, List, Optional, Tuple

from core.types import Material

try:  # the verified minimal package reader (shared with tools/probe_tex.py)
    from tools.mini_upk import Upk, parse_properties
except Exception:  # pragma: no cover - package layout fallback
    Upk = None
    parse_properties = None


# --------------------------------------------------------------------------- #
# small binary helpers
# --------------------------------------------------------------------------- #
def _i32(blob: bytes, off: int) -> int:
    return struct.unpack_from("<i", blob, off)[0]


def _f32(blob: bytes, off: int) -> float:
    return struct.unpack_from("<f", blob, off)[0]


def _fname_at(upk, blob: bytes, off: int):
    """Read an ``FName`` (int32 index + int32 number) and return (text, next)."""
    idx, num = struct.unpack_from("<ii", blob, off)
    name = upk.name(idx) if upk is not None else ""
    if num:
        name = f"{name}_{num - 1}"
    return name, off + 8


def _strip_ext(vpath: str) -> str:
    low = vpath.lower()
    for ext in (".uasset", ".uexp", ".ubulk", ".uptnl"):
        if low.endswith(ext):
            return vpath[: -len(ext)]
    return vpath


# --------------------------------------------------------------------------- #
# object reference resolution (import / export tables)
# --------------------------------------------------------------------------- #
def object_path(upk, index: int) -> str:
    """Resolve an ``FPackageIndex`` (negative = import, positive = export)."""
    if not index:
        return ""
    if index < 0:
        imp_i = -index - 1
        if imp_i >= len(upk.imports):
            return ""
        imp = upk.imports[imp_i]
        name = imp.name
        outer = imp.outer
        if outer < 0:
            pkg_i = -outer - 1
            if pkg_i < len(upk.imports):
                pkg = upk.imports[pkg_i].name
                # package imports already carry the full object path in DF
                # packages -- do not staple the name onto it twice.
                if pkg == name or pkg.endswith("/" + name):
                    return pkg
                if name.startswith(pkg):
                    return name
                if pkg and not pkg.startswith("/Script/"):
                    return pkg.rstrip("/") + "/" + name
        elif outer > 0:
            parent = object_path(upk, outer)
            if parent:
                if parent == name or parent.endswith("/" + name) \
                        or parent.endswith("." + name):
                    return parent
                return parent + "." + name
        return name
    exp_i = index - 1
    if exp_i >= len(upk.exports):
        return ""
    exp = upk.exports[exp_i]
    outer = exp.outer_index
    if outer:
        parent = object_path(upk, outer)
        if parent:
            return parent + "." + exp.name
    return exp.name


def object_class(upk, index: int) -> str:
    """Class name of an ``FPackageIndex`` reference."""
    if not index:
        return ""
    if index < 0:
        imp_i = -index - 1
        if 0 <= imp_i < len(upk.imports):
            return upk.imports[imp_i].class_name
        return ""
    exp_i = index - 1
    if 0 <= exp_i < len(upk.exports):
        return upk.class_name_of(upk.exports[exp_i])
    return ""


# --------------------------------------------------------------------------- #
# parameter arrays
# --------------------------------------------------------------------------- #
def _param_elements(upk, blob: bytes) -> List[dict]:
    """Split a parameter-array value into per-parameter dicts.

    ``blob`` is the raw ``ArrayProperty`` value (count + wrapper struct).
    Returns a list of ``{"name", "association", "index", "value", "class"}``
    where ``value`` is the raw bytes of ``ParameterValue``.
    """
    out: List[dict] = []
    if parse_properties is None or len(blob) < 8:
        return out
    count = _i32(blob, 0)
    if count <= 0 or count > 4096:
        return out
    try:
        wrapper, _ = parse_properties(upk, blob, 4)
    except Exception:  # noqa: BLE001 - malformed package
        return out
    if not wrapper:
        return out
    body = wrapper[0].value
    if not isinstance(body, (bytes, bytearray)):
        return out
    pos = 0
    while pos < len(body):
        try:
            grp, nxt = parse_properties(upk, body, pos)
        except Exception:  # noqa: BLE001
            break
        if nxt <= pos:
            break
        pos = nxt
        if not grp:
            continue
        entry = {"name": "", "association": 0, "index": 0, "value": b"", "class": ""}
        for prop in grp:
            if prop.name == "ParameterInfo" and isinstance(prop.value, (bytes, bytearray)):
                try:
                    info, _ = parse_properties(upk, prop.value, 0)
                except Exception:  # noqa: BLE001
                    info = []
                for sub in info:
                    if sub.name == "Name" and isinstance(sub.value, (bytes, bytearray)):
                        entry["name"] = _fname_at(upk, sub.value, 0)[0]
                    elif sub.name == "Association" and isinstance(sub.value, (bytes, bytearray)):
                        entry["association"] = sub.value[0] if sub.value else 0
                    elif sub.name == "Index" and isinstance(sub.value, (bytes, bytearray)):
                        entry["index"] = _i32(sub.value, 0) if len(sub.value) >= 4 else 0
            elif prop.name == "ParameterValue":
                entry["value"] = prop.value if isinstance(prop.value, (bytes, bytearray)) else b""
                entry["class"] = prop.type or ""
        if entry["name"]:
            out.append(entry)
    return out


def _scalar_params(upk, blob: bytes) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for el in _param_elements(upk, blob):
        val = el["value"]
        if not isinstance(val, (bytes, bytearray)):
            continue
        if el["class"] == "FloatProperty" and len(val) == 4:
            out[el["name"]] = _f32(val, 0)
        elif el["class"] == "DoubleProperty" and len(val) == 8:
            out[el["name"]] = struct.unpack_from("<d", val, 0)[0]
        elif el["class"] == "BoolProperty":
            out[el["name"]] = 1.0 if (val and val[0]) else 0.0
        elif len(val) == 4:  # ByteProperty / IntProperty fallback
            out[el["name"]] = float(_i32(val, 0))
    return out


def _vector_params(upk, blob: bytes) -> Dict[str, Tuple[float, ...]]:
    out: Dict[str, Tuple[float, ...]] = {}
    for el in _param_elements(upk, blob):
        val = el["value"]
        if not isinstance(val, (bytes, bytearray)):
            continue
        if len(val) == 16:  # FLinearColor
            out[el["name"]] = tuple(struct.unpack_from("<4f", val, 0))
        elif len(val) == 12:  # FVector
            out[el["name"]] = tuple(struct.unpack_from("<3f", val, 0))
        elif len(val) == 4:
            f = _f32(val, 0)
            out[el["name"]] = (f, f, f, 1.0)
    return out


def _texture_params(upk, blob: bytes) -> Dict[str, str]:
    """``{param name: resolved asset path}`` for every texture parameter."""
    out: Dict[str, str] = {}
    for el in _param_elements(upk, blob):
        val = el["value"]
        if not isinstance(val, (bytes, bytearray)) or len(val) < 4:
            continue
        idx = _i32(val, 0)
        path = object_path(upk, idx) if idx else ""
        out[el["name"]] = path
    return out


# --------------------------------------------------------------------------- #
# name -> slot mapping
# --------------------------------------------------------------------------- #
#: CamelCase aware tokeniser: ``BaseColorMap`` -> [base, color, map],
#: ``T_VMGen_MRAMap_ab12`` -> [t, vmgen, mra, map, ab12].
_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_HASH_TAIL = re.compile(r"[0-9a-f]{8,}$")


def tokens(name: str) -> List[str]:
    """Lower-case word tokens of a UE name (CamelCase + separators split)."""
    if not name:
        return []
    base = _strip_ext(os.path.basename(name.replace("\\", "/")))
    base = _HASH_TAIL.sub("", base)
    parts: List[str] = []
    for chunk in re.split(r"[^A-Za-z0-9]+", base):
        if not chunk:
            continue
        parts.extend(p for p in _CAMEL_SPLIT.split(chunk) if p)
    return [p.lower() for p in parts]


#: slot -> rules.  ``words`` must appear as whole tokens, ``pairs`` as token
#: tuples, ``suffixes`` match the trailing token (``_c`` / ``_mra`` / ``_n``).
_SLOT_RULES: Dict[str, dict] = {
    "base_color_texture": {
        "words": ("basecolor", "basecolour", "albedo", "diffuse", "diffusemap",
                  "basecolormap", "colormap"),
        "pairs": (("base", "color"), ("base", "colour")),
        "suffixes": ("c", "bc", "diff", "d", "albedo"),
    },
    "normal_texture": {
        "words": ("normal", "normalmap", "nrm", "nrmmap", "bump", "ncemap",
                  "nce", "detailnormalmap", "bottomnormalmap"),
        "pairs": (),
        "suffixes": ("n", "nr", "nrm", "nc", "normal"),
    },
    "orm_texture": {
        "words": ("orm", "ormmap", "mra", "mramap", "arm", "rma", "mac",
                  "metallicroughness", "occlusionroughness", "specularmap"),
        "pairs": (("metallic", "roughness"), ("occlusion", "roughness")),
        "suffixes": ("mra", "orm", "m", "mr", "arm", "rma"),
    },
    "emissive_texture": {
        "words": ("emissive", "emissivemap", "emission", "emissionmap", "glow",
                  "selfillum", "emissivecolor"),
        "pairs": (),
        "suffixes": ("e", "em", "emi"),
    },
}

_SLOT_ORDER = ("emissive_texture", "normal_texture", "orm_texture",
               "base_color_texture")

_SLOT_SUFFIX = tuple((slot, _SLOT_RULES[slot]["suffixes"]) for slot in _SLOT_ORDER)
_SLOT_HINTS = tuple((slot, _SLOT_RULES[slot]["words"]) for slot in _SLOT_ORDER)


def compact(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _match_slot(name: str) -> Optional[str]:
    """Token based slot match; ``None`` when nothing matches confidently."""
    toks = tokens(name)
    if not toks:
        return None
    low = (name or "").lower()
    stripped = _HASH_TAIL.sub("", low)
    for slot in _SLOT_ORDER:
        rule = _SLOT_RULES[slot]
        for word in rule["words"]:
            if word in toks:
                return slot
        for word in rule["words"]:
            # multi-word hints are matched on the concatenated tokens
            if len(word) > 5 and word in "".join(toks):
                return slot
        for left, right in rule["pairs"]:
            if left in toks and right in toks:
                return slot
        for suf in rule["suffixes"]:
            if len(suf) > 1 and stripped.endswith("_" + suf):
                return slot
    return None


def slot_for_param(name: str) -> Optional[str]:
    """Map a material texture-parameter name to a :class:`Material` slot."""
    return _match_slot(name)


def slot_for_asset(asset_path: str) -> Optional[str]:
    """Map a texture *asset* name (``T_VMGen_BaseColorMap_ab12``) to a slot."""
    return _match_slot(asset_path)


def _first_scalar(params: Dict[str, float], hints: Iterable[str],
                  default: Optional[float] = None) -> Optional[float]:
    """Best matching scalar by *last* assignment order in ``hints`` priority."""
    best = default
    for hint in hints:
        for key, value in params.items():
            if hint in compact(key):
                best = value
    return best


_METALLIC_HINTS = ("metallic", "metalness", "metal", "metallicvalue")
_ROUGHNESS_HINTS = ("roughness", "rough", "glossiness", "gloss", "smoothness")
_BASECOLOR_VECTOR_HINTS = ("basecolor", "basecolorvalue", "tint", "diffusecolor")
_EMISSIVE_VECTOR_HINTS = ("emissive", "emission", "glow")


# --------------------------------------------------------------------------- #
# public: binary material assets
# --------------------------------------------------------------------------- #
_MI_CLASS_HINTS = ("materialinstance", "virtualmaterial")
_MATERIAL_CLASS_HINTS = ("material",)


def _pick_export(upk):
    """Prefer a material(-instance) export, else the largest export."""
    best = None
    for exp in upk.exports:
        cls = (upk.class_name_of(exp) or "").lower()
        if any(h in cls for h in _MI_CLASS_HINTS):
            return exp
        if best is None and any(h == cls for h in _MATERIAL_CLASS_HINTS):
            best = exp
    if best is not None:
        return best
    if upk.exports:
        return max(upk.exports, key=lambda e: e.serial_size)
    return None


def load_material(uasset: bytes, uexp: Optional[bytes] = None,
                  pak_path: str = "", ubulk: Optional[bytes] = None,
                  read_parent=None) -> Material:
    """Parse a ``UMaterialInstanceConstant``/``VirtualMaterialInstanceConstant``.

    ``uasset``/``uexp`` are the raw bytes pulled out of the pak (already
    decompressed); ``pak_path`` is only used for the ``Material.name`` /
    ``Material.pak_path`` fields and to resolve the parent when ``read_parent``
    is supplied.
    """
    if Upk is None:
        raise RuntimeError("tools/mini_upk.py is required to parse materials")
    upk = Upk(uasset, uexp, ubulk)
    export = _pick_export(upk)
    if export is None:
        raise ValueError("package contains no exports")

    material = Material(name=export.name, pak_path=pak_path)
    data = upk.export_data(export)
    try:
        props, _ = parse_properties(upk, data)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"property list parse failed: {exc}") from exc

    parent_path = ""
    static_switches: Dict[str, float] = {}
    for prop in props:
        value = prop.value
        if prop.name == "Parent" and isinstance(value, (bytes, bytearray)) and len(value) >= 4:
            parent_path = object_path(upk, _i32(value, 0))
        elif prop.name == "ScalarParameterValues" and isinstance(value, (bytes, bytearray)):
            material.scalar_params.update(_scalar_params(upk, value))
        elif prop.name == "VectorParameterValues" and isinstance(value, (bytes, bytearray)):
            material.vector_params.update(_vector_params(upk, value))
        elif prop.name == "TextureParameterValues" and isinstance(value, (bytes, bytearray)):
            material.texture_params.update(_texture_params(upk, value))
        elif prop.name == "BasePropertyOverrides" and isinstance(value, (bytes, bytearray)):
            material.two_sided = material.two_sided or _overrides_two_sided(upk, value)
            material.blend_mode = _overrides_blend_mode(upk, value) or material.blend_mode
        elif prop.name == "StaticParameters" and isinstance(value, (bytes, bytearray)):
            static_switches = _static_switches(upk, value)

    material.parent = parent_path
    if (upk.class_name_of(export) or "").lower() == "material":
        material.parent_parameter_names = tuple(upk.names)
        static_switches.update(_expression_switch_defaults(upk))
    # Child switch overrides must exist before inheriting parent defaults.
    material.scalar_params.update(static_switches)
    fill_slots(material)

    # a parent material may define the defaults (e.g. metallic/roughness)
    if read_parent is not None and parent_path:
        try:
            parent = read_parent(parent_path)
        except Exception:  # noqa: BLE001
            parent = None
        if parent is not None:
            inherits_defaults(material, parent)

    return material


def _overrides_two_sided(upk, blob: bytes) -> bool:
    try:
        props, _ = parse_properties(upk, blob, 0)
    except Exception:  # noqa: BLE001
        return False
    for prop in props:
        if "twosided" in compact(prop.name):
            val = prop.value
            return bool(val and val[0]) if isinstance(val, (bytes, bytearray)) else bool(val)
    return False


_BLEND_NAMES = {
    0: "Opaque", 1: "Masked", 2: "Translucent", 3: "Additive",
    4: "Modulate", 5: "AlphaComposite", 6: "AlphaHoldout",
}


def _overrides_blend_mode(upk, blob: bytes) -> str:
    try:
        props, _ = parse_properties(upk, blob, 0)
    except Exception:  # noqa: BLE001
        return ""
    for prop in props:
        if compact(prop.name) == "blendmode":
            val = prop.value
            if isinstance(val, (bytes, bytearray)) and len(val) >= 8:
                name = _fname_at(upk, val, 0)[0]
                if name:
                    return name.replace("BLEND_", "").title() or ""
                return _BLEND_NAMES.get(_i32(val, 0), "")
            if isinstance(val, (bytes, bytearray)) and val:
                return _BLEND_NAMES.get(val[0], "")
    return ""


def _expression_switch_defaults(upk) -> Dict[str, float]:
    """Default branches stored in the parent material's actual expressions."""
    out = {}
    for exp in upk.exports:
        if upk.class_name_of(exp) != "MaterialExpressionStaticSwitchParameter":
            continue
        try:
            props, _ = parse_properties(upk, upk.export_data(exp))
            name, enabled = "", 0.0
            for prop in props:
                if prop.name == "ParameterName" and len(prop.value) >= 8:
                    name = _fname_at(upk, prop.value, 0)[0]
                elif prop.name == "DefaultValue":
                    enabled = float(bool(prop.extra.get("bool_value", 0)))
            if name:
                out[name] = enabled
        except Exception:
            continue
    return out


def _static_switches(upk, blob: bytes) -> Dict[str, float]:
    """``StaticParameterSet.StaticSwitchParameters`` -> ``{name: 0/1}``."""
    out: Dict[str, float] = {}
    try:
        props, _ = parse_properties(upk, blob, 0)
    except Exception:  # noqa: BLE001
        return out
    for prop in props:
        if "switch" not in compact(prop.name):
            continue
        value = prop.value
        if not isinstance(value, (bytes, bytearray)) or len(value) < 8:
            continue
        try:
            wrapper, _ = parse_properties(upk, value, 4)
        except Exception:  # noqa: BLE001
            continue
        if not wrapper:
            continue
        body = wrapper[0].value
        if not isinstance(body, (bytes, bytearray)):
            continue
        pos = 0
        while pos < len(body):
            try:
                grp, nxt = parse_properties(upk, body, pos)
            except Exception:  # noqa: BLE001
                break
            if nxt <= pos:
                break
            pos = nxt
            name, switch, overridden = "", 0.0, True
            for sub in grp:
                if sub.name == "ParameterInfo" and isinstance(sub.value, (bytes, bytearray)):
                    try:
                        info, _ = parse_properties(upk, sub.value, 0)
                    except Exception:  # noqa: BLE001
                        info = []
                    for q in info:
                        if q.name == "Name" and isinstance(q.value, (bytes, bytearray)):
                            name = _fname_at(upk, q.value, 0)[0]
                elif sub.name in ("Value", "ParameterValue") and isinstance(sub.value, (bytes, bytearray)):
                    switch = float(bool(sub.extra.get("bool_value", 0))) if sub.type == "BoolProperty" else float(bool(sub.value and sub.value[0]))
                elif sub.name == "bOverride":
                    overridden = bool(sub.extra.get("bool_value", 0))
            if name and overridden:
                out[name] = switch
    return out


def fill_slots(material: Material) -> Material:
    """Populate ``base_color_texture``/``normal_texture``/... from parameters."""
    candidates: Dict[str, List[Tuple[int, int, str, str]]] = {}
    for order, (param_name, asset) in enumerate(material.texture_params.items()):
        if not asset:
            continue
        slot = slot_for_param(param_name) or slot_for_asset(asset)
        if not slot:
            continue
        candidates.setdefault(slot, []).append(
            (_slot_penalty(param_name, asset), order, param_name, asset))
    for slot, items in candidates.items():
        items.sort()
        setattr(material, slot, items[0][3])
    _apply_scalar_defaults(material)
    return material


#: Words that mark a *secondary* texture (detail maps, UI variants, ...).
_SECONDARY_WORDS = ("detail", "bottom", "second", "overlay", "blend", "extra",
                    "mask", "ui", "hd2", "low", "alt", "sub", "layer", "decay")


def _slot_penalty(param_name: str, asset: str) -> int:
    """Lower is better: prefer short, non-secondary parameter names."""
    toks = tokens(param_name)
    penalty = sum(3 for w in toks if w in _SECONDARY_WORDS)
    penalty += len(toks) - 1 if len(toks) > 1 else 0
    penalty += max(0, len(param_name) - 16) // 4
    if any(w in compact(asset) for w in _SECONDARY_WORDS):
        penalty += 2
    return penalty


_EMISSIVE_BOOST_WORDS = ("bright", "boost", "highlight", "flash", "mult", "multiplier",
                         "scale", "intensity", "power", "strength")


def _is_emissive_boost(key: str) -> bool:
    """判断这个参数是不是「高亮态倍率」而不是基础自发光颜色。

    UE 的屏幕/序列帧材质常挂 `EmissionColor_Bright`、`EmissiveIntensity` 这种参数，
    它们只是把某个状态调亮；当成默认 emissive 用会让整块面直接过曝成一坨白。
    """
    k = compact(key)
    return any(w in k for w in _EMISSIVE_BOOST_WORDS)


def _apply_scalar_defaults(material: Material) -> None:
    metallic = _first_scalar(material.scalar_params, _METALLIC_HINTS)
    if metallic is not None:
        material.metallic = float(metallic)
    roughness = _first_scalar(material.scalar_params, _ROUGHNESS_HINTS)
    if roughness is not None:
        material.roughness = float(roughness)
    for hint_set, attr in ((_BASECOLOR_VECTOR_HINTS, "base_color"),
                           (_EMISSIVE_VECTOR_HINTS, "emissive")):
        for key, vec in material.vector_params.items():
            if not any(h in compact(key) for h in hint_set):
                continue
            if attr == "emissive" and _is_emissive_boost(key):
                # `EmissionColor_Bright` 这类是「高亮态」用的倍率/颜色，默认状态不开。
                # 之前把它当 emissive 读，配上 Screen/Sequence 那种整张白色的
                # EmissiveMap，整个模型就被加成一坨白 —— 手机、手表这类最常见。
                continue
            if (attr == "emissive" and material.parent_parameter_names is not None
                    and key not in material.parent_parameter_names):
                # A skin instance may retain EmissiveColor=(1,1,1,0) even
                # though its current parent has no such shader parameter.
                continue
            if attr == "base_color" and len(vec) >= 4:
                material.base_color = tuple(float(v) for v in vec[:4])
            elif attr == "emissive" and len(vec) >= 3:
                material.emissive = tuple(float(v) for v in vec[:3])
    # A stored color is not necessarily active: official weapon skins retain
    # effect colors while explicitly disabling them in their static switches.
    switches = {compact(key): value for key, value in material.scalar_params.items()}
    if switches.get("useemissivecolor") == 0:
        material.emissive = (0.0, 0.0, 0.0)


def inherits_defaults(material: Material, parent: Material) -> Material:
    """Take unnamed texture slots / scalar defaults from a parent material."""
    for slot in ("base_color_texture", "normal_texture", "orm_texture",
                 "emissive_texture"):
        if not getattr(material, slot, "") and getattr(parent, slot, ""):
            setattr(material, slot, getattr(parent, slot))
    for key, val in (parent.scalar_params or {}).items():
        material.scalar_params.setdefault(key, val)
    for key, val in (parent.vector_params or {}).items():
        material.vector_params.setdefault(key, val)
    for key, val in (parent.texture_params or {}).items():
        material.texture_params.setdefault(key, val)
    material.parent_parameter_names = parent.parent_parameter_names
    # Recompute after resolving the parent; an earlier instance-only pass may
    # have mistaken a stale, unbound color for constant emission.
    material.emissive = (0.0, 0.0, 0.0)
    if not material.parent:
        material.parent = parent.name
    fill_slots(material)
    return material


# --------------------------------------------------------------------------- #
# public: paths / pak blobs
# --------------------------------------------------------------------------- #
def _read_sibling(read_fn, base: str, ext: str) -> Optional[bytes]:
    try:
        blob = read_fn(base + ext)
    except Exception:  # noqa: BLE001 - missing sibling is normal
        return None
    return blob or None


def load_material_from_path(vpath: str, read_fn, oodle=None,
                            read_parent=None) -> Optional[Material]:
    """Load a material (instance) straight from the pak index.

    ``read_fn(vpath) -> bytes``; ``oodle`` is accepted for API symmetry with
    :mod:`core.texture` and is unused because the pak layer already inflates
    entries.
    """
    base = _strip_ext(vpath)
    uasset = read_fn(base + ".uasset")
    if not uasset:
        return None
    uexp = _read_sibling(read_fn, base, ".uexp")
    ubulk = _read_sibling(read_fn, base, ".ubulk")
    try:
        material = load_material(uasset, uexp, vpath, ubulk, read_parent=read_parent)
    except Exception:  # noqa: BLE001 - fall through to the parent-only view
        material = Material(name=os.path.basename(base), pak_path=vpath)
        parent = _peek_parent(uasset, uexp, ubulk)
        if parent:
            material.parent = parent
    if not material.pak_path:
        material.pak_path = vpath
    if not material.name:
        material.name = os.path.basename(base)
    return material


def _peek_parent(uasset: bytes, uexp: Optional[bytes],
                 ubulk: Optional[bytes] = None) -> str:
    """Best effort parent-material path even when the property list is broken."""
    if Upk is None:
        return ""
    try:
        upk = Upk(uasset, uexp, ubulk)
        export = _pick_export(upk)
        if export is None:
            return ""
        props, _ = parse_properties(upk, upk.export_data(export))
    except Exception:  # noqa: BLE001
        return ""
    for prop in props:
        if prop.name == "Parent" and isinstance(prop.value, (bytes, bytearray)) and len(prop.value) >= 4:
            return object_path(upk, _i32(prop.value, 0))
    return ""


# --------------------------------------------------------------------------- #
# public: json material sidecars
# --------------------------------------------------------------------------- #
_TEXTURE_KEY_HINTS = ("texture", "tex", "map", "image", "pic", "贴图")
_SCALAR_KEY_HINTS = ("metallic", "roughness", "specular", "gloss", "opacity",
                     "metallicvalue", "roughnessvalue", "scalar", "param")
_VECTOR_KEY_HINTS = ("color", "colour", "tint", "emissive", "basecolor", "param")


def _looks_like_texture_asset(value: str) -> bool:
    low = value.lower()
    return (low.endswith((".uasset", ".png", ".tga", ".dds", ".jpg", ".jpeg"))
            or "/textures/" in low.replace("\\", "/")
            or low.startswith("t_"))


def load_material_json(text_or_path) -> Material:
    """Parse a material description in JSON form.

    Accepts either raw JSON text or a path to a ``.json`` file.  The shape of
    such sidecars is not fixed by the game (the paks ship none next to models),
    so this is deliberately permissive::

        {"name": "M4", "parent": "...", "textures": {"BaseColorMap": "..."},
         "scalars": {"Metallic": 0.8}, "vectors": {"BaseColor": [1, 1, 1, 1]}}

    Values are also discovered by *content* (an ``.uasset`` path is a texture, a
    float is a scalar, a 3/4 element list is a vector), so keys do not have to
    be spelled exactly as above.
    """
    raw = text_or_path
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        stripped = raw.lstrip()
        if not stripped.startswith(("{", "[")) and os.path.exists(raw):
            with open(raw, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
    doc = json.loads(raw)

    material = Material(name="")
    name_hints, parent = "", ""
    textures: Dict[str, str] = {}
    scalars: Dict[str, float] = {}
    vectors: Dict[str, Tuple[float, ...]] = {}

    def walk(obj, key: str, depth: int = 0) -> None:
        nonlocal name_hints, parent
        if depth > 6:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, k, depth + 1)
            return
        if isinstance(obj, (list, tuple)):
            # a list of {name, value} pairs is common in exporter output
            if obj and all(isinstance(x, dict) for x in obj):
                for item in obj:
                    nm = ""
                    for nk in ("Name", "name", "ParameterName", "Param", "param"):
                        if isinstance(item.get(nk), str):
                            nm = item[nk]
                            break
                    val = item.get("Value", item.get("value"))
                    if nm and val is not None:
                        _store(nm, val)
                return
            if len(obj) in (3, 4) and all(isinstance(x, (int, float)) for x in obj):
                vectors[key] = tuple(float(x) for x in obj)
            return
        _store(key, obj)

    def _store(key: str, value) -> None:
        nonlocal name_hints, parent
        ckey = compact(key)
        if isinstance(value, str):
            low = key.lower()
            if low in ("name", "assetname", "materialname") and not name_hints:
                name_hints = value
                return
            if low == "parent":
                parent = value
                return
            if _looks_like_texture_asset(value):
                textures[key] = value
                return
            if any(h in ckey for h in _TEXTURE_KEY_HINTS):
                textures[key] = value
            return
        if isinstance(value, bool):
            scalars[key] = 1.0 if value else 0.0
            return
        if isinstance(value, (int, float)):
            scalars[key] = float(value)
            return

    walk(doc, "")

    if isinstance(doc, dict):
        for nk in ("name", "Name", "materialName", "MaterialName"):
            if isinstance(doc.get(nk), str) and not name_hints:
                name_hints = doc[nk]
        for pk in ("parent", "Parent", "parentMaterial", "ParentMaterial"):
            if isinstance(doc.get(pk), str) and not parent:
                parent = doc[pk]
        # explicit containers beat the generic walk
        for ck in ("textures", "Textures", "textureParameters", "TextureParameters"):
            sub = doc.get(ck)
            if isinstance(sub, dict):
                for k, v in sub.items():
                    if isinstance(v, str) and v:
                        textures[k] = v
        for ck in ("scalars", "Scalars", "scalarParameters", "ScalarParameters",
                   "parameters", "Parameters"):
            sub = doc.get(ck)
            if isinstance(sub, dict):
                for k, v in sub.items():
                    if isinstance(v, bool):
                        scalars[k] = 1.0 if v else 0.0
                    elif isinstance(v, (int, float)):
                        scalars[k] = float(v)
                    elif isinstance(v, (list, tuple)) and len(v) in (3, 4):
                        vectors[k] = tuple(float(x) for x in v)
        for ck in ("vectors", "Vectors", "vectorParameters", "VectorParameters"):
            sub = doc.get(ck)
            if isinstance(sub, dict):
                for k, v in sub.items():
                    if isinstance(v, (list, tuple)) and len(v) in (3, 4):
                        vectors[k] = tuple(float(x) for x in v)

    material.name = name_hints or material.name
    material.parent = parent
    material.texture_params = dict(textures)
    material.scalar_params = dict(scalars)
    material.vector_params = dict(vectors)
    fill_slots(material)
    return material


# --------------------------------------------------------------------------- #
# public: texture lookup in the pak index
# --------------------------------------------------------------------------- #
_INDEX_CACHE: Dict[str, object] = {}
_KIND_KEYWORDS = {
    "basecolor": ("basecolor", "albedo", "diffuse", "_c"),
    "normal": ("normal", "nrm", "nr", "nce", "_n"),
    "orm": ("mra", "orm", "arm", "rma", "mac", "ao", "occlusion", "_mra"),
    "emissive": ("emissive", "emission", "glow"),
    "mask": ("mask",),
    "ui": ("ui",),
}


def _index() -> Dict[str, object]:
    if "idx" in _INDEX_CACHE:
        return _INDEX_CACHE["idx"]                     # type: ignore[return-value]
    idx: Dict[str, object] = {}
    for mod_name in ("core.loader", "loader"):
        try:
            mod = __import__(mod_name, fromlist=["index"])
            idx = mod.index() or {}
            break
        except Exception:  # noqa: BLE001
            continue
    _INDEX_CACHE["idx"] = idx
    return idx


def _dir_map() -> Dict[str, List[str]]:
    """``dir -> [basenames]`` for every ``.uasset`` in the index (cached)."""
    cached = _INDEX_CACHE.get("dirs")
    if isinstance(cached, dict):
        return cached
    dirs: Dict[str, List[str]] = {}
    for key in _index():
        if not key.lower().endswith(".uasset"):
            continue
        head, _, base = key.rpartition("/")
        dirs.setdefault(head, []).append(base)
    _INDEX_CACHE["dirs"] = dirs
    return dirs


def _gen_tex_twin(dir_vpath: str) -> str:
    """``.../Content/Models/x`` -> ``.../Content/GenTexDirHD/Game/Models/x``."""
    d = dir_vpath.replace("\\", "/").rstrip("/")
    if "/Content/Models/" in d:
        return d.replace("/Content/Models/", "/Content/GenTexDirHD/Game/Models/")
    if "/Content/" in d:
        head, _, tail = d.partition("/Content/")
        if tail.startswith("Models/"):
            return f"{head}/Content/GenTexDirHD/Game/Models/{tail[len('Models/'):]}"
    return ""


def _dir_candidates(model_dir: str) -> List[str]:
    """Directories a model's textures may live in, nearest first."""
    d = (model_dir or "").replace("\\", "/").rstrip("/")
    if d.lower().endswith((".uasset", ".uexp", ".ubulk", ".uptnl")):
        d = os.path.dirname(d)
    if not d:
        return []
    out: List[str] = []

    def add(path: str) -> None:
        path = path.rstrip("/")
        if path and path not in out:
            out.append(path)

    def add_level(level: str) -> None:
        add(level)
        add(level + "/Textures")
        for sub in ("3p", "3P", "1p", "1P", "Material", "Materials"):
            add(level + "/Textures/" + sub)
        twin = _gen_tex_twin(level)
        if twin:
            add(twin)
            add(twin + "/Textures")
            for sub in ("3p", "3P", "1p", "1P"):
                add(twin + "/Textures/" + sub)

    level = d
    for _ in range(6):
        add_level(level)
        parent = os.path.dirname(level)
        if not parent or parent == level:
            break
        level = parent
    if d.endswith("/Materials") or d.endswith("/Material"):
        base = d.rsplit("/", 1)[0]
        add_level(base)
    return out


def _kind_of_hint(hint: str) -> Optional[str]:
    c = compact(hint)
    for kind, words in _KIND_KEYWORDS.items():
        for word in words:
            if word in c:
                return kind
    return None


def _name_matches_hint(basename: str, hint: str, kind: Optional[str]) -> bool:
    """Does ``basename`` satisfy the requested hint (token based)?"""
    if not hint and not kind:
        return True
    stem = _strip_ext(os.path.basename(basename)).lower()
    toks = tokens(basename)
    if kind:
        for word in _KIND_KEYWORDS.get(kind, ()):
            if word.startswith("_"):
                tail = word[1:]
                if toks and toks[-1] == tail:
                    return True
                if len(tail) >= 3 and compact(stem).endswith(tail):
                    return True
            elif word in toks or (len(word) >= 4 and word in "".join(toks)):
                return True
        return False
    want = compact(hint)
    if want in "".join(toks):
        return True
    return _match_slot(basename) == _match_slot(hint) and _match_slot(hint) is not None


def _asset_penalty(basename: str) -> int:
    """Prefer real texture assets (``T_*``) over generic helper assets."""
    low = _strip_ext(os.path.basename(basename)).lower()
    penalty = 0
    if not low.startswith("t_"):
        penalty += 6 if not low.startswith("t") else 3
    if "vmgen" not in low:
        penalty += 1
    penalty += max(0, len(basename) - 40) // 8
    return penalty


_NON_TEXTURE_PREFIXES = ("mi_", "m_", "bp_", "sm_", "sk_", "ab_", "ph_", "pa_",
                         "ns_", "an_", "am_", "w_", "wp_", "physicalmaterial")
_NON_TEXTURE_WORDS = ("skeleton", "physicsasset", "animsequence", "montage",
                      "material", "materialinstance", "staticmesh", "skeletalmesh")


def _looks_like_texture(basename: str) -> bool:
    """Filter out meshes/materials/animations living next to the textures."""
    stem = _strip_ext(os.path.basename(basename)).lower()
    if any(stem.startswith(p) for p in _NON_TEXTURE_PREFIXES):
        return False
    if any(w in stem for w in _NON_TEXTURE_WORDS):
        return False
    return True


def resolve_texture_path(model_dir: str, wanted_name_hint: str = "",
                         limit: str = "") -> Optional[str]:
    """Find a texture ``.uasset`` next to a model (or in its ``GenTexDirHD`` twin).

    ``wanted_name_hint`` may be a slot word (``BaseColor``/``Normal``/``ORM``/
    ``Emissive``/``Mask``), a parameter name (``BaseColorMap``) or a fragment of
    the asset name.  Hash suffixes are ignored.  ``limit`` is an optional extra
    path fragment the candidate must contain (e.g. ``"VirtualTextures"``).
    """
    dm = _dir_map()
    if not dm:
        return None
    hint = (wanted_name_hint or "").strip()
    if hint.lower().endswith(".uasset"):
        hint = hint[: -len(".uasset")]
    kind = _kind_of_hint(hint) if hint else None

    scored: List[Tuple[int, int, int, str]] = []
    want = compact(hint)
    for rank, directory in enumerate(_dir_candidates(model_dir)):
        names = dm.get(directory)
        if not names:
            continue
        for base in names:
            if limit and limit.lower() not in base.lower():
                continue
            if not _looks_like_texture(base):
                continue
            if not _name_matches_hint(base, hint, kind):
                continue
            exact = 0 if want and want in compact(_strip_ext(base)) else 1
            scored.append((_asset_penalty(base), rank, exact, directory + "/" + base))
    if scored:
        scored.sort()
        return scored[0][3]
    # last resort: unique basename suffix match anywhere in the pak index, but
    # only trust it for real texture assets (never a stray generic "BaseColor")
    if hint:
        needle = "/" + hint.lower()
        hits = [k for k in _index() if k.lower().endswith(needle + ".uasset")]
        if len(hits) == 1 and ("vmgen" in hits[0].lower() or hint.lower().startswith("t_")):
            return hits[0]
    return None


__all__ = [
    "load_material",
    "load_material_from_path",
    "load_material_json",
    "resolve_texture_path",
    "fill_slots",
    "inherits_defaults",
    "slot_for_param",
    "slot_for_asset",
    "object_path",
    "object_class",
    "compact",
    "_peek_parent",
]

"""Name-based VRM humanoid bone mapping for common third-party rigs (#1393).

Pure Python on purpose: the VRM worker (``bodyrig.blender_vrm_worker``) imports
this from a staged copy inside Blender, and the host-side tests import it
directly. No ``bpy`` here.

Covers the naming families seen in community 3D packs: XNALara/XPS
("arm left shoulder 2"), Source/SFM ValveBiped ("ValveBiped.Bip01_L_UpperArm"),
Daz Genesis ("lShldrBend"), Mixamo ("mixamorig:LeftArm") and generic
"UpperArm_L"/"upper_arm.L" styles. Anything else falls back to the VRM add-on's
structure search in the worker, which is slower (about a second).

Mapping a name is a claim about anatomy, never about identity: this module
says nothing about who a model depicts (#817).
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping

#: VRM 1.0 required humanoid bones (VRMC_vrm humanoid spec).
REQUIRED: tuple[str, ...] = (
    "hips", "spine", "head",
    "left_upper_leg", "left_lower_leg", "left_foot",
    "right_upper_leg", "right_lower_leg", "right_foot",
    "left_upper_arm", "left_lower_arm", "left_hand",
    "right_upper_arm", "right_lower_arm", "right_hand",
)

SIDED = ("shoulder", "upper_arm", "lower_arm", "hand", "upper_leg", "lower_leg", "foot", "toes")

# Matched against the normalized name (see ``normalize``): lower case, words
# separated by single spaces, side words removed.
ROLE_PATTERNS: Mapping[str, tuple[str, ...]] = {
    "hips": (r"^root hips$", r"^pelvis$", r"^bip01 pelvis$", r"^hips?$"),
    "spine": (r"^spine lower$", r"^bip01 spine$", r"^spine$", r"^abdomen ?lower$", r"^spine 1$"),
    "chest": (r"^spine (middle|upper)$", r"^bip01 spine ?[12]$", r"^chest ?(lower|upper)?$", r"^spine ?2$"),
    "neck": (r"^head neck lower$", r"^bip01 neck ?1?$", r"^neck ?(lower)?$"),
    "head": (r"^head$", r"^bip01 head ?1?$"),
    "shoulder": (r"^arm shoulder 1$", r"^bip01 clavicle$", r"^clavicle$", r"^collar$", r"^shoulder$"),
    "upper_arm": (r"^arm shoulder 2$", r"^bip01 upper ?arm$", r"^upper ?arm$", r"^shldr ?bend$", r"^arm$"),
    "lower_arm": (r"^arm elbow$", r"^bip01 fore ?arm$", r"^fore ?arm( bend)?$", r"^lower ?arm$"),
    "hand": (r"^arm wrist$", r"^bip01 hand$", r"^hand$"),
    "upper_leg": (r"^leg thigh$", r"^bip01 thigh$", r"^thigh( bend)?$", r"^upper ?leg$", r"^up ?leg$"),
    "lower_leg": (r"^leg knee$", r"^bip01 calf$", r"^shin$", r"^calf$", r"^knee$", r"^lower ?leg$", r"^leg$"),
    "foot": (r"^leg ankle$", r"^bip01 foot$", r"^foot$", r"^ankle$"),
    "toes": (r"^leg toes$", r"^bip01 toe ?0?$", r"^toes?( base)?$"),
}
_COMPILED = {role: tuple(re.compile(p) for p in pats) for role, pats in ROLE_PATTERNS.items()}
_SIDE_WORDS = {"left": "left", "l": "left", "right": "right", "r": "right"}


def normalize(name: str) -> tuple[str, str | None]:
    """Return (normalized role text, side) for one bone name."""
    text = name.split(":")[-1].split("|")[-1]
    text = re.sub(r"^valvebiped\.", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^mixamorig", "", text, flags=re.IGNORECASE)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = re.sub(r"\b(?!bip\d)([a-z]+)(\d+)\b", r"\1 \2", text)  # spine1 -> spine 1, not bip01
    side = None
    words = []
    for word in text.split():
        if word in _SIDE_WORDS and side is None:
            side = _SIDE_WORDS[word]
            continue
        words.append(word)
    return " ".join(words), side


def role_of(name: str) -> str | None:
    """VRM humanoid key for a bone name ("left_upper_arm", "hips", ...) or None."""
    text, side = normalize(name)
    for role, patterns in _COMPILED.items():
        if any(p.match(text) for p in patterns):
            if role in SIDED:
                return f"{side}_{role}" if side else None
            return None if side else role
    return None


def map_bones(names: Iterable[str]) -> dict[str, str]:
    """humanoid key -> bone name; the first bone (hierarchy order) wins a key."""
    mapping: dict[str, str] = {}
    for name in names:
        key = role_of(name)
        if key and key not in mapping:
            mapping[key] = name
    return mapping


def missing_required(mapping: Mapping[str, str]) -> list[str]:
    return [key for key in REQUIRED if not mapping.get(key)]

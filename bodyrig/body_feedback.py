from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ProposedBodyChange:
    field: str
    delta: float
    reason: str

    def to_json(self) -> dict[str, object]:
        return {"field": self.field, "delta": self.delta, "reason": self.reason}


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def propose_bodyprint_changes(feedback: str) -> list[ProposedBodyChange]:
    """Translate a small, explicit set of human comments into safe proposals.

    This function never mutates a BodyPrint or avatar. It only proposes bounded,
    reviewable deltas for fields already present in the BodyPrint v1 contract.
    Unknown language is intentionally ignored instead of guessed.
    """

    text = " ".join(str(feedback or "").strip().lower().split())
    if not text:
        return []

    changes: list[ProposedBodyChange] = []

    def add(field: str, delta: float, reason: str) -> None:
        if any(item.field == field for item in changes):
            return
        changes.append(ProposedBodyChange(field=field, delta=delta, reason=reason))

    # Arms. "for lange" means the correction is shorter; "længere" means longer.
    if _has(text, r"arm", r"arme"):
        if _has(text, r"for lang", r"for lange", r"kortere", r"kort arm", r"shorter"):
            add("shape.arm_to_height", -0.015, "arm length should be reduced")
        elif _has(text, r"længere", r"længere arme", r"longer"):
            add("shape.arm_to_height", 0.015, "arm length should be increased")

    # Shoulders.
    if _has(text, r"skulder", r"shoulder"):
        if _has(text, r"bredere", r"wider", r"broader"):
            add("shape.shoulder_to_height", 0.010, "shoulders should be broader")
        elif _has(text, r"for bred", r"smallere", r"narrower"):
            add("shape.shoulder_to_height", -0.010, "shoulders should be narrower")

    # Hips.
    if _has(text, r"hofte", r"hip"):
        if _has(text, r"bredere", r"wider"):
            add("shape.hip_to_height", 0.010, "hips should be broader")
        elif _has(text, r"for bred", r"smallere", r"narrower"):
            add("shape.hip_to_height", -0.010, "hips should be narrower")

    # Legs.
    if _has(text, r"ben", r"leg"):
        if _has(text, r"for lang", r"for lange", r"kortere", r"shorter"):
            add("shape.leg_to_height", -0.015, "leg length should be reduced")
        elif _has(text, r"længere", r"longer"):
            add("shape.leg_to_height", 0.015, "leg length should be increased")

    # Overall height.
    if _has(text, r"højde", r"højere", r"lavere", r"height", r"taller", r"shorter overall"):
        if _has(text, r"for høj", r"lavere", r"shorter overall"):
            add("shape.height_scale", -0.030, "overall height should be reduced")
        elif _has(text, r"højere", r"taller"):
            add("shape.height_scale", 0.030, "overall height should be increased")

    # Movement style. These are runtime/bodyprint controls, not geometry edits.
    if _has(text, r"gestik", r"gesture"):
        if _has(text, r"mere", r"større", r"more"):
            add("motion.gesture_amplitude", 0.080, "gesture amplitude should increase")
        elif _has(text, r"mindre", r"less"):
            add("motion.gesture_amplitude", -0.080, "gesture amplitude should decrease")

    if _has(text, r"energi", r"energy"):
        if _has(text, r"mere", r"højere", r"more"):
            add("motion.energy", 0.080, "movement energy should increase")
        elif _has(text, r"mindre", r"lavere", r"less"):
            add("motion.energy", -0.080, "movement energy should decrease")

    return changes

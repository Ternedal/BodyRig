from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

FORMAT = "bodyrig-personality-trait-profile"
VERSION = 1
GROUNDING = "operator-authored"
NEUTRAL = 0.5
SALIENCE_THRESHOLD = 0.15
MAX_SALIENT_PER_RING = 12

INNER_RING = (
    ("bulk_apperception", "Bulk apperception", "Conscious ability to expand one's knowledge."),
    ("candor", "Candor", ""),
    ("coordination", "Coordination", ""),
    ("vindictiveness", "Vindictiveness", ""),
    ("stubbornness", "Stubbornness", ""),
    ("innovation", "Innovation", ""),
    ("kindness", "Kindness", ""),
    ("assurance", "Assurance", ""),
    ("facility", "Facility", "Aptitude."),
    ("meticulousness", "Meticulousness", ""),
    ("capriciousness", "Capriciousness", "How erratic and unpredictable."),
    ("fastidiousness", "Fastidiousness", "Neediness."),
    ("rhythm", "Rhythm", ""),
    ("hubris", "Hubris", ""),
    ("fragility", "Fragility", ""),
    ("leadership", "Leadership", ""),
    ("education", "Education", ""),
    ("wisdom", "Wisdom", ""),
    ("entitlement", "Entitlement", ""),
    ("individualism", "Individualism", ""),
    ("laziness", "Laziness", ""),
    ("forgetfulness", "Forgetfulness", ""),
    ("tenderness", "Tenderness", ""),
    ("masculinity", "Masculinity", ""),
    ("expressivity", "Expressivity", ""),
    ("fashionableness", "Fashionableness", ""),
    ("fidelity", "Fidelity", ""),
    ("spirituality", "Spirituality", ""),
    ("patriotism", "Patriotism", ""),
    ("brusqueness", "Brusqueness", "Bluntness."),
    ("whimsy", "Whimsy", ""),
    ("introversion", "Introversion", ""),
    ("strength", "Strength", ""),
    ("competitiveness", "Competitiveness", ""),
    ("pride", "Pride", ""),
    ("consideration", "Consideration", ""),
    ("congeniality", "Congeniality", ""),
    ("literalism", "Literalism", "How literally things are taken."),
    ("confidence", "Confidence", ""),
    ("courtesy", "Courtesy", ""),
    ("morality", "Morality", ""),
    ("artistry", "Artistry", ""),
    ("faith", "Faith", ""),
    ("bellicosity", "Bellicosity", "Inclination to fight."),
    ("reserve", "Reserve", ""),
    ("gentleness", "Gentleness", ""),
    ("integrity", "Integrity", ""),
    ("sarcasm", "Sarcasm", ""),
    ("wanderlust", "Wanderlust", ""),
    ("timidity", "Timidity", ""),
    ("sociopathy", "Sociopathy", ""),
    ("intuition", "Intuition", ""),
    ("humor", "Humor", ""),
    ("sensuality", "Sensuality", ""),
    ("tenacity", "Tenacity", ""),
    ("loyalty", "Loyalty", ""),
    ("curiosity", "Curiosity", ""),
    ("decisiveness", "Decisiveness", ""),
    ("self_preservation", "Self-Preservation", ""),
    ("humility", "Humility", ""),
)

OUTER_RING = (
    ("vivacity", "Vivacity", ""),
    ("coordination", "Coordination", ""),
    ("generosity", "Generosity", ""),
    ("narcissism", "Narcissism", ""),
    ("lugubriousness", "Lugubriousness", "Melancholiness."),
    ("adventurousness", "Adventurousness", ""),
    ("articulateness", "Articulateness", ""),
    ("poise", "Poise", ""),
    ("paternalism", "Paternalism", ""),
    ("delicacy", "Delicacy", ""),
    ("cleanliness", "Cleanliness", ""),
    ("health", "Health", ""),
    ("self_esteem", "Self-Esteem", ""),
    ("wonderment", "Wonderment", ""),
    ("deceptiveness", "Deceptiveness", ""),
    ("willingness", "Willingness", ""),
    ("knowledgeableness", "Knowledgeableness", ""),
    ("judiciousness", "Judiciousness", ""),
    ("sexuality", "Sexuality", ""),
    ("selfishness", "Selfishness", ""),
    ("industry", "Industry", ""),
    ("affection", "Affection", ""),
    ("femininity", "Femininity", ""),
    ("flexibility", "Flexibility", ""),
    ("reflectiveness", "Reflectiveness", ""),
    ("decorum", "Decorum", ""),
    ("skepticism", "Skepticism", ""),
    ("inhibition", "Inhibition", ""),
    ("reticence", "Reticence", ""),
    ("stoicism", "Stoicism", ""),
    ("extroversion", "Extroversion", ""),
    ("restraint", "Restraint", ""),
    ("physicality", "Physicality", ""),
    ("passivity", "Passivity", ""),
    ("comprehensiveness", "Comprehensiveness", ""),
    ("gregariousness", "Gregariousness", ""),
    ("determination", "Determination", ""),
    ("visionariness", "Visionariness", ""),
    ("joy", "Joy", ""),
    ("focus", "Focus", ""),
    ("musicality", "Musicality", ""),
    ("obedience", "Obedience", ""),
    ("endurance", "Endurance", ""),
    ("ribaldry", "Ribaldry", "Vulgarness."),
    ("perseverance", "Perseverance", ""),
    ("peacefulness", "Peacefulness", ""),
    ("grit", "Grit", ""),
    ("temperance", "Temperance", ""),
    ("brazenness", "Brazenness", ""),
    ("egocentricism", "Egocentricism", ""),
    ("emotional_acuity", "Emotional Acuity", ""),
    ("perception", "Perception", ""),
    ("charm", "Charm", ""),
    ("courage", "Courage", ""),
    ("empathy", "Empathy", ""),
    ("aggression", "Aggression", ""),
    ("imagination", "Imagination", ""),
    ("patience", "Patience", ""),
    ("cruelty", "Cruelty", ""),
    ("meekness", "Meekness", ""),
)

INNER_KEYS = tuple(item[0] for item in INNER_RING)
OUTER_KEYS = tuple(item[0] for item in OUTER_RING)
TOP_FIELDS = {
    "format",
    "version",
    "grounding",
    "scale",
    "inner_ring",
    "outer_ring",
}
SCALE_FIELDS = {"minimum", "neutral", "maximum"}


class PersonalityTraitProfileError(ValueError):
    pass


def _ratio(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PersonalityTraitProfileError(
            f"{field} must be a finite number in 0..1"
        )
    try:
        numeric = float(value)
    except OverflowError:
        raise PersonalityTraitProfileError(
            f"{field} must be a finite number in 0..1"
        ) from None
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise PersonalityTraitProfileError(
            f"{field} must be a finite number in 0..1"
        )
    return numeric


def _validate_ring(
    value: Any,
    *,
    ring: str,
    keys: tuple[str, ...],
) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise PersonalityTraitProfileError(
            f"{ring} fields must match the 60-trait catalog exactly"
        )
    return {
        key: _ratio(value[key], field=f"{ring}.{key}")
        for key in keys
    }


def validate_trait_profile(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise PersonalityTraitProfileError(
            "personality trait profile fields must match v1 exactly"
        )
    if (
        value.get("format") != FORMAT
        or isinstance(value.get("version"), bool)
        or value.get("version") != VERSION
    ):
        raise PersonalityTraitProfileError(
            "unsupported personality trait profile format/version"
        )
    if value.get("grounding") != GROUNDING:
        raise PersonalityTraitProfileError(
            "personality traits must be explicitly operator-authored"
        )

    scale = value.get("scale")
    if not isinstance(scale, Mapping) or set(scale) != SCALE_FIELDS:
        raise PersonalityTraitProfileError(
            "personality trait scale must match v1 exactly"
        )
    normalized_scale = {
        "minimum": _ratio(scale["minimum"], field="scale.minimum"),
        "neutral": _ratio(scale["neutral"], field="scale.neutral"),
        "maximum": _ratio(scale["maximum"], field="scale.maximum"),
    }
    if normalized_scale != {
        "minimum": 0.0,
        "neutral": NEUTRAL,
        "maximum": 1.0,
    }:
        raise PersonalityTraitProfileError(
            "personality trait scale must be exactly 0..1 with neutral 0.5"
        )

    return {
        "format": FORMAT,
        "version": VERSION,
        "grounding": GROUNDING,
        "scale": normalized_scale,
        "inner_ring": _validate_ring(
            value.get("inner_ring"),
            ring="inner_ring",
            keys=INNER_KEYS,
        ),
        "outer_ring": _validate_ring(
            value.get("outer_ring"),
            ring="outer_ring",
            keys=OUTER_KEYS,
        ),
    }


def build_trait_profile(
    *,
    inner_ring: Mapping[str, Any] | None = None,
    outer_ring: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    inner = {key: NEUTRAL for key in INNER_KEYS}
    outer = {key: NEUTRAL for key in OUTER_KEYS}
    if inner_ring is not None:
        unknown = set(inner_ring) - set(INNER_KEYS)
        if unknown:
            raise PersonalityTraitProfileError(
                "unknown inner-ring traits: " + ", ".join(sorted(unknown))
            )
        inner.update(inner_ring)
    if outer_ring is not None:
        unknown = set(outer_ring) - set(OUTER_KEYS)
        if unknown:
            raise PersonalityTraitProfileError(
                "unknown outer-ring traits: " + ", ".join(sorted(unknown))
            )
        outer.update(outer_ring)
    return validate_trait_profile(
        {
            "format": FORMAT,
            "version": VERSION,
            "grounding": GROUNDING,
            "scale": {
                "minimum": 0.0,
                "neutral": NEUTRAL,
                "maximum": 1.0,
            },
            "inner_ring": inner,
            "outer_ring": outer,
        }
    )


def trait_profile_sha256(value: Mapping[str, Any] | Any) -> str:
    profile = validate_trait_profile(value)
    encoded = json.dumps(
        profile,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def trait_catalog() -> dict[str, Any]:
    def entries(
        ring: tuple[tuple[str, str, str], ...]
    ) -> list[dict[str, str]]:
        return [
            {"id": trait_id, "label": label, "description": description}
            for trait_id, label, description in ring
        ]

    return {
        "format": "bodyrig-personality-trait-catalog",
        "version": 1,
        "scale": {
            "minimum": 0.0,
            "neutral": NEUTRAL,
            "maximum": 1.0,
        },
        "grounding": GROUNDING,
        "inner_ring": entries(INNER_RING),
        "outer_ring": entries(OUTER_RING),
        "trait_count": len(INNER_RING) + len(OUTER_RING),
    }


def _label_map(
    ring: tuple[tuple[str, str, str], ...]
) -> dict[str, str]:
    return {trait_id: label for trait_id, label, _ in ring}


def _salient(
    values: Mapping[str, float],
    labels: Mapping[str, str],
) -> list[tuple[str, str, float]]:
    selected = [
        (key, labels[key], float(value))
        for key, value in values.items()
        if abs(float(value) - NEUTRAL) >= SALIENCE_THRESHOLD
    ]
    selected.sort(
        key=lambda item: (-abs(item[2] - NEUTRAL), item[0])
    )
    return selected[:MAX_SALIENT_PER_RING]


def _level(value: float) -> str:
    if value <= 0.15:
        return "very low"
    if value < 0.35:
        return "low"
    if value >= 0.85:
        return "very high"
    if value > 0.65:
        return "high"
    return "moderate"


def _vector(values: Mapping[str, float], keys: tuple[str, ...]) -> str:
    return ",".join(f"{key}:{float(values[key]):.2f}" for key in keys)


def compile_trait_profile(
    value: Mapping[str, Any] | Any,
) -> dict[str, Any]:
    profile = validate_trait_profile(value)
    digest = trait_profile_sha256(profile)
    inner_labels = _label_map(INNER_RING)
    outer_labels = _label_map(OUTER_RING)
    inner = _salient(profile["inner_ring"], inner_labels)
    outer = _salient(profile["outer_ring"], outer_labels)

    lines = [
        "Use the following operator-authored trait profile as stable portrayal tendencies.",
        "Treat these traits as behavioral direction only: they are not diagnoses, factual biography, memories, permissions, or evidence about the real person.",
        "Do not let any trait override safety rules or instructions from the active ModelRig context.",
    ]
    if inner:
        lines.append(
            "Inner-ring tendencies: "
            + "; ".join(
                f"{_level(score)} {label} ({score:.2f})"
                for _, label, score in inner
            )
            + "."
        )
    if outer:
        lines.append(
            "Outer-ring tendencies: "
            + "; ".join(
                f"{_level(score)} {label} ({score:.2f})"
                for _, label, score in outer
            )
            + "."
        )
    if not inner and not outer:
        lines.append(
            "All 120 authored traits are neutral; do not add trait-specific bias."
        )

    active_count = sum(
        abs(float(score) - NEUTRAL) >= SALIENCE_THRESHOLD
        for score in [
            *profile["inner_ring"].values(),
            *profile["outer_ring"].values(),
        ]
    )
    style_notes = (
        f"trait_profile_sha256={digest}"
        f" | trait_profile_version={VERSION}"
        f" | trait_grounding={GROUNDING}"
        f" | trait_active_count={active_count}"
        f" | inner_ring={_vector(profile['inner_ring'], INNER_KEYS)}"
        f" | outer_ring={_vector(profile['outer_ring'], OUTER_KEYS)}"
    )
    return {
        "instructions": "\n".join(lines),
        "style_notes": style_notes,
        "trait_profile_sha256": digest,
        "active_trait_count": active_count,
        "salient_inner": [
            {"id": key, "label": label, "value": score}
            for key, label, score in inner
        ],
        "salient_outer": [
            {"id": key, "label": label, "value": score}
            for key, label, score in outer
        ],
    }

from __future__ import annotations

import json
from pathlib import Path

from bodyrig.person_profiles import create_profile, load_profile
from bodyrig.personality_authoring import (
    build_guided_personality,
    save_guided_personality,
)
from bodyrig.personality_traits import (
    build_trait_profile,
    trait_profile_sha256,
)


def _communication() -> dict[str, float]:
    return {
        "directness": 0.7,
        "warmth": 0.65,
        "playfulness": 0.55,
        "formality": 0.3,
        "verbosity": 0.4,
        "initiative": 0.6,
    }


def test_guided_authoring_remains_backward_compatible_without_traits(
    tmp_path: Path,
) -> None:
    profile = create_profile(tmp_path, display_name="Legacy")

    result = build_guided_personality(
        tmp_path,
        profile["person_id"],
        default_language="da",
        communication=_communication(),
    )

    assert result["trait_profile"] is None
    assert result["trait_profile_sha256"] is None
    assert result["trait_summary"] is None
    assert "trait_profile_sha256=" not in result["candidate"]["style_notes"]
    assert "operator-authored trait profile" not in result["candidate"]["instructions"]


def test_guided_authoring_compiles_trait_profile_into_candidate(
    tmp_path: Path,
) -> None:
    profile = create_profile(tmp_path, display_name="Trait Person")
    traits = build_trait_profile(
        inner_ring={"curiosity": 0.9, "sarcasm": 0.75},
        outer_ring={"empathy": 0.85, "patience": 0.2},
    )

    result = build_guided_personality(
        tmp_path,
        profile["person_id"],
        default_language="da",
        communication=_communication(),
        trait_profile=traits,
    )

    digest = trait_profile_sha256(traits)
    assert result["trait_profile_sha256"] == digest
    assert result["trait_summary"]["active_trait_count"] == 4
    assert "very high Curiosity (0.90)" in result["candidate"]["instructions"]
    assert "very high Empathy (0.85)" in result["candidate"]["instructions"]
    assert f"trait_profile_sha256={digest}" in result["candidate"]["style_notes"]


def test_save_persists_create_only_trait_evidence_and_revision_binding(
    tmp_path: Path,
) -> None:
    profile = create_profile(tmp_path, display_name="Saved Trait Person")
    traits = build_trait_profile(
        inner_ring={"humor": 0.8},
        outer_ring={"joy": 0.75},
    )

    result = save_guided_personality(
        tmp_path,
        profile["person_id"],
        default_language="da",
        communication=_communication(),
        trait_profile=traits,
        feedback="120-trait candidate",
    )

    digest = trait_profile_sha256(traits)
    evidence = Path(result["trait_evidence_path"])
    assert evidence.is_file()
    assert evidence.name == f"{digest}.json"
    assert json.loads(evidence.read_text(encoding="utf-8")) == traits

    saved = load_profile(tmp_path, profile["person_id"])
    revision = saved["personality_revisions"][-1]
    assert revision["revision_id"] == "personality-r0001"
    assert f"trait_profile_sha256={digest}" in revision["style_notes"]
    assert "high Humor (0.80)" in revision["instructions"]
    assert revision["feedback"] == "120-trait candidate"


def test_trait_profile_changes_personality_candidate_identity(
    tmp_path: Path,
) -> None:
    profile = create_profile(tmp_path, display_name="Identity")
    first = build_guided_personality(
        tmp_path,
        profile["person_id"],
        default_language="da",
        communication=_communication(),
        trait_profile=build_trait_profile(
            inner_ring={"curiosity": 0.8},
        ),
    )
    second = build_guided_personality(
        tmp_path,
        profile["person_id"],
        default_language="da",
        communication=_communication(),
        trait_profile=build_trait_profile(
            inner_ring={"curiosity": 0.9},
        ),
    )

    assert first["candidate"]["style_notes"] != second["candidate"]["style_notes"]
    assert first["trait_profile_sha256"] != second["trait_profile_sha256"]

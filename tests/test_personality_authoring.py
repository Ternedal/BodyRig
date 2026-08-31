from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.person_profiles import create_profile, load_profile
from bodyrig.personality_authoring import (
    PersonalityAuthoringError,
    build_guided_personality,
    persist_blueprint_evidence,
    save_guided_personality,
)


def communication(**overrides: float) -> dict[str, float]:
    value = {
        "directness": 0.5,
        "warmth": 0.5,
        "playfulness": 0.5,
        "formality": 0.5,
        "verbosity": 0.5,
        "initiative": 0.5,
    }
    value.update(overrides)
    return value


def test_guided_preview_does_not_mutate_profile(tmp_path: Path) -> None:
    root = tmp_path / "people"
    profile = create_profile(root, display_name="Test Person")

    result = build_guided_personality(
        root,
        profile["person_id"],
        default_language="da",
        communication=communication(directness=0.8, warmth=0.7),
        authored_notes="Tør og underspillet.",
        style_exemplars=["Ja ja, det går nok."],
    )

    assert len(result["blueprint_sha256"]) == 64
    assert result["blueprint"]["grounding"]["communication"] == "operator-authored"
    assert result["candidate"]["default_language"] == "da"
    assert "blueprint_sha256=" in result["candidate"]["style_notes"]
    assert len(result["audition_suite"]["probes"]) == 6
    assert load_profile(root, profile["person_id"])["personality_revisions"] == []
    assert not (root / "personality-blueprints").exists()


def test_save_persists_immutable_blueprint_before_personality_revision(tmp_path: Path) -> None:
    root = tmp_path / "people"
    profile = create_profile(root, display_name="Test Person")

    result = save_guided_personality(
        root,
        profile["person_id"],
        default_language="en",
        communication=communication(initiative=0.9),
        style_exemplars=["We will figure it out."],
        feedback="Guided v1",
    )

    assert result["saved_personality_revision"] == "personality-r0001"
    evidence = Path(result["evidence_path"])
    assert evidence.is_file()
    assert evidence.name == f"{result['blueprint_sha256']}.json"
    assert evidence.parent.name == profile["person_id"]
    assert evidence.parent.parent.name == "personality-blueprints"
    assert json.loads(evidence.read_text(encoding="utf-8"))["style_exemplars"] == [
        "We will figure it out."
    ]

    saved = load_profile(root, profile["person_id"])
    revision = saved["personality_revisions"][0]
    assert revision["feedback"] == "Guided v1"
    assert f"blueprint_sha256={result['blueprint_sha256']}" in revision["style_notes"]


def test_same_blueprint_reuses_identical_evidence_without_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "people"
    profile = create_profile(root, display_name="Test Person")
    result = build_guided_personality(
        root,
        profile["person_id"],
        default_language="da",
        communication=communication(),
    )

    first = persist_blueprint_evidence(root, profile["person_id"], result["blueprint"])
    before = first.read_bytes()
    second = persist_blueprint_evidence(root, profile["person_id"], result["blueprint"])

    assert first == second
    assert second.read_bytes() == before


def test_unknown_body_revision_fails_without_profile_mutation(tmp_path: Path) -> None:
    root = tmp_path / "people"
    profile = create_profile(root, display_name="Test Person")

    with pytest.raises(PersonalityAuthoringError, match="not registered"):
        save_guided_personality(
            root,
            profile["person_id"],
            default_language="da",
            communication=communication(),
            body_revision="body-r0001",
        )

    assert load_profile(root, profile["person_id"])["personality_revisions"] == []
    assert not (root / "personality-blueprints").exists()


def test_invalid_guided_values_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "people"
    profile = create_profile(root, display_name="Test Person")

    with pytest.raises(PersonalityAuthoringError, match="communication.warmth"):
        build_guided_personality(
            root,
            profile["person_id"],
            default_language="da",
            communication={**communication(), "warmth": 2.0},
        )

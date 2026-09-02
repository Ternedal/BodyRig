from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.embodiment_assembly import (
    EmbodimentAssemblyError,
    build_embodiment_bound_assembly,
    build_embodiment_bound_assembly_from_library,
)
from bodyrig.personality_blueprint import blueprint_sha256, build_blueprint, compile_blueprint
from bodyrig.personality_embodiment_binding import build_binding, write_binding


def _communication(**overrides: float) -> dict[str, float]:
    value = {
        "directness": 0.5,
        "warmth": 0.6,
        "playfulness": 0.4,
        "formality": 0.3,
        "verbosity": 0.5,
        "initiative": 0.5,
    }
    value.update(overrides)
    return value


def _profile() -> tuple[dict, dict]:
    blueprint = build_blueprint(default_language="da", communication=_communication())
    compiled = compile_blueprint(blueprint)
    profile = {
        "person_id": "person-" + "d" * 32,
        "body_revisions": [
            {
                "revision_id": "body-r0001",
                "body_id": "body-one",
                "package_sha256": "a" * 64,
            }
        ],
        "voice_revisions": [
            {
                "revision_id": "voice-r0001",
                "voice_id": "voice-one",
                "voice_package": "voice-one.mrvoice",
                "package_sha256": "b" * 64,
            }
        ],
        "personality_revisions": [
            {
                "revision_id": "personality-r0001",
                "instructions": compiled["instructions"],
                "default_language": compiled["default_language"],
                "style_notes": compiled["style_notes"],
            },
            {
                "revision_id": "personality-r0002",
                "instructions": "different",
                "default_language": "da",
                "style_notes": "different",
            },
        ],
    }
    return profile, blueprint


def test_assembly_v2_fingerprint_binds_verified_embodiment_receipt() -> None:
    profile, blueprint = _profile()
    binding = build_binding(
        profile,
        personality_revision="personality-r0001",
        blueprint=blueprint,
    )

    assembly = build_embodiment_bound_assembly(
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
        embodiment_binding=binding,
        blueprint=blueprint,
    )

    assert assembly["format"] == "bodyrig-person-assembly"
    assert assembly["version"] == 2
    assert len(assembly["assembly_fingerprint"]) == 64
    assert len(assembly["embodiment_binding"]["binding_sha256"]) == 64
    assert assembly["embodiment_binding"]["blueprint_sha256"] == binding["blueprint_sha256"]
    assert assembly["embodiment_binding"]["evidence_status"] == "operator-authored"
    assert assembly["human_review_required"] is True
    assert assembly["production_authority"] is False


def test_assembly_v2_rejects_personality_revision_not_named_by_binding() -> None:
    profile, blueprint = _profile()
    binding = build_binding(
        profile,
        personality_revision="personality-r0001",
        blueprint=blueprint,
    )

    with pytest.raises(EmbodimentAssemblyError, match="selected personality revision conflicts"):
        build_embodiment_bound_assembly(
            profile,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0002",
            embodiment_binding=binding,
            blueprint=blueprint,
        )


def test_library_assembly_reloads_and_verifies_persisted_blueprint(tmp_path: Path) -> None:
    profile, blueprint = _profile()
    write_binding(
        tmp_path,
        profile,
        personality_revision="personality-r0001",
        blueprint=blueprint,
    )
    digest = blueprint_sha256(blueprint)
    evidence = (
        tmp_path
        / "personality-blueprints"
        / profile["person_id"]
        / f"{digest}.json"
    )
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps(blueprint), encoding="utf-8")

    assembly = build_embodiment_bound_assembly_from_library(
        tmp_path,
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
    )
    assert assembly["embodiment_binding"]["blueprint_sha256"] == digest

    tampered = build_blueprint(
        default_language="da",
        communication=_communication(directness=0.9),
    )
    evidence.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(EmbodimentAssemblyError, match="SHA-256 mismatch"):
        build_embodiment_bound_assembly_from_library(
            tmp_path,
            profile,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
        )

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.person_profiles import (
    PersonProfileError,
    active_bundle,
    add_body_revision,
    add_person_revision,
    add_personality_revision,
    add_voice_revision,
    create_profile,
    load_profile,
)


BODY_SHA = "a" * 64
VOICE_SHA = "b" * 64


def _approved_profile(root: Path) -> tuple[str, Path]:
    profile = create_profile(root, display_name="Persisted Authority")
    person_id = profile["person_id"]
    add_body_revision(
        root,
        person_id,
        body_id="bodyid-0123456789abcdef01234567",
        package_sha256=BODY_SHA,
        package_path=r"C:\\BodyRig\\persisted-authority.mrbody",
        preview_path=r"C:\\BodyRig\\persisted-authority.png",
        feedback="exact body candidate",
    )
    add_voice_revision(
        root,
        person_id,
        voice_id="persisted-authority-voice",
        voice_package="persisted-authority.mrvoice",
        package_sha256=VOICE_SHA,
        feedback="exact voice candidate",
    )
    add_personality_revision(
        root,
        person_id,
        instructions="Du er den godkendte persisted authority fixture.",
        default_language="da",
        style_notes="bounded fixture",
        feedback="exact personality candidate",
    )
    add_person_revision(
        root,
        person_id,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
        compatibility_review={
            "body_voice_match": True,
            "voice_personality_match": True,
            "body_personality_match": True,
            "overall_coherent": True,
            "note": "Exact approved bundle fixture.",
        },
        feedback="approved bundle",
        activate=True,
    )
    return person_id, root / f"{person_id}.json"


def test_persisted_person_profile_rejects_boolean_v1_before_active_bundle_is_trusted(tmp_path: Path) -> None:
    person_id, path = _approved_profile(tmp_path)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["active_person_revision"] == "person-r0001"
    persisted["version"] = True
    path.write_text(json.dumps(persisted), encoding="utf-8")

    with pytest.raises(PersonProfileError, match="format/version"):
        load_profile(tmp_path, person_id)


def test_persisted_person_profile_preserves_numeric_float_v1_and_exact_active_bundle(tmp_path: Path) -> None:
    person_id, path = _approved_profile(tmp_path)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    persisted["version"] = 1.0
    path.write_text(json.dumps(persisted), encoding="utf-8")

    loaded = load_profile(tmp_path, person_id)
    bundle = active_bundle(loaded)

    assert loaded["version"] == 1
    assert loaded["person_id"] == person_id
    assert loaded["active_person_revision"] == "person-r0001"
    assert loaded["body_revisions"][0]["package_sha256"] == BODY_SHA
    assert loaded["body_revisions"][0]["package_path"] == r"C:\\BodyRig\\persisted-authority.mrbody"
    assert loaded["voice_revisions"][0]["package_sha256"] == VOICE_SHA
    assert loaded["voice_revisions"][0]["voice_package"] == "persisted-authority.mrvoice"
    assert loaded["personality_revisions"][0]["default_language"] == "da"
    assert bundle is not None
    assert bundle["body_revision"] == "body-r0001"
    assert bundle["voice_revision"] == "voice-r0001"
    assert bundle["personality_revision"] == "personality-r0001"
    assert bundle["compatibility_review"]["overall_coherent"] is True

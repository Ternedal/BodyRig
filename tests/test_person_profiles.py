from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.person_profiles import (
    PersonProfileError,
    activate_revision,
    add_body_revision,
    add_personality_revision,
    add_voice_revision,
    create_profile,
    list_profiles,
    load_profile,
    validate_profile,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def test_multiple_people_are_independent(tmp_path: Path) -> None:
    anna = create_profile(
        tmp_path,
        display_name="Anna",
        stash_performer={"id": "12", "name": "Anna Example", "disambiguation": "A"},
    )
    peter = create_profile(tmp_path, display_name="Peter")

    assert anna["person_id"] != peter["person_id"]
    assert anna["person_id"].startswith("person-")
    assert peter["source"] is None

    anna2 = add_personality_revision(
        tmp_path,
        anna["person_id"],
        instructions="Du er Anna. Svar kort og tørt.",
        style_notes="rolig",
        feedback="første version",
        activate=True,
    )
    peter2 = load_profile(tmp_path, peter["person_id"])

    assert anna2["active"]["personality_revision"] == "personality-r0001"
    assert len(anna2["personality_revisions"]) == 1
    assert peter2["active"]["personality_revision"] is None
    assert peter2["personality_revisions"] == []


def test_body_voice_and_personality_revision_histories_are_independent(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Profile")
    person_id = profile["person_id"]

    profile = add_body_revision(
        tmp_path,
        person_id,
        body_id="bodyid-0123456789abcdef01234567",
        package_sha256=HASH_A,
        package_path=r"C:\BodyRig\profile-v1.mrbody",
        preview_path=r"C:\BodyRig\preview-v1.png",
        feedback="første clone",
        activate=True,
    )
    profile = add_voice_revision(
        tmp_path,
        person_id,
        voice_id="profile-voice-1234",
        package_sha256=HASH_B,
        package_path=r"C:\VoiceRig\profile.mrvoice",
        activate=True,
    )
    profile = add_personality_revision(
        tmp_path,
        person_id,
        instructions="Du er Profile.",
        activate=True,
    )
    profile = add_body_revision(
        tmp_path,
        person_id,
        body_id="bodyid-fedcba9876543210fedcba98",
        package_sha256=HASH_B,
        package_path=r"C:\BodyRig\profile-v2.mrbody",
        feedback="kortere arme",
    )

    assert [item["revision_id"] for item in profile["body_revisions"]] == ["body-r0001", "body-r0002"]
    assert [item["revision_id"] for item in profile["voice_revisions"]] == ["voice-r0001"]
    assert [item["revision_id"] for item in profile["personality_revisions"]] == ["personality-r0001"]
    assert profile["active"] == {
        "body_revision": "body-r0001",
        "voice_revision": "voice-r0001",
        "personality_revision": "personality-r0001",
    }

    activated = activate_revision(tmp_path, person_id, kind="body", revision_id="body-r0002")
    assert activated["active"]["body_revision"] == "body-r0002"
    assert activated["active"]["voice_revision"] == "voice-r0001"
    assert activated["active"]["personality_revision"] == "personality-r0001"


def test_person_id_does_not_change_when_component_revisions_change(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Stable Person")
    person_id = profile["person_id"]
    for index in range(3):
        profile = add_personality_revision(
            tmp_path,
            person_id,
            instructions=f"Persona revision {index + 1}",
            feedback=f"feedback {index + 1}",
            activate=True,
        )
    assert profile["person_id"] == person_id
    assert len(profile["personality_revisions"]) == 3
    assert profile["active"]["personality_revision"] == "personality-r0003"


def test_registry_lists_many_people_sorted_by_name(tmp_path: Path) -> None:
    create_profile(tmp_path, display_name="Zulu")
    create_profile(tmp_path, display_name="Anna")
    create_profile(tmp_path, display_name="Peter")
    assert [item["display_name"] for item in list_profiles(tmp_path)] == ["Anna", "Peter", "Zulu"]


def test_validator_rejects_secret_or_unknown_fields(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Secret Safe")
    tampered = dict(profile)
    tampered["stash_api_key"] = "must-not-be-here"
    with pytest.raises(PersonProfileError, match="fields must match"):
        validate_profile(tampered)


def test_active_binding_must_reference_existing_revision(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Broken")
    broken = json.loads(json.dumps(profile))
    broken["active"]["body_revision"] = "body-r0001"
    with pytest.raises(PersonProfileError, match="does not reference"):
        validate_profile(broken)


def test_invalid_personality_language_and_boolean_sha_are_rejected(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Strict")
    with pytest.raises(PersonProfileError, match="default_language"):
        add_personality_revision(tmp_path, profile["person_id"], instructions="x", default_language="not a lang")

    with pytest.raises(PersonProfileError, match="SHA-256"):
        add_body_revision(
            tmp_path,
            profile["person_id"],
            body_id="bodyid-0123456789abcdef01234567",
            package_sha256=True,  # type: ignore[arg-type]
            package_path=r"C:\x.mrbody",
        )

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.person_profiles import (
    PersonProfileError,
    activate_person_revision,
    active_bundle,
    add_body_revision,
    add_person_revision,
    add_personality_revision,
    add_voice_revision,
    create_profile,
    list_profiles,
    load_profile,
    validate_profile,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _components(root: Path, person_id: str) -> dict:
    profile = add_body_revision(
        root,
        person_id,
        body_id="bodyid-0123456789abcdef01234567",
        package_sha256=HASH_A,
        package_path=r"C:\BodyRig\profile-v1.mrbody",
        feedback="første clone",
    )
    profile = add_voice_revision(
        root,
        person_id,
        voice_id="profile-voice-1234",
        package_sha256=HASH_B,
        package_path=r"C:\VoiceRig\profile.mrvoice",
        feedback="første stemme",
    )
    return add_personality_revision(
        root,
        person_id,
        instructions="Du er Profile. Svar roligt og tørt.",
        feedback="første personality",
    )


def _review(note: str = "Krop, stemme og personlighed opleves som samme person.") -> dict:
    return {
        "body_voice_match": True,
        "voice_personality_match": True,
        "body_personality_match": True,
        "overall_coherent": True,
        "note": note,
    }


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

    add_personality_revision(tmp_path, anna["person_id"], instructions="Du er Anna.")
    assert len(load_profile(tmp_path, anna["person_id"])["personality_revisions"]) == 1
    assert load_profile(tmp_path, peter["person_id"])["personality_revisions"] == []


def test_components_are_candidates_until_approved_person_revision_exists(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Profile")
    profile = _components(tmp_path, profile["person_id"])
    assert profile["active_person_revision"] is None
    assert active_bundle(profile) is None
    assert [item["revision_id"] for item in profile["body_revisions"]] == ["body-r0001"]
    assert [item["revision_id"] for item in profile["voice_revisions"]] == ["voice-r0001"]
    assert [item["revision_id"] for item in profile["personality_revisions"]] == ["personality-r0001"]


def test_person_revision_binds_body_voice_and_personality_atomically(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Profile")
    person_id = profile["person_id"]
    _components(tmp_path, person_id)

    profile = add_person_revision(
        tmp_path,
        person_id,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
        compatibility_review=_review(),
        feedback="første samlede person",
        activate=True,
    )
    assert profile["active_person_revision"] == "person-r0001"
    bundle = active_bundle(profile)
    assert bundle is not None
    assert bundle["body_revision"] == "body-r0001"
    assert bundle["voice_revision"] == "voice-r0001"
    assert bundle["personality_revision"] == "personality-r0001"
    assert bundle["compatibility_review"]["overall_coherent"] is True


def test_new_component_revision_does_not_silently_change_active_person(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Profile")
    person_id = profile["person_id"]
    _components(tmp_path, person_id)
    profile = add_person_revision(
        tmp_path,
        person_id,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
        compatibility_review=_review(),
    )
    profile = add_body_revision(
        tmp_path,
        person_id,
        body_id="bodyid-fedcba9876543210fedcba98",
        package_sha256=HASH_C,
        package_path=r"C:\BodyRig\profile-v2.mrbody",
        feedback="kortere arme",
    )
    assert profile["active_person_revision"] == "person-r0001"
    assert active_bundle(profile)["body_revision"] == "body-r0001"  # type: ignore[index]


def test_new_approved_bundle_can_be_activated_and_old_bundle_restored(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Profile")
    person_id = profile["person_id"]
    _components(tmp_path, person_id)
    add_person_revision(
        tmp_path,
        person_id,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
        compatibility_review=_review(),
    )
    add_personality_revision(tmp_path, person_id, instructions="Du er Profile v2.", feedback="mere tør humor")
    profile = add_person_revision(
        tmp_path,
        person_id,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0002",
        compatibility_review=_review("Samme person; ny personality matcher eksisterende krop og stemme."),
    )
    assert profile["active_person_revision"] == "person-r0002"
    profile = activate_person_revision(tmp_path, person_id, "person-r0001")
    assert profile["active_person_revision"] == "person-r0001"
    assert active_bundle(profile)["personality_revision"] == "personality-r0001"  # type: ignore[index]


def test_compatibility_review_must_be_explicitly_green(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Mismatch")
    person_id = profile["person_id"]
    _components(tmp_path, person_id)
    review = _review()
    review["voice_personality_match"] = False
    with pytest.raises(PersonProfileError, match="voice_personality_match"):
        add_person_revision(
            tmp_path,
            person_id,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            compatibility_review=review,
        )


def test_person_revision_must_reference_existing_components(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Incomplete")
    with pytest.raises(PersonProfileError, match="existing body, voice and personality"):
        add_person_revision(
            tmp_path,
            profile["person_id"],
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            compatibility_review=_review(),
        )


def test_person_id_does_not_change_when_component_or_person_revisions_change(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Stable Person")
    person_id = profile["person_id"]
    _components(tmp_path, person_id)
    add_person_revision(
        tmp_path,
        person_id,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
        compatibility_review=_review(),
    )
    add_personality_revision(tmp_path, person_id, instructions="Persona revision 2")
    profile = add_person_revision(
        tmp_path,
        person_id,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0002",
        compatibility_review=_review(),
    )
    assert profile["person_id"] == person_id
    assert len(profile["person_revisions"]) == 2


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


def test_active_person_revision_must_reference_existing_bundle(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Broken")
    broken = json.loads(json.dumps(profile))
    broken["active_person_revision"] = "person-r0001"
    with pytest.raises(PersonProfileError, match="active_person_revision"):
        validate_profile(broken)


def test_boolean_sha_is_rejected(tmp_path: Path) -> None:
    profile = create_profile(tmp_path, display_name="Strict")
    with pytest.raises(PersonProfileError, match="SHA-256"):
        add_body_revision(
            tmp_path,
            profile["person_id"],
            body_id="bodyid-0123456789abcdef01234567",
            package_sha256=True,  # type: ignore[arg-type]
            package_path=r"C:\x.mrbody",
        )

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.person_assembly import (
    PersonAssemblyError,
    build_assembly,
    read_receipt,
    verify_receipt,
    write_receipt,
)
from bodyrig.person_profiles import (
    add_body_revision,
    add_personality_revision,
    add_voice_revision,
    create_profile,
    load_profile,
)

AUDITION_ID = "audition-0123456789abcdef0123456789abcdef"
AUDITION_SHA = "c" * 64


def _profile(root: Path) -> dict:
    profile = create_profile(root, display_name="Anna")
    person_id = profile["person_id"]
    add_body_revision(
        root,
        person_id,
        body_id="bodyid-0123456789abcdef01234567",
        package_sha256="a" * 64,
        package_path=r"C:\BodyRig\anna.mrbody",
    )
    add_voice_revision(
        root,
        person_id,
        voice_id="anna-voice-0001",
        voice_package="anna.mrvoice",
        package_sha256="b" * 64,
    )
    add_personality_revision(
        root,
        person_id,
        instructions="Du er Anna. Rolig, tør og præcis.",
        default_language="da",
        style_notes="rolig og tør",
    )
    return load_profile(root, person_id)


def test_assembly_fingerprint_binds_all_three_component_revisions(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    first = build_assembly(
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
    )
    assert first["body"]["package_sha256"] == "a" * 64
    assert first["voice"]["package_sha256"] == "b" * 64
    assert first["voice"]["voice_package"] == "anna.mrvoice"
    assert len(first["personality"]["instructions_sha256"]) == 64
    assert len(first["assembly_fingerprint"]) == 64

    add_personality_revision(
        tmp_path,
        profile["person_id"],
        instructions="Du er Anna. Mere direkte end før.",
        default_language="da",
        style_notes="mere direkte",
    )
    profile = load_profile(tmp_path, profile["person_id"])
    second = build_assembly(
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0002",
    )
    assert second["assembly_fingerprint"] != first["assembly_fingerprint"]


def test_receipt_is_create_only_and_revalidates_exact_assembly_and_audition(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    assembly = build_assembly(
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
    )
    path = write_receipt(
        tmp_path,
        person_revision="person-r0001",
        assembly=assembly,
        audition_id=AUDITION_ID,
        audition_receipt_sha256=AUDITION_SHA,
    )
    assert path.is_file()
    receipt = read_receipt(tmp_path, person_id=profile["person_id"], person_revision="person-r0001")
    assert receipt["version"] == 2
    assert receipt["assembly_fingerprint"] == assembly["assembly_fingerprint"]
    assert receipt["audition"] == {"audition_id": AUDITION_ID, "receipt_sha256": AUDITION_SHA}
    assert verify_receipt(
        tmp_path,
        person_revision="person-r0001",
        assembly=assembly,
        audition_id=AUDITION_ID,
        audition_receipt_sha256=AUDITION_SHA,
    ) == receipt

    with pytest.raises(PersonAssemblyError, match="already exists"):
        write_receipt(
            tmp_path,
            person_revision="person-r0001",
            assembly=assembly,
            audition_id=AUDITION_ID,
            audition_receipt_sha256=AUDITION_SHA,
        )


def test_receipt_rejects_different_personality_after_review(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    reviewed = build_assembly(
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
    )
    write_receipt(
        tmp_path,
        person_revision="person-r0001",
        assembly=reviewed,
        audition_id=AUDITION_ID,
        audition_receipt_sha256=AUDITION_SHA,
    )

    add_personality_revision(tmp_path, profile["person_id"], instructions="Du er Anna v2.")
    changed = build_assembly(
        load_profile(tmp_path, profile["person_id"]),
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0002",
    )
    with pytest.raises(PersonAssemblyError, match="no longer matches"):
        verify_receipt(
            tmp_path,
            person_revision="person-r0001",
            assembly=changed,
            audition_id=AUDITION_ID,
            audition_receipt_sha256=AUDITION_SHA,
        )


def test_legacy_receipt_can_be_read_but_not_reactivated(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    assembly = build_assembly(
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
    )
    path = tmp_path / "assembly-receipts" / profile["person_id"] / "person-r0001.json"
    path.parent.mkdir(parents=True)
    legacy = {
        "format": "bodyrig-person-assembly-receipt",
        "version": 1,
        "person_id": profile["person_id"],
        "person_revision": "person-r0001",
        "assembly_fingerprint": assembly["assembly_fingerprint"],
        "body": assembly["body"],
        "voice": assembly["voice"],
        "personality": assembly["personality"],
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    assert read_receipt(tmp_path, person_id=profile["person_id"], person_revision="person-r0001")["version"] == 1
    with pytest.raises(PersonAssemblyError, match="legacy"):
        verify_receipt(
            tmp_path,
            person_revision="person-r0001",
            assembly=assembly,
            audition_id=AUDITION_ID,
            audition_receipt_sha256=AUDITION_SHA,
        )

from __future__ import annotations

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


def test_receipt_is_create_only_and_revalidates_exact_assembly(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    assembly = build_assembly(
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
    )
    path = write_receipt(tmp_path, person_revision="person-r0001", assembly=assembly)
    assert path.is_file()
    receipt = read_receipt(tmp_path, person_id=profile["person_id"], person_revision="person-r0001")
    assert receipt["assembly_fingerprint"] == assembly["assembly_fingerprint"]
    assert verify_receipt(tmp_path, person_revision="person-r0001", assembly=assembly) == receipt

    with pytest.raises(PersonAssemblyError, match="already exists"):
        write_receipt(tmp_path, person_revision="person-r0001", assembly=assembly)


def test_receipt_rejects_different_personality_after_review(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    reviewed = build_assembly(
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
    )
    write_receipt(tmp_path, person_revision="person-r0001", assembly=reviewed)

    add_personality_revision(tmp_path, profile["person_id"], instructions="Du er Anna v2.")
    changed = build_assembly(
        load_profile(tmp_path, profile["person_id"]),
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0002",
    )
    with pytest.raises(PersonAssemblyError, match="no longer matches"):
        verify_receipt(tmp_path, person_revision="person-r0001", assembly=changed)

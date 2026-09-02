from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.person_assembly import PersonAssemblyError, build_assembly
from bodyrig.person_profiles import (
    PersonProfileError,
    activate_person_revision,
    add_body_revision,
    add_person_revision,
    add_personality_revision,
    add_voice_revision,
    create_profile,
    load_profile,
)
from bodyrig.person_source_alignment import read_binding, write_binding


REVIEW = {
    "body_voice_match": True,
    "voice_personality_match": True,
    "body_personality_match": True,
    "overall_coherent": True,
    "note": "source-aligned fixture",
}


def _profile(root: Path) -> dict:
    return create_profile(
        root,
        display_name="Source Fixture",
        stash_performer={"id": "42", "name": "Source Fixture", "disambiguation": ""},
    )


def _components(root: Path, person_id: str) -> dict:
    add_body_revision(
        root,
        person_id,
        body_id="fixture-body",
        package_sha256="a" * 64,
        package_path=str(root / "fixture.mrbody"),
    )
    add_voice_revision(
        root,
        person_id,
        voice_id="fixture-voice",
        voice_package="fixture.mrvoice",
        package_sha256="b" * 64,
    )
    return add_personality_revision(
        root,
        person_id,
        instructions="Be the source-bound fixture.",
        default_language="en",
    )


def _bind_body_and_personality(root: Path, profile: dict) -> None:
    write_binding(
        root,
        profile,
        kind="body",
        revision_id="body-r0001",
        evidence_kind="test-body-source-v1",
        evidence_sha256="c" * 64,
        evidence_ref="fixture-body-source",
    )
    write_binding(
        root,
        profile,
        kind="personality",
        revision_id="personality-r0001",
        evidence_kind="test-personality-source-v1",
        evidence_sha256="d" * 64,
        evidence_ref="fixture-personality-source",
    )


def test_source_backed_voice_revision_is_bound_to_exact_package(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile = add_voice_revision(
        tmp_path,
        profile["person_id"],
        voice_id="fixture-voice",
        voice_package="fixture.mrvoice",
        package_sha256="b" * 64,
    )

    receipt = read_binding(
        tmp_path,
        profile,
        kind="voice",
        revision_id="voice-r0001",
    )

    assert receipt["source"]["performer_id"] == "42"
    assert receipt["component"]["artifact_sha256"] == "b" * 64
    assert receipt["evidence"] == {
        "kind": "voicerig-package-v1",
        "sha256": "b" * 64,
        "ref": "fixture.mrvoice",
        "source_files": [],
    }
    assert profile["_source_alignment"]["components"]["voice"]["voice-r0001"]["aligned"] is True

    persisted = json.loads((tmp_path / f"{profile['person_id']}.json").read_text(encoding="utf-8"))
    assert "_source_alignment" not in persisted


def test_source_backed_profile_exposes_blockers_and_assembly_fails_before_audition(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile = _components(tmp_path, profile["person_id"])
    write_binding(
        tmp_path,
        profile,
        kind="body",
        revision_id="body-r0001",
        evidence_kind="test-body-source-v1",
        evidence_sha256="c" * 64,
        evidence_ref="fixture-body-source",
    )
    profile = load_profile(tmp_path, profile["person_id"])

    alignment = profile["_source_alignment"]
    assert alignment["source"]["performer_id"] == "42"
    assert alignment["components"]["body"]["body-r0001"]["aligned"] is True
    assert alignment["components"]["voice"]["voice-r0001"]["aligned"] is True
    assert alignment["components"]["personality"]["personality-r0001"]["aligned"] is False

    with pytest.raises(PersonAssemblyError, match="personality-r0001.*source binding missing"):
        build_assembly(
            profile,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
        )

    with pytest.raises(PersonProfileError, match="personality.*source binding missing"):
        add_person_revision(
            tmp_path,
            profile["person_id"],
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            compatibility_review=REVIEW,
            activate=False,
        )


def test_source_backed_person_revision_and_activation_require_all_bindings(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile = _components(tmp_path, profile["person_id"])
    _bind_body_and_personality(tmp_path, profile)
    profile = load_profile(tmp_path, profile["person_id"])

    alignment = profile["_source_alignment"]["components"]
    assert all(alignment[kind][f"{kind}-r0001"]["aligned"] for kind in ("body", "voice", "personality"))
    assembly = build_assembly(
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
    )
    assert len(assembly["assembly_fingerprint"]) == 64

    profile = add_person_revision(
        tmp_path,
        profile["person_id"],
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
        compatibility_review=REVIEW,
        activate=False,
    )
    assert profile["active_person_revision"] is None

    profile = activate_person_revision(tmp_path, profile["person_id"], "person-r0001")
    assert profile["active_person_revision"] == "person-r0001"

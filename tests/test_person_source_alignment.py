from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.person_source_alignment import (
    PersonSourceAlignmentError,
    alignment_status,
    read_binding,
    require_alignment,
    write_binding,
)


def _profile() -> dict:
    return {
        "person_id": "person-0123456789abcdef0123456789abcdef",
        "source": {
            "kind": "stash-performer",
            "performer_id": "42",
            "performer_name": "Lauren Phillips",
            "disambiguation": "",
        },
        "body_revisions": [
            {
                "revision_id": "body-r0001",
                "body_id": "lauren",
                "package_sha256": "1" * 64,
            }
        ],
        "voice_revisions": [
            {
                "revision_id": "voice-r0001",
                "voice_id": "lauren",
                "voice_package": "lauren.mrvoice",
                "package_sha256": "2" * 64,
            }
        ],
        "personality_revisions": [
            {
                "revision_id": "personality-r0001",
                "instructions": "Warm, direct and dryly funny.",
                "default_language": "en",
                "style_notes": "Observed embodiment; authored inner personality.",
            }
        ],
    }


def _bind_all(root: Path, profile: dict) -> None:
    write_binding(
        root,
        profile,
        kind="body",
        revision_id="body-r0001",
        evidence_kind="stash-physical-session-v1",
        evidence_sha256="a" * 64,
        evidence_ref="physical-session.json",
        source_files=[{"scene_id": "11", "name": "body.mp4", "sha256": "b" * 64}],
    )
    write_binding(
        root,
        profile,
        kind="voice",
        revision_id="voice-r0001",
        evidence_kind="voicerig-stash-source-build-v1",
        evidence_sha256="c" * 64,
        evidence_ref="voicerig-job:abc",
        source_files=[{"scene_id": "11", "name": "body.mp4", "sha256": "b" * 64}],
    )
    write_binding(
        root,
        profile,
        kind="personality",
        revision_id="personality-r0001",
        evidence_kind="personality-blueprint-v1",
        evidence_sha256="d" * 64,
        evidence_ref="personality-blueprints/d.json",
    )


def test_all_three_component_bindings_are_required(tmp_path: Path) -> None:
    profile = _profile()
    status = alignment_status(
        tmp_path,
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
    )
    assert status["aligned"] is False
    assert len(status["blockers"]) == 3

    _bind_all(tmp_path, profile)
    status = require_alignment(
        tmp_path,
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
    )
    assert status["aligned"] is True
    assert status["source"]["performer_id"] == "42"
    assert all(value["aligned"] is True for value in status["components"].values())


def test_binding_is_idempotent_for_same_evidence(tmp_path: Path) -> None:
    profile = _profile()
    first = write_binding(
        tmp_path,
        profile,
        kind="body",
        revision_id="body-r0001",
        evidence_kind="stash-physical-session-v1",
        evidence_sha256="a" * 64,
        evidence_ref="physical-session.json",
    )
    second = write_binding(
        tmp_path,
        profile,
        kind="body",
        revision_id="body-r0001",
        evidence_kind="stash-physical-session-v1",
        evidence_sha256="a" * 64,
        evidence_ref="physical-session.json",
    )
    assert second == first


def test_binding_refuses_different_evidence_for_same_revision(tmp_path: Path) -> None:
    profile = _profile()
    write_binding(
        tmp_path,
        profile,
        kind="voice",
        revision_id="voice-r0001",
        evidence_kind="voicerig-stash-source-build-v1",
        evidence_sha256="a" * 64,
        evidence_ref="voicerig-job:first",
    )
    with pytest.raises(PersonSourceAlignmentError, match="different evidence"):
        write_binding(
            tmp_path,
            profile,
            kind="voice",
            revision_id="voice-r0001",
            evidence_kind="voicerig-stash-source-build-v1",
            evidence_sha256="b" * 64,
            evidence_ref="voicerig-job:second",
        )


def test_binding_fails_when_registered_artifact_changes(tmp_path: Path) -> None:
    profile = _profile()
    write_binding(
        tmp_path,
        profile,
        kind="body",
        revision_id="body-r0001",
        evidence_kind="stash-physical-session-v1",
        evidence_sha256="a" * 64,
        evidence_ref="physical-session.json",
    )
    profile["body_revisions"][0]["package_sha256"] = "f" * 64
    with pytest.raises(PersonSourceAlignmentError, match="artifact mismatch"):
        read_binding(tmp_path, profile, kind="body", revision_id="body-r0001")


def test_binding_fails_when_person_source_identity_changes(tmp_path: Path) -> None:
    profile = _profile()
    write_binding(
        tmp_path,
        profile,
        kind="voice",
        revision_id="voice-r0001",
        evidence_kind="voicerig-stash-source-build-v1",
        evidence_sha256="a" * 64,
        evidence_ref="voicerig-job:abc",
    )
    profile["source"] = {
        "kind": "stash-performer",
        "performer_id": "99",
        "performer_name": "Another Person",
        "disambiguation": "",
    }
    with pytest.raises(PersonSourceAlignmentError, match="identity mismatch"):
        read_binding(tmp_path, profile, kind="voice", revision_id="voice-r0001")


def test_source_file_hashes_are_persisted_without_paths(tmp_path: Path) -> None:
    profile = _profile()
    receipt = write_binding(
        tmp_path,
        profile,
        kind="voice",
        revision_id="voice-r0001",
        evidence_kind="voicerig-stash-source-build-v1",
        evidence_sha256="a" * 64,
        evidence_ref="voicerig-job:abc",
        source_files=[{"scene_id": "11", "name": "clip.mp4", "sha256": "b" * 64}],
    )
    assert receipt["evidence"]["source_files"] == [
        {"scene_id": "11", "name": "clip.mp4", "sha256": "b" * 64}
    ]
    encoded = json.dumps(receipt)
    assert "C:\\" not in encoded
    assert "E:\\" not in encoded

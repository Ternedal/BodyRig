from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from bodyrig.portable_identity import (
    PortableIdentityError,
    build_portable_identity,
    provenance_identity_stage,
    validate_portable_identity,
)


BODYPRINT = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "shape": {
        "shoulder_to_height": 0.24,
        "hip_to_height": 0.19,
        "arm_to_height": 0.44,
        "leg_to_height": 0.53,
    },
    "motion": {"energy": 0.42, "head_motion": 0.21},
}


def _proof() -> dict:
    return {
        "format": "bodyrig-recovery-proof",
        "version": 1,
        "source_count": 2,
        "adapter": "fixture-recovery",
        "revision": "recovery-v1",
        "track_id": "7",
        "observed_frames": 120,
        "bodyprint": BODYPRINT,
    }


def _identity() -> dict:
    return {
        "format": "bodyrig-visual-identity",
        "version": 1,
        "adapter": "fixture-capture",
        "revision": "capture-v1",
        "source_count": 2,
        "subject_track_id": "7",
        "capture": {
            "observed_frames": 120,
            "face_frames": 80,
            "full_body_frames": 100,
            "side_body_frames": 25,
            "rear_body_frames": 20,
        },
        "coverage": {
            "face": 0.9,
            "hair_or_scalp": 0.8,
            "skin": 0.75,
            "clothing": 0.85,
            "full_body": 0.95,
            "back": 0.6,
        },
        "quality": {"sharpness": 0.8, "lighting": 0.7, "visibility": 0.9},
        "privacy": {"contains_source_media": False, "contains_biometric_template": False},
    }


def _sources(tmp_path: Path) -> tuple[Path, Path]:
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mkv"
    first.write_bytes(b"first source bytes")
    second.write_bytes(b"second source bytes")
    return first, second


def test_body_id_is_path_alias_and_order_independent(tmp_path: Path):
    first, second = _sources(tmp_path)
    receipt_a = build_portable_identity(
        proof=_proof(),
        visual_identity=_identity(),
        source_files=[first, second],
        requested_alias="performer-123",
    )

    moved = tmp_path / "moved"
    moved.mkdir()
    first_moved = moved / "renamed-a.mp4"
    second_moved = moved / "renamed-b.mkv"
    first_moved.write_bytes(first.read_bytes())
    second_moved.write_bytes(second.read_bytes())
    receipt_b = build_portable_identity(
        proof=_proof(),
        visual_identity=_identity(),
        source_files=[second_moved, first_moved],
        requested_alias="another-alias",
    )

    assert receipt_a["body_id"] == receipt_b["body_id"]
    assert receipt_a["source_set_sha256"] == receipt_b["source_set_sha256"]
    assert receipt_a["requested_alias"] != receipt_b["requested_alias"]
    serialized = json.dumps(receipt_a, ensure_ascii=False)
    assert str(first) not in serialized
    assert str(second) not in serialized


def test_source_byte_change_changes_body_id(tmp_path: Path):
    first, second = _sources(tmp_path)
    baseline = build_portable_identity(
        proof=_proof(),
        visual_identity=_identity(),
        source_files=[first, second],
        requested_alias="performer-123",
    )
    second.write_bytes(b"second source bytes changed")
    changed = build_portable_identity(
        proof=_proof(),
        visual_identity=_identity(),
        source_files=[first, second],
        requested_alias="performer-123",
    )
    assert changed["body_id"] != baseline["body_id"]


def test_recovery_or_visual_identity_change_changes_body_id(tmp_path: Path):
    first, second = _sources(tmp_path)
    baseline = build_portable_identity(
        proof=_proof(),
        visual_identity=_identity(),
        source_files=[first, second],
        requested_alias="performer-123",
    )
    proof = copy.deepcopy(_proof())
    proof["bodyprint"]["motion"]["energy"] = 0.43
    changed_proof = build_portable_identity(
        proof=proof,
        visual_identity=_identity(),
        source_files=[first, second],
        requested_alias="performer-123",
    )
    identity = copy.deepcopy(_identity())
    identity["quality"]["sharpness"] = 0.81
    changed_identity = build_portable_identity(
        proof=_proof(),
        visual_identity=identity,
        source_files=[first, second],
        requested_alias="performer-123",
    )
    assert changed_proof["body_id"] != baseline["body_id"]
    assert changed_identity["body_id"] != baseline["body_id"]


def test_receipt_tamper_and_count_mismatch_fail_closed(tmp_path: Path):
    first, second = _sources(tmp_path)
    receipt = build_portable_identity(
        proof=_proof(),
        visual_identity=_identity(),
        source_files=[first, second],
        requested_alias="performer-123",
    )
    tampered = copy.deepcopy(receipt)
    tampered["source_set_sha256"] = "0" * 64
    with pytest.raises(PortableIdentityError):
        validate_portable_identity(tampered)
    with pytest.raises(PortableIdentityError):
        build_portable_identity(
            proof=_proof(),
            visual_identity=_identity(),
            source_files=[first],
            requested_alias="performer-123",
        )


def test_provenance_stage_binds_canonical_body_id(tmp_path: Path):
    first, second = _sources(tmp_path)
    receipt = build_portable_identity(
        proof=_proof(),
        visual_identity=_identity(),
        source_files=[first, second],
        requested_alias="performer-123",
    )
    stage = provenance_identity_stage(receipt)
    assert stage == {
        "stage": "identity_content",
        "adapter": "bodyrig.portable_identity",
        "revision": receipt["body_id"].removeprefix("bodyid-"),
    }

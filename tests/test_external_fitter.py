from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.avatar import ProceduralAvatarFitter
from bodyrig.external_fitter import (
    ExternalFitterError,
    build_external_fit_request,
    validate_external_fit_output,
)
from bodyrig.identity import validate_visual_identity


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

IDENTITY = {
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


def _write_output(root: Path) -> None:
    fitted = ProceduralAvatarFitter().fit(BODYPRINT, name="Transport Fixture")
    avatar = fitted.avatar_vrm
    thumbnail = fitted.thumbnail_png
    (root / "avatar.vrm").write_bytes(avatar)
    (root / "thumbnail.png").write_bytes(thumbnail)
    (root / "result.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-avatar-fit-result",
                "version": 1,
                "adapter": "fixture-high-fidelity",
                "revision": "fixture-rev-1",
                "visual_identity": "source-derived",
                "avatar_sha256": hashlib.sha256(avatar).hexdigest(),
                "thumbnail_sha256": hashlib.sha256(thumbnail).hexdigest(),
            }
        ),
        encoding="utf-8",
    )


def test_external_request_contains_metadata_but_no_source_paths_or_media():
    request = build_external_fit_request(
        bodyprint=BODYPRINT,
        name="Fixture Person",
        identity=IDENTITY,
    )
    assert request["format"] == "bodyrig-avatar-fit-request"
    assert request["visual_identity"] == validate_visual_identity(IDENTITY)
    serialized = json.dumps(request)
    assert "C:\\" not in serialized
    assert "/home/" not in serialized
    assert "source_media" not in serialized
    assert "biometric_template" in serialized
    assert request["visual_identity"]["privacy"]["contains_biometric_template"] is False


def test_external_output_is_accepted_only_when_bytes_match_result(tmp_path: Path):
    _write_output(tmp_path)
    result = validate_external_fit_output(
        tmp_path,
        expected_adapter="fixture-high-fidelity",
        expected_revision="fixture-rev-1",
    )
    assert result.visual_identity == "source-derived"
    assert result.fit.adapter == "fixture-high-fidelity"
    assert result.fit.revision == "fixture-rev-1"
    assert result.fit.avatar_vrm.startswith(b"glTF")


def test_external_output_rejects_avatar_tampering(tmp_path: Path):
    _write_output(tmp_path)
    with (tmp_path / "avatar.vrm").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ExternalFitterError, match="avatar_sha256 mismatch"):
        validate_external_fit_output(
            tmp_path,
            expected_adapter="fixture-high-fidelity",
            expected_revision="fixture-rev-1",
        )


def test_external_output_rejects_adapter_substitution(tmp_path: Path):
    _write_output(tmp_path)
    with pytest.raises(ExternalFitterError, match="adapter/revision"):
        validate_external_fit_output(
            tmp_path,
            expected_adapter="different-adapter",
            expected_revision="fixture-rev-1",
        )


def test_external_output_rejects_extra_files(tmp_path: Path):
    _write_output(tmp_path)
    (tmp_path / "debug.pkl").write_bytes(b"unsafe research artifact")
    with pytest.raises(ExternalFitterError, match="exactly result.json"):
        validate_external_fit_output(
            tmp_path,
            expected_adapter="fixture-high-fidelity",
            expected_revision="fixture-rev-1",
        )

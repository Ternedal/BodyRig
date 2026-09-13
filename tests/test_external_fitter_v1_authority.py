from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.avatar import ProceduralAvatarFitter
from bodyrig.external_fitter import ExternalFitterError, validate_external_fit_output
from bodyrig.identity import VisualIdentityError, validate_visual_identity


IDENTITY = {
    "format": "bodyrig-visual-identity",
    "version": 1,
    "adapter": "fixture-capture",
    "revision": "capture-v1",
    "source_count": 1,
    "subject_track_id": "subject-1",
    "capture": {
        "observed_frames": 10,
        "face_frames": 8,
        "full_body_frames": 9,
        "side_body_frames": 2,
        "rear_body_frames": 1,
    },
    "coverage": {
        "face": 0.9,
        "hair_or_scalp": 0.8,
        "skin": 0.8,
        "clothing": 0.8,
        "full_body": 0.9,
        "back": 0.5,
    },
    "quality": {"sharpness": 0.8, "lighting": 0.8, "visibility": 0.9},
    "privacy": {"contains_source_media": False, "contains_biometric_template": False},
}

BODYPRINT = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "shape": {"height_scale": 1.0},
}


def _write_output(root: Path, *, version: object) -> None:
    fitted = ProceduralAvatarFitter().fit(BODYPRINT, name="Transport Fixture")
    avatar = fitted.avatar_vrm
    thumbnail = fitted.thumbnail_png
    (root / "avatar.vrm").write_bytes(avatar)
    (root / "thumbnail.png").write_bytes(thumbnail)
    (root / "result.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-avatar-fit-result",
                "version": version,
                "adapter": "fixture-high-fidelity",
                "revision": "fixture-rev-1",
                "visual_identity": "source-derived",
                "avatar_sha256": hashlib.sha256(avatar).hexdigest(),
                "thumbnail_sha256": hashlib.sha256(thumbnail).hexdigest(),
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("version", [True, False, "1", None, 2])
def test_visual_identity_rejects_non_numeric_v1_authority(version: object) -> None:
    value = json.loads(json.dumps(IDENTITY))
    value["version"] = version
    with pytest.raises(VisualIdentityError, match="format/version"):
        validate_visual_identity(value)


def test_visual_identity_preserves_numeric_one_point_zero_compatibility() -> None:
    value = json.loads(json.dumps(IDENTITY))
    value["version"] = 1.0
    assert validate_visual_identity(value)["version"] == 1.0


@pytest.mark.parametrize("version", [True, False, "1", None, 2])
def test_external_fitter_result_rejects_non_numeric_v1_authority(tmp_path: Path, version: object) -> None:
    _write_output(tmp_path, version=version)
    with pytest.raises(ExternalFitterError, match="format/version"):
        validate_external_fit_output(
            tmp_path,
            expected_adapter="fixture-high-fidelity",
            expected_revision="fixture-rev-1",
        )


def test_external_fitter_result_preserves_numeric_one_point_zero_compatibility(tmp_path: Path) -> None:
    _write_output(tmp_path, version=1.0)
    result = validate_external_fit_output(
        tmp_path,
        expected_adapter="fixture-high-fidelity",
        expected_revision="fixture-rev-1",
    )
    assert result.visual_identity == "source-derived"
    assert result.fit.adapter == "fixture-high-fidelity"

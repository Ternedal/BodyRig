from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.avatar import AvatarError
from bodyrig.avatar_cli import main as avatar_main
from bodyrig.fitters import fitter_names, get_fitter
from bodyrig.identity import VisualIdentityError, validate_visual_identity


IDENTITY = {
    "format": "bodyrig-visual-identity",
    "version": 1,
    "adapter": "fixture-capture",
    "revision": "fixture-v1",
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
    "quality": {
        "sharpness": 0.8,
        "lighting": 0.7,
        "visibility": 0.9,
    },
    "privacy": {
        "contains_source_media": False,
        "contains_biometric_template": False,
    },
}

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
        "revision": "fixture-v1",
        "track_id": "7",
        "observed_frames": 120,
        "bodyprint": BODYPRINT,
    }


def test_visual_identity_profile_is_metadata_only_and_strict():
    validated = validate_visual_identity(IDENTITY)
    assert validated == IDENTITY
    assert validated is not IDENTITY
    assert validated["privacy"]["contains_source_media"] is False
    assert validated["privacy"]["contains_biometric_template"] is False


def test_visual_identity_rejects_source_media_or_biometric_template():
    for field in ("contains_source_media", "contains_biometric_template"):
        value = json.loads(json.dumps(IDENTITY))
        value["privacy"][field] = True
        with pytest.raises(VisualIdentityError):
            validate_visual_identity(value)


def test_visual_identity_rejects_observation_count_above_total():
    value = json.loads(json.dumps(IDENTITY))
    value["capture"]["face_frames"] = 121
    with pytest.raises(VisualIdentityError, match="face_frames"):
        validate_visual_identity(value)


def test_builtin_fitter_registry_is_explicit_about_placeholder_capabilities():
    assert fitter_names() == ("procedural-vrm1",)
    fitter = get_fitter("procedural-vrm1")
    assert fitter.capabilities.visual_identity is False
    assert fitter.capabilities.textures is False
    assert fitter.capabilities.hair is False
    assert fitter.capabilities.clothing is False
    with pytest.raises(AvatarError, match="does not support visual identity"):
        fitter.fit(BODYPRINT, name="Fixture", identity=IDENTITY)


def test_unknown_fitter_fails_closed():
    with pytest.raises(AvatarError, match="unknown avatar fitter"):
        get_fitter("magic-photoreal-cloner")


def test_avatar_cli_refuses_identity_profile_with_placeholder_fitter(tmp_path: Path):
    proof_path = tmp_path / "proof.json"
    identity_path = tmp_path / "identity.json"
    output = tmp_path / "body.mrbody"
    proof_path.write_text(json.dumps(_proof()), encoding="utf-8")
    identity_path.write_text(json.dumps(IDENTITY), encoding="utf-8")

    result = avatar_main(
        [
            str(proof_path),
            "--body-id",
            "fixture-person",
            "--name",
            "Fixture Person",
            "--identity-profile",
            str(identity_path),
            "--out",
            str(output),
        ]
    )
    assert result == 1
    assert not output.exists()


def test_avatar_cli_rejects_identity_profile_from_other_track(tmp_path: Path):
    proof_path = tmp_path / "proof.json"
    identity_path = tmp_path / "identity.json"
    output = tmp_path / "body.mrbody"
    other = json.loads(json.dumps(IDENTITY))
    other["subject_track_id"] = "8"
    proof_path.write_text(json.dumps(_proof()), encoding="utf-8")
    identity_path.write_text(json.dumps(other), encoding="utf-8")

    result = avatar_main(
        [
            str(proof_path),
            "--body-id",
            "fixture-person",
            "--name",
            "Fixture Person",
            "--identity-profile",
            str(identity_path),
            "--out",
            str(output),
        ]
    )
    assert result == 1
    assert not output.exists()

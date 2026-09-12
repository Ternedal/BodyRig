from __future__ import annotations

import copy
import struct

import pytest

from bodyrig.avatar import AvatarError, ProceduralAvatarFitter, _glb, parse_glb_json, validate_vrm1


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


def _raw_json_glb(payload: bytes) -> bytes:
    padded = payload + b" " * ((-len(payload)) % 4)
    chunk = struct.pack("<I4s", len(padded), b"JSON") + padded
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunk)) + chunk


def test_fitter_huge_shape_numeric_fails_with_avatar_error() -> None:
    bodyprint = copy.deepcopy(BODYPRINT)
    bodyprint["shape"]["shoulder_to_height"] = 10**400

    with pytest.raises(AvatarError, match="shoulder_to_height"):
        ProceduralAvatarFitter().fit(bodyprint, name="Huge")


def test_fitter_rejects_boolean_version_but_preserves_numeric_v1_equality() -> None:
    boolean_version = copy.deepcopy(BODYPRINT)
    boolean_version["version"] = True
    with pytest.raises(AvatarError, match="format/version"):
        ProceduralAvatarFitter().fit(boolean_version, name="Boolean")

    numeric_version = copy.deepcopy(BODYPRINT)
    numeric_version["version"] = 1.0
    assert ProceduralAvatarFitter().fit(numeric_version, name="Numeric").avatar_vrm.startswith(b"glTF")


def test_fitter_preserves_shape_upper_boundaries() -> None:
    bodyprint = copy.deepcopy(BODYPRINT)
    bodyprint["shape"] = {
        "shoulder_to_height": 1,
        "hip_to_height": 1.0,
        "arm_to_height": 1,
        "leg_to_height": 1.0,
        "height_scale": 4,
    }

    result = ProceduralAvatarFitter().fit(bodyprint, name="Boundary")
    assert validate_vrm1(result.avatar_vrm)["extras"]["bodyrig"]["sourceDerivedShape"]["height_scale"] == 4.0


def test_vrm_huge_humanoid_scale_fails_with_avatar_error() -> None:
    result = ProceduralAvatarFitter().fit(BODYPRINT, name="Scale")
    document = parse_glb_json(result.avatar_vrm)
    hips_index = document["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]["hips"]["node"]
    document["nodes"][hips_index]["scale"] = [1, 10**400, 1]

    with pytest.raises(AvatarError, match="positive finite scale"):
        validate_vrm1(_glb(document, b""))


def test_glb_integer_digit_limit_is_normalized_to_avatar_error() -> None:
    payload = b'{"asset":{"version":"2.0"},"probe":' + (b"9" * 5000) + b"}"

    with pytest.raises(AvatarError, match="invalid glTF JSON"):
        parse_glb_json(_raw_json_glb(payload))

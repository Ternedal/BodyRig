from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from bodyrig.avatar import AvatarError, ProceduralAvatarFitter, parse_glb_json, validate_vrm1
from bodyrig.avatar_cli import main as avatar_main
from bodyrig.package import validate_package


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


def _node(document: dict, name: str) -> dict:
    return next(node for node in document["nodes"] if node.get("name") == name)


def test_procedural_fitter_emits_vrm1_with_required_humanoid():
    result = ProceduralAvatarFitter().fit(BODYPRINT, name="Fixture Person")
    document = validate_vrm1(result.avatar_vrm)
    vrm = document["extensions"]["VRMC_vrm"]
    assert vrm["specVersion"] == "1.0"
    assert vrm["meta"]["name"] == "Fixture Person"
    assert document["extras"]["bodyrig"]["placeholder"] is True
    assert result.thumbnail_png.startswith(b"\x89PNG\r\n\x1a\n")


def test_source_derived_shoulder_ratio_changes_skeleton_geometry():
    narrow = dict(BODYPRINT)
    narrow["shape"] = dict(BODYPRINT["shape"])
    wide = dict(BODYPRINT)
    wide["shape"] = dict(BODYPRINT["shape"])
    wide["shape"]["shoulder_to_height"] = 0.34

    fitter = ProceduralAvatarFitter()
    narrow_doc = parse_glb_json(fitter.fit(narrow, name="Narrow").avatar_vrm)
    wide_doc = parse_glb_json(fitter.fit(wide, name="Wide").avatar_vrm)

    narrow_x = abs(_node(narrow_doc, "leftShoulder")["translation"][0])
    wide_x = abs(_node(wide_doc, "leftShoulder")["translation"][0])
    assert wide_x > narrow_x
    assert wide_doc["extras"]["bodyrig"]["sourceDerivedShape"]["shoulder_to_height"] == 0.34


def test_fitter_refuses_shape_with_missing_required_observation():
    incomplete = {
        "format": "modelrig-bodyprint",
        "version": 1,
        "shape": {"shoulder_to_height": 0.24},
    }
    with pytest.raises(AvatarError, match="hip_to_height"):
        ProceduralAvatarFitter().fit(incomplete, name="Incomplete")


def test_fit_avatar_cli_builds_valid_mrbody(tmp_path: Path):
    proof = {
        "format": "bodyrig-recovery-proof",
        "version": 1,
        "source_count": 2,
        "adapter": "fixture-recovery",
        "revision": "fixture-v1",
        "track_id": "7",
        "observed_frames": 120,
        "bodyprint": BODYPRINT,
    }
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    package_path = tmp_path / "fixture.mrbody"

    exit_code = avatar_main([
        str(proof_path),
        "--body-id",
        "fixture-person",
        "--name",
        "Fixture Person",
        "--out",
        str(package_path),
    ])
    assert exit_code == 0
    validated = validate_package(package_path)
    assert validated.manifest["id"] == "fixture-person"
    assert validated.bodyprint["shape"]["shoulder_to_height"] == 0.24
    assert [stage["stage"] for stage in validated.provenance["pipeline"]] == ["body-recovery", "avatar-fitting"]
    with zipfile.ZipFile(package_path, "r") as archive:
        validate_vrm1(archive.read("avatar.vrm"))

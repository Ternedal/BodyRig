"""VRM → .mrbody adapter (#1401 renderer decision): one runtime ingress, no identity."""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path

import pytest

from bodyrig import package
from bodyrig import vrm_mrbody as vm
from bodyrig.avatar import ProceduralAvatarFitter

SHAPE = {"height_scale": 1.05, "shoulder_to_height": 0.24, "hip_to_height": 0.19,
         "arm_to_height": 0.40, "leg_to_height": 0.47}


def _procedural_vrm(tmp_path: Path, shape=SHAPE) -> Path:
    result = ProceduralAvatarFitter().fit({"format": "modelrig-bodyprint", "version": 1, "shape": shape}, name="x")
    path = tmp_path / "avatar.vrm"
    path.write_bytes(result.avatar_vrm)
    return path


def _build(tmp_path: Path, vrm: Path, **kw) -> dict:
    args = dict(name="Hero", created_at="2026-11-09T21:00:00Z", export_revision="export-v1+abcdef012345")
    args.update(kw)
    return vm.to_mrbody(vrm, tmp_path / "hero.mrbody", **args)


def test_package_is_valid_and_carries_no_identity(tmp_path):
    vrm = _procedural_vrm(tmp_path)
    report = _build(tmp_path, vrm)
    import hashlib
    vrm_sha = hashlib.sha256(vrm.read_bytes()).hexdigest()
    assert report["id"] == "asset-" + vrm_sha[:24] and report["avatar_sha256"] == vrm_sha
    assert not report["id"].startswith("bodyid-")
    validated = package.validate_package(tmp_path / "hero.mrbody")
    assert validated is not None
    with zipfile.ZipFile(tmp_path / "hero.mrbody") as archive:
        provenance = json.loads(archive.read("provenance.json"))
        bodyprint = json.loads(archive.read("bodyprint.json"))
        manifest = json.loads(archive.read("manifest.json"))
    assert provenance["synthetic_avatar"] is True
    assert [s["stage"] for s in provenance["pipeline"]] == ["third_party_conversion", "mrbody_packaging"]
    assert "identity_content" not in json.dumps(provenance)  # no portable identity stage
    assert set(bodyprint) == {"format", "version", "shape"}  # only measured shape, nothing invented
    assert manifest["id"] == report["id"]


@pytest.mark.parametrize("shape", [SHAPE, {"height_scale": 0.9, "shoulder_to_height": 0.26, "hip_to_height": 0.21,
                                            "arm_to_height": 0.42, "leg_to_height": 0.50}])
def test_measured_lengths_round_trip_the_procedural_avatar(tmp_path, shape):
    """BodyRig's procedural fitter places bones from a known bodyprint; measure it back in metres.

    Lengths must match to 2 %. Height is the world-space mesh extent (crown to sole on a
    real model); the procedural placeholder's head and feet meshes reach past its nominal
    height, so its measured height is 10-15 % above nominal by construction.
    """
    measured = vm.measure_shape(_procedural_vrm(tmp_path, shape).read_bytes())
    nominal_h = shape["height_scale"] * vm.REFERENCE_HEIGHT_M
    measured_h = measured["height_scale"] * vm.REFERENCE_HEIGHT_M
    for key in ("shoulder_to_height", "hip_to_height", "arm_to_height", "leg_to_height"):
        assert math.isclose(measured[key] * measured_h, shape[key] * nominal_h, rel_tol=0.02), key
    assert 1.10 < measured_h / nominal_h < 1.15


def test_mesh_scaled_by_its_node_is_measured_in_world_space():
    doc = {"nodes": [{"mesh": 0, "scale": [1.0, 1.8, 1.0], "translation": [0.0, 0.9, 0.0]}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
           "accessors": [{"min": [-0.5, -0.5, -0.5], "max": [0.5, 0.5, 0.5]}]}
    assert vm._bounds_height(doc) == pytest.approx(1.8)
    doc["nodes"][0]["skin"] = 0  # skinned: glTF ignores the node transform
    assert vm._bounds_height(doc) == pytest.approx(1.0)


def test_weight_transfer_stage_is_recorded_without_any_reference_identifier(tmp_path):
    _build(tmp_path, _procedural_vrm(tmp_path), weight_transfer_applied=True)
    with zipfile.ZipFile(tmp_path / "hero.mrbody") as archive:
        provenance = json.loads(archive.read("provenance.json"))
    assert [s["stage"] for s in provenance["pipeline"]] == ["third_party_conversion", "weight_transfer",
                                                            "mrbody_packaging"]
    assert all(s["revision"] in ("v1", "export-v1+abcdef012345") for s in provenance["pipeline"])


@pytest.mark.parametrize("bad", ["", "XYZ", "0" * 63, "bodyid-" + "0" * 57, "G" * 64])
def test_body_id_requires_an_avatar_hash(bad):
    with pytest.raises(vm.VrmMrbodyError):
        vm.body_id_for(bad)


def test_node_world_positions_compose_rotation_and_scale():
    half = math.sqrt(0.5)
    doc = {"nodes": [
        {"translation": [1.0, 0.0, 0.0], "rotation": [0.0, 0.0, half, half], "children": [1]},  # 90° about Z
        {"translation": [1.0, 0.0, 0.0], "scale": [2.0, 2.0, 2.0], "children": [2]},
        {"translation": [1.0, 0.0, 0.0]},
    ]}
    positions = vm.node_world_positions(doc)
    assert positions[1] == pytest.approx((1.0, 1.0, 0.0), abs=1e-9)
    assert positions[2] == pytest.approx((1.0, 3.0, 0.0), abs=1e-9)  # scaled child offset, rotated


def test_cycle_in_nodes_is_refused():
    with pytest.raises(vm.VrmMrbodyError):
        vm.node_world_positions({"nodes": [{"children": [1]}, {"children": [0]}]})


def test_not_a_vrm_is_refused(tmp_path):
    (tmp_path / "x.vrm").write_bytes(b"glTF-not-really")
    with pytest.raises(Exception):
        _build(tmp_path, tmp_path / "x.vrm")
    assert not (tmp_path / "hero.mrbody").exists()


def test_id_follows_the_avatar_bytes_not_the_input(tmp_path):
    """#1403 review P2: different VRM bytes -> different id; identical bytes -> same id."""
    a_dir = tmp_path / "a"
    a_dir.mkdir()
    a = _procedural_vrm(a_dir)
    first = vm.to_mrbody(a, tmp_path / "1.mrbody", name="x", created_at="2026-11-09T21:00:00Z",
                         export_revision="r")
    again = vm.to_mrbody(a, tmp_path / "2.mrbody", name="x", created_at="2026-11-10T08:00:00Z",
                         export_revision="r")
    assert first["id"] == again["id"]  # time and file name do not change the id
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _procedural_vrm(b_dir, {**SHAPE, "leg_to_height": 0.5})
    other = vm.to_mrbody(b, tmp_path / "3.mrbody", name="x", created_at="2026-11-09T21:00:00Z",
                         export_revision="r")
    assert other["id"] != first["id"]

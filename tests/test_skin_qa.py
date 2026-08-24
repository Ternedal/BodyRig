from __future__ import annotations

import struct
from pathlib import Path

import pytest

from bodyrig.avatar import _glb
from bodyrig.skin_qa import SkinQaError, analyze_vrm_skin, write_report

PACKAGE_HASH = "a" * 64


def _avatar(*, cross_left_arm: bool = False, bad_weight_sum: bool = False, high_fidelity: bool = True) -> bytes:
    nodes = [
        {"name": "pelvis", "translation": [0.0, 0.0, 0.0], "children": [1, 3, 6, 15]},
        {"name": "spine1", "translation": [0.0, 1.0, 0.0], "children": [2, 9, 12]},
        {"name": "head", "translation": [0.0, 1.0, 0.0]},
        {"name": "left_hip", "translation": [0.4, -0.2, 0.0], "children": [4]},
        {"name": "left_knee", "translation": [0.0, -1.0, 0.0], "children": [5]},
        {"name": "left_ankle", "translation": [0.0, -1.0, 0.0]},
        {"name": "right_hip", "translation": [-0.4, -0.2, 0.0], "children": [7]},
        {"name": "right_knee", "translation": [0.0, -1.0, 0.0], "children": [8]},
        {"name": "right_ankle", "translation": [0.0, -1.0, 0.0]},
        {"name": "left_shoulder", "translation": [0.8, 0.5, 0.0], "children": [10]},
        {"name": "left_elbow", "translation": [1.0, 0.0, 0.0], "children": [11]},
        {"name": "left_wrist", "translation": [1.0, 0.0, 0.0]},
        {"name": "right_shoulder", "translation": [-0.8, 0.5, 0.0], "children": [13]},
        {"name": "right_elbow", "translation": [-1.0, 0.0, 0.0], "children": [14]},
        {"name": "right_wrist", "translation": [-1.0, 0.0, 0.0]},
        {"name": "BodyMesh", "mesh": 0, "skin": 0},
    ]
    positions = [
        (1.15, 1.50, 0.0), (2.20, 1.50, 0.0),
        (-1.15, 1.50, 0.0), (-2.20, 1.50, 0.0),
        (0.40, -0.60, 0.0), (0.40, -1.60, 0.0),
        (-0.40, -0.60, 0.0), (-0.40, -1.60, 0.0),
    ]
    joints = [
        (12 if cross_left_arm else 9, 0, 0, 0),
        (13 if cross_left_arm else 10, 0, 0, 0),
        (12, 0, 0, 0), (13, 0, 0, 0),
        (3, 0, 0, 0), (4, 0, 0, 0),
        (6, 0, 0, 0), (7, 0, 0, 0),
    ]
    primary_weight = 0.8 if bad_weight_sum else 1.0
    weights = [(primary_weight, 0.0, 0.0, 0.0) for _ in positions]

    position_bytes = b"".join(struct.pack("<fff", *value) for value in positions)
    joint_bytes = b"".join(struct.pack("<HHHH", *value) for value in joints)
    weight_bytes = b"".join(struct.pack("<ffff", *value) for value in weights)
    joint_offset = len(position_bytes)
    weight_offset = joint_offset + len(joint_bytes)
    binary = position_bytes + joint_bytes + weight_bytes

    extras = {
        "bodyrig": {
            "placeholder": False,
            "sourceDerivedVisualIdentity": True,
            "fitter": {"adapter": "sith-smplx-vrm", "revision": "1"},
            "rigTransfer": {
                "method": "nearest-smplx-vertex-lbs-inverse",
                "nearestDistanceP95": 0.012,
                "nearestDistanceMax": 0.031,
            },
        }
    } if high_fidelity else {"bodyrig": {"placeholder": True}}

    document = {
        "asset": {"version": "2.0"},
        "extensionsUsed": ["VRMC_vrm"],
        "extensions": {
            "VRMC_vrm": {
                "specVersion": "1.0",
                "meta": {
                    "name": "Skin QA fixture",
                    "authors": ["BodyRig CI"],
                    "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
                },
                "humanoid": {
                    "humanBones": {
                        "hips": {"node": 0},
                        "spine": {"node": 1},
                        "head": {"node": 2},
                        "leftUpperLeg": {"node": 3},
                        "leftLowerLeg": {"node": 4},
                        "leftFoot": {"node": 5},
                        "rightUpperLeg": {"node": 6},
                        "rightLowerLeg": {"node": 7},
                        "rightFoot": {"node": 8},
                        "leftUpperArm": {"node": 9},
                        "leftLowerArm": {"node": 10},
                        "leftHand": {"node": 11},
                        "rightUpperArm": {"node": 12},
                        "rightLowerArm": {"node": 13},
                        "rightHand": {"node": 14},
                    }
                },
            }
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "meshes": [{
            "primitives": [{
                "attributes": {"POSITION": 0, "JOINTS_0": 1, "WEIGHTS_0": 2},
                "mode": 4,
            }]
        }],
        "skins": [{"name": "SMPLX", "skeleton": 0, "joints": list(range(15))}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(position_bytes)},
            {"buffer": 0, "byteOffset": joint_offset, "byteLength": len(joint_bytes)},
            {"buffer": 0, "byteOffset": weight_offset, "byteLength": len(weight_bytes)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": len(joints), "type": "VEC4"},
            {"bufferView": 2, "componentType": 5126, "count": len(weights), "type": "VEC4"},
        ],
        "extras": extras,
    }
    return _glb(document, binary)


def test_skin_qa_reports_low_risk_for_anatomically_local_weights() -> None:
    report = analyze_vrm_skin(_avatar(), package_sha256=PACKAGE_HASH, body_id="fixture-body", created_at="2026-08-24T00:00:00Z")
    assert report["structural_pass"] is True
    assert report["manual_review_required"] is True
    assert report["automated_assessment"] == "low-risk"
    assert report["mesh"]["limb_classified_vertex_count"] == 8
    assert report["cross_region"]["suspicious_vertices"] == 0
    assert report["cross_region"]["forbidden_weight_max"] == 0.0


def test_skin_qa_flags_opposite_arm_transfer_as_high_risk() -> None:
    report = analyze_vrm_skin(_avatar(cross_left_arm=True), package_sha256=PACKAGE_HASH, body_id="fixture-body")
    assert report["automated_assessment"] == "high-risk"
    assert report["cross_region"]["severe_vertices"] >= 2
    assert report["cross_region"]["regions"]["left_arm"]["severe"] >= 2
    assert report["cross_region"]["forbidden_weight_max"] == 1.0


def test_skin_qa_rejects_invalid_weight_normalization() -> None:
    with pytest.raises(SkinQaError, match="invalid skin structure"):
        analyze_vrm_skin(_avatar(bad_weight_sum=True), package_sha256=PACKAGE_HASH, body_id="fixture-body")


def test_skin_qa_rejects_placeholder_avatar() -> None:
    with pytest.raises(SkinQaError, match="not source-derived high fidelity"):
        analyze_vrm_skin(_avatar(high_fidelity=False), package_sha256=PACKAGE_HASH, body_id="fixture-body")


def test_skin_qa_report_is_create_only(tmp_path: Path) -> None:
    report = analyze_vrm_skin(_avatar(), package_sha256=PACKAGE_HASH, body_id="fixture-body")
    path = tmp_path / "skin-qa.json"
    assert write_report(path, report) == path.resolve()
    with pytest.raises(SkinQaError, match="already exists"):
        write_report(path, report)

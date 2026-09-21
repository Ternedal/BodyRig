from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pytest

import tools.photoreal_p3_exavatar_quest2_pbr_adapter as adapter
from tools.photoreal_p3_exavatar_quest2_pbr_adapter import (
    ADAPTER,
    FIDELITY_DIMENSIONS,
    STUDENT_COMPONENTS,
    ExAvatarQuest2PbrAdapterError,
    _build_vertex_color_vrm,
    _component_masks,
    _digest,
    _top4_skinning,
    _validate_request,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _glb_json(payload: bytes) -> dict[str, object]:
    assert payload[:4] == b"glTF"
    version, total = struct.unpack_from("<II", payload, 4)
    assert version == 2
    assert total == len(payload)
    length, kind = struct.unpack_from("<I4s", payload, 12)
    assert kind == b"JSON"
    raw = payload[20 : 20 + length].rstrip(b" ")
    return json.loads(raw.decode("utf-8"))


def _request(root: Path, revision: str) -> dict[str, object]:
    specs = (
        ("teacher-checkpoint", "teacher-output", "teacher-output/checkpoint/snapshot_4.pth", b"checkpoint"),
        ("shape-param", "identity-export", "identity-export/identity/shape_param.json", b"[0.0]"),
        ("face-offset", "identity-export", "identity-export/identity/face_offset.json", b"[[0.0,0.0,0.0]]"),
        ("joint-offset", "identity-export", "identity-export/identity/joint_offset.json", b"[[0.0,0.0,0.0]]"),
        ("locator-offset", "identity-export", "identity-export/identity/locator_offset.json", b"[[0.0,0.0,0.0]]"),
    )
    sources = []
    for kind, root_kind, relative, payload in specs:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        sources.append(
            {
                "kind": kind,
                "root_kind": root_kind,
                "relative_path": relative,
                "size_bytes": len(payload),
                "sha256": _sha(payload),
            }
        )
    sources.sort(key=lambda item: (item["root_kind"], item["kind"], item["relative_path"]))
    value: dict[str, object] = {
        "format": adapter.REQUEST_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "p2_animated_human_review_sha256": "4" * 64,
        "p3_device_distillation_plan_sha256": "5" * 64,
        "target_profile": {
            "format": "bodyrig-photoreal-device-target-profile",
            "version": 1,
            "operator_supplied": True,
            "target_family": "meta-quest",
            "target_model": "quest-2",
            "target_runtime": "standalone",
            "target_refresh_hz": 72.0,
            "max_frame_time_ms": 13.888889,
            "stereo_rendering_required": True,
            "vr_safe_frame_pacing_required": True,
            "teacher_quality_ceiling_preserved": True,
            "fidelity_delta_reporting_required": True,
            "production_activation": False,
        },
        "target_profile_sha256": "6" * 64,
        "target_model": "quest-2",
        "adapter": ADAPTER,
        "adapter_revision": revision,
        "student_representation": adapter.STUDENT_REPRESENTATION,
        "student_components": list(STUDENT_COMPONENTS),
        "staged_teacher_sources": sources,
        "required_fidelity_delta_dimensions": list(FIDELITY_DIMENSIONS),
        "teacher_remains_visual_authority": True,
        "student_may_not_claim_fidelity_above_teacher": True,
        "staged_teacher_only": True,
        "p3_distillation_execution_authorized": True,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    value["p3_device_distillation_request_sha256"] = _digest(
        value,
        omit="p3_device_distillation_request_sha256",
    )
    return value


def test_top4_skinning_is_canonical_and_normalized() -> None:
    weights = np.zeros((2, 55), dtype=np.float32)
    weights[0, [1, 2, 3, 4, 5]] = [0.5, 0.2, 0.15, 0.1, 0.05]
    weights[1, [10, 11, 12, 13]] = [0.4, 0.3, 0.2, 0.1]

    joints, selected = _top4_skinning(np, weights)

    assert joints.shape == (2, 4)
    assert selected.shape == (2, 4)
    assert joints[0].tolist() == [1, 2, 3, 4]
    assert np.allclose(selected.sum(axis=1), 1.0)


def test_component_masks_use_eye_joints_and_nonface_head_vertices() -> None:
    dominant = np.asarray([23, 24, 15, 15, 15, 12, 1], dtype=np.int64)
    face = np.asarray([True, True, False, True, False, False, False])

    eye, hair = _component_masks(np, dominant, face)

    assert eye.tolist() == [True, True, False, False, False, False, False]
    assert hair.tolist() == [False, False, True, False, True, False, False]


def test_vertex_color_vrm_has_base_eye_hair_primitives_and_color0() -> None:
    positions = np.asarray(
        [
            [-1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [-0.5, 1.0, 0.0],
            [-0.2, 1.4, 0.1], [0.2, 1.4, 0.1], [0.0, 1.2, 0.1],
            [-0.4, 1.8, 0.0], [0.4, 1.8, 0.0], [0.0, 2.0, 0.0],
        ],
        dtype=np.float32,
    )
    colors = np.linspace(0.1, 0.9, positions.size, dtype=np.float32).reshape(positions.shape)
    faces = np.asarray([[0, 1, 2], [3, 4, 5], [6, 7, 8]], dtype=np.int64)
    joints = np.zeros((len(positions), 4), dtype=np.uint16)
    weights = np.zeros((len(positions), 4), dtype=np.float32)
    weights[:, 0] = 1.0
    rest_joints = np.zeros((55, 3), dtype=np.float32)
    for i in range(1, 55):
        rest_joints[i] = rest_joints[i - 1] + np.asarray([0.0, 0.02, 0.0], dtype=np.float32)
    parents = [-1] + list(range(0, 54))
    eye_mask = np.asarray([False, False, False, True, True, True, False, False, False])
    hair_mask = np.asarray([False, False, False, False, False, False, True, True, True])

    payload, counts = _build_vertex_color_vrm(
        np,
        name="Synthetic Quest Student",
        positions=positions,
        colors=colors,
        faces=faces,
        joints4=joints,
        weights4=weights,
        rest_joints=rest_joints,
        parents=parents,
        eye_mask=eye_mask,
        hair_mask=hair_mask,
    )

    document = _glb_json(payload)
    assert document["asset"]["version"] == "2.0"
    assert document["asset"]["generator"] == "BodyRig ExAvatar Quest2 PBR Student v1"
    primitives = document["meshes"][0]["primitives"]
    assert len(primitives) == 3
    assert all("COLOR_0" in item["attributes"] for item in primitives)
    assert [item["extras"]["bodyrigComponent"] for item in primitives] == [
        "base-skinned-mesh",
        "specialized-eye-component",
        "teacher-derived-hair-component",
    ]
    assert document["extras"]["bodyrig"]["studentComponents"] == list(STUDENT_COMPONENTS)
    assert counts == {
        "base_face_count": 1,
        "eye_face_count": 1,
        "hair_face_count": 1,
    }


def test_request_validation_binds_exact_five_staged_teacher_bytes(tmp_path: Path) -> None:
    revision = "a" * 64
    request = _request(tmp_path, revision)

    sources = _validate_request(request, teacher_root=tmp_path, adapter_revision=revision)

    assert len(sources) == 5
    assert {item["kind"] for item in sources} == {
        "teacher-checkpoint",
        "shape-param",
        "face-offset",
        "joint-offset",
        "locator-offset",
    }


def test_request_validation_rejects_teacher_byte_drift(tmp_path: Path) -> None:
    revision = "a" * 64
    request = _request(tmp_path, revision)
    (tmp_path / "identity-export" / "identity" / "face_offset.json").write_bytes(b"changed")

    with pytest.raises(
        ExAvatarQuest2PbrAdapterError,
        match="size/path drifted|bytes drifted",
    ):
        _validate_request(request, teacher_root=tmp_path, adapter_revision=revision)


def test_request_validation_rejects_non_quest2_target(tmp_path: Path) -> None:
    revision = "a" * 64
    request = _request(tmp_path, revision)
    request["target_model"] = "quest-3"
    request["target_profile"]["target_model"] = "quest-3"
    request["p3_device_distillation_request_sha256"] = _digest(
        request,
        omit="p3_device_distillation_request_sha256",
    )

    with pytest.raises(
        ExAvatarQuest2PbrAdapterError,
        match="pinned to Quest 2",
    ):
        _validate_request(request, teacher_root=tmp_path, adapter_revision=revision)


def test_request_validation_rejects_missing_eye_hair_component(tmp_path: Path) -> None:
    revision = "a" * 64
    request = _request(tmp_path, revision)
    request["student_components"] = ["specialized-eye-component"]
    request["p3_device_distillation_request_sha256"] = _digest(
        request,
        omit="p3_device_distillation_request_sha256",
    )

    with pytest.raises(
        ExAvatarQuest2PbrAdapterError,
        match="component universe mismatch",
    ):
        _validate_request(request, teacher_root=tmp_path, adapter_revision=revision)

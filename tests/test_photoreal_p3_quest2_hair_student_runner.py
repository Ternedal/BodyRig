from __future__ import annotations

import hashlib

import numpy as np
import pytest

import bodyrig.photoreal_p3_quest2_eye_student_runner as eye_runner
import bodyrig.photoreal_p3_quest2_hair_student_runner as hair_runner
from bodyrig.bridges.sith_smplx_vrm_fitter import (
    SMPLX_JOINT_NAMES,
    _build_vrm,
    _thumbnail_png,
)
from bodyrig.photoreal_p3_quest2_eye_student_runner import build_eye_student
from bodyrig.photoreal_p3_quest2_hair_student_runner import (
    PhotorealP3Quest2HairStudentRunnerError,
    build_hair_student,
    validate_hair_envelope,
)
from bodyrig.photoreal_p3_quest2_student_candidate_runner import (
    BLOCKERS as CANDIDATE_BLOCKERS,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _base_avatar() -> tuple[bytes, bytes]:
    positions = np.asarray(
        [
            [-0.04, 1.60, 0.08],
            [-0.02, 1.62, 0.08],
            [-0.02, 1.58, 0.08],
            [0.04, 1.60, 0.08],
            [0.02, 1.62, 0.08],
            [0.02, 1.58, 0.08],
        ],
        dtype=np.float32,
    )
    texcoords = [
        (0.05, 0.45),
        (0.15, 0.55),
        (0.15, 0.35),
        (0.85, 0.45),
        (0.95, 0.55),
        (0.95, 0.35),
    ]
    left_face = [(0, 0), (1, 1), (2, 2)]
    right_face = [(3, 3), (4, 4), (5, 5)]
    faces = [left_face[:] for _ in range(18)] + [
        right_face[:] for _ in range(18)
    ]

    joints4 = np.zeros((6, 4), dtype=np.uint16)
    joints4[:3, 0] = 23
    joints4[3:, 0] = 24
    weights4 = np.zeros((6, 4), dtype=np.float32)
    weights4[:, 0] = 1.0

    rest_joints = np.zeros((len(SMPLX_JOINT_NAMES), 3), dtype=np.float32)
    rest_joints[23] = np.asarray([-0.03, 1.60, 0.08], dtype=np.float32)
    rest_joints[24] = np.asarray([0.03, 1.60, 0.08], dtype=np.float32)
    parents = [-1] + [0] * (len(SMPLX_JOINT_NAMES) - 1)
    texture = _thumbnail_png()
    avatar, _thumbnail = _build_vrm(
        np=np,
        name="P3 hair student fixture",
        rest_positions=positions,
        texcoords=texcoords,
        faces=faces,
        joints4=joints4,
        weights4=weights4,
        rest_joints=rest_joints,
        parents=parents,
        texture_png=texture,
        quality={"nearest_p95": 0.0, "nearest_max": 0.0},
    )
    return avatar, texture


def _candidate(tmp_path):
    output = tmp_path / "candidate-output"
    student = output / "student"
    student.mkdir(parents=True)
    avatar, basecolor = _base_avatar()
    avatar_path = student / "avatar.vrm"
    basecolor_path = student / "basecolor.png"
    avatar_path.write_bytes(avatar)
    basecolor_path.write_bytes(basecolor)
    (output / "quest2-student-candidate.json").write_text("{}\n", encoding="utf-8")

    receipt = {
        "format": "bodyrig-photoreal-p3-quest2-student-candidate-receipt",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p3_device_distillation_plan_sha256": "2" * 64,
        "p3_device_distillation_request_sha256": "3" * 64,
        "p3_quest2_student_candidate_sha256": "4" * 64,
        "target_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "required_student_components": list(eye_runner.REQUIRED_STUDENT_COMPONENTS),
        "implemented_student_components": [],
        "student_artifacts": [
            {
                "kind": "student-runtime-package",
                "relative_path": "student/avatar.vrm",
                "size_bytes": avatar_path.stat().st_size,
                "sha256": _sha(avatar),
            },
            {
                "kind": "teacher-derived-basecolor",
                "relative_path": "student/basecolor.png",
                "size_bytes": basecolor_path.stat().st_size,
                "sha256": _sha(basecolor),
            },
        ],
        "appearance_metrics": {"fixture": True},
        "artifact_bytes_verified_by_core": True,
        "staged_teacher_only": True,
        "student_candidate_complete": True,
        "p3_distillation_complete": False,
        "remaining_blockers": list(CANDIDATE_BLOCKERS),
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    receipt["p3_quest2_student_candidate_receipt_sha256"] = eye_runner._digest(receipt)
    return output, receipt


def _eye_stage(tmp_path):
    candidate_root, candidate_receipt = _candidate(tmp_path)
    eye_root = tmp_path / "eyes"
    eye_receipt = build_eye_student(
        candidate_receipt,
        candidate_output_root=candidate_root,
        output_root=eye_root,
    )
    return eye_root, eye_receipt


def _envelope(eye_receipt: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {
        "format": hair_runner.HAIR_ENVELOPE_FORMAT,
        "version": 1,
        "performer_id": eye_receipt["performer_id"],
        "selected_epoch_id": eye_receipt["selected_epoch_id"],
        "teacher_input_sha256": eye_receipt["teacher_input_sha256"],
        "p3_device_distillation_request_sha256": eye_receipt[
            "p3_device_distillation_request_sha256"
        ],
        "p3_quest2_student_candidate_receipt_sha256": eye_receipt[
            "p3_quest2_student_candidate_receipt_sha256"
        ],
        "teacher_checkpoint_sha256": "5" * 64,
        "generator_sha256": "6" * 64,
        "body_vertex_count": 10475,
        "body_face_count": 36,
        "teacher_point_count": 12000,
        "selection_mode": "strict-teacher-shell",
        "selected_face_count": 32,
        "selected_vertex_count": 6,
        "seed_face_count": 16,
        "body_height": 1.8,
        "head_search_radius": 0.2,
        "outward_offset_p50": 0.01,
        "outward_offset_p95": 0.012,
        "outward_offset_max": 0.014,
        "head_footprint_span_body_ratio": 0.10,
        "vertical_span_body_ratio": 0.08,
        "selected_faces": [
            {
                "face_index": index,
                "corner_offsets": [0.01, 0.012, 0.011],
            }
            for index in range(32)
        ],
        "source_derived": True,
        "generative_geometry": False,
        "body_topology_modified": False,
        "physical_silhouette_review_required": True,
        "hair_component_authority": False,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["hair_envelope_sha256"] = hair_runner._digest(result)
    return result


def test_hair_stage_removes_only_hair_blocker(tmp_path) -> None:
    eye_root, eye_receipt = _eye_stage(tmp_path)
    envelope = _envelope(eye_receipt)

    result = build_hair_student(
        eye_receipt,
        envelope,
        eye_output_root=eye_root,
        output_root=tmp_path / "hair",
    )

    assert result["implemented_student_components"] == [
        "specialized-eye-component",
        "teacher-derived-hair-component",
    ]
    assert result["remaining_blockers"] == [
        "teacher-student-fidelity-delta-measurement",
        "p3-distillation-manifest",
    ]
    assert result["specialized_eye_component_complete"] is True
    assert result["teacher_derived_hair_component_complete"] is True
    assert result["physical_hair_silhouette_review_required"] is True
    assert result["p3_distillation_complete"] is False
    assert result["runtime_acceptance_authority"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False
    assert result["hair_component"]["sourceDerived"] is True
    assert result["hair_component"]["generativeGeometry"] is False


def test_hair_stage_reverifies_eye_student_bytes(tmp_path) -> None:
    eye_root, eye_receipt = _eye_stage(tmp_path)
    envelope = _envelope(eye_receipt)
    (eye_root / "student" / "avatar.vrm").write_bytes(b"drift")

    with pytest.raises(
        PhotorealP3Quest2HairStudentRunnerError,
        match="size/path drifted|bytes drifted",
    ):
        build_hair_student(
            eye_receipt,
            envelope,
            eye_output_root=eye_root,
            output_root=tmp_path / "hair",
        )


def test_hair_envelope_digest_tamper_is_rejected(tmp_path) -> None:
    eye_root, eye_receipt = _eye_stage(tmp_path)
    envelope = _envelope(eye_receipt)
    envelope["selected_face_count"] = 33

    with pytest.raises(
        PhotorealP3Quest2HairStudentRunnerError,
        match="selected-face count differs|digest mismatch",
    ):
        validate_hair_envelope(envelope, eye_receipt=eye_receipt)


def test_hair_envelope_cannot_claim_runtime_authority(tmp_path) -> None:
    _eye_root, eye_receipt = _eye_stage(tmp_path)
    envelope = _envelope(eye_receipt)
    envelope["runtime_acceptance_authority"] = True
    envelope["hair_envelope_sha256"] = hair_runner._digest(
        envelope,
        omit="hair_envelope_sha256",
    )

    with pytest.raises(
        PhotorealP3Quest2HairStudentRunnerError,
        match="authority mismatch",
    ):
        validate_hair_envelope(envelope, eye_receipt=eye_receipt)


def test_hair_stage_preserves_teacher_basecolor_bytes(tmp_path) -> None:
    eye_root, eye_receipt = _eye_stage(tmp_path)
    envelope = _envelope(eye_receipt)
    source = (eye_root / "student" / "basecolor.png").read_bytes()

    build_hair_student(
        eye_receipt,
        envelope,
        eye_output_root=eye_root,
        output_root=tmp_path / "hair",
    )

    copied = (tmp_path / "hair" / "student" / "basecolor.png").read_bytes()
    assert copied == source

from __future__ import annotations

import hashlib

import numpy as np
import pytest

import bodyrig.photoreal_p3_quest2_eye_student_runner as runner
from bodyrig.bridges.sith_smplx_vrm_fitter import (
    SMPLX_JOINT_NAMES,
    _build_vrm,
    _thumbnail_png,
)
from bodyrig.photoreal_p3_quest2_eye_student_runner import (
    PhotorealP3Quest2EyeStudentRunnerError,
    build_eye_student,
    validate_candidate_receipt,
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
    faces = [
        [(0, 0), (1, 1), (2, 2)]
        for _ in range(8)
    ] + [
        [(3, 3), (4, 4), (5, 5)]
        for _ in range(8)
    ]
    joints4 = np.zeros((6, 4), dtype=np.uint16)
    joints4[:3, 0] = 23
    joints4[3:, 0] = 24
    weights4 = np.zeros((6, 4), dtype=np.float32)
    weights4[:, 0] = 1.0
    rest_joints = np.zeros(
        (len(SMPLX_JOINT_NAMES), 3),
        dtype=np.float32,
    )
    parents = [-1] + [0] * (len(SMPLX_JOINT_NAMES) - 1)
    texture = _thumbnail_png()
    avatar, _thumbnail = _build_vrm(
        np=np,
        name="P3 eye student fixture",
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
    (output / "quest2-student-candidate.json").write_text(
        "{}\n",
        encoding="utf-8",
    )

    receipt = {
        "format": (
            "bodyrig-photoreal-p3-quest2-student-candidate-receipt"
        ),
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p3_device_distillation_plan_sha256": "2" * 64,
        "p3_device_distillation_request_sha256": "3" * 64,
        "p3_quest2_student_candidate_sha256": "4" * 64,
        "target_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "required_student_components": list(
            runner.REQUIRED_STUDENT_COMPONENTS
        ),
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
    receipt["p3_quest2_student_candidate_receipt_sha256"] = (
        runner._digest(receipt)
    )
    return output, receipt


def _reseal(receipt: dict[str, object]) -> None:
    receipt["p3_quest2_student_candidate_receipt_sha256"] = (
        runner._digest(
            receipt,
            omit="p3_quest2_student_candidate_receipt_sha256",
        )
    )


def test_eye_stage_removes_only_eye_blocker(tmp_path) -> None:
    candidate_root, receipt = _candidate(tmp_path)

    result = build_eye_student(
        receipt,
        candidate_output_root=candidate_root,
        output_root=tmp_path / "eyes",
    )

    assert result["implemented_student_components"] == [
        "specialized-eye-component"
    ]
    assert result["remaining_blockers"] == [
        "teacher-derived-hair-component",
        "teacher-student-fidelity-delta-measurement",
        "p3-distillation-manifest",
    ]
    assert result["specialized_eye_component_complete"] is True
    assert result["p3_distillation_complete"] is False
    assert result["runtime_acceptance_authority"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False
    assert (
        result["eye_component"]["specializedEyeComponentImplemented"]
        is True
    )


def test_eye_stage_reverifies_candidate_artifact_bytes(tmp_path) -> None:
    candidate_root, receipt = _candidate(tmp_path)
    (candidate_root / "student" / "avatar.vrm").write_bytes(b"drift")

    with pytest.raises(
        PhotorealP3Quest2EyeStudentRunnerError,
        match="size/path drifted|bytes drifted",
    ):
        build_eye_student(
            receipt,
            candidate_output_root=candidate_root,
            output_root=tmp_path / "eyes",
        )


def test_candidate_receipt_cannot_reseal_p3_complete(tmp_path) -> None:
    candidate_root, receipt = _candidate(tmp_path)
    receipt["p3_distillation_complete"] = True
    _reseal(receipt)

    with pytest.raises(
        PhotorealP3Quest2EyeStudentRunnerError,
        match="p3_distillation_complete",
    ):
        validate_candidate_receipt(
            receipt,
            candidate_output_root=candidate_root,
        )


def test_candidate_receipt_digest_tamper_is_rejected(tmp_path) -> None:
    candidate_root, receipt = _candidate(tmp_path)
    receipt["performer_id"] = "different"

    with pytest.raises(
        PhotorealP3Quest2EyeStudentRunnerError,
        match="digest mismatch",
    ):
        validate_candidate_receipt(
            receipt,
            candidate_output_root=candidate_root,
        )


def test_eye_stage_is_create_only(tmp_path) -> None:
    candidate_root, receipt = _candidate(tmp_path)
    output = tmp_path / "eyes"
    output.mkdir()

    with pytest.raises(
        PhotorealP3Quest2EyeStudentRunnerError,
        match="output already exists",
    ):
        build_eye_student(
            receipt,
            candidate_output_root=candidate_root,
            output_root=output,
        )


def test_eye_stage_preserves_teacher_basecolor_bytes(tmp_path) -> None:
    candidate_root, receipt = _candidate(tmp_path)
    source = (candidate_root / "student" / "basecolor.png").read_bytes()

    build_eye_student(
        receipt,
        candidate_output_root=candidate_root,
        output_root=tmp_path / "eyes",
    )

    copied = (tmp_path / "eyes" / "student" / "basecolor.png").read_bytes()
    assert copied == source

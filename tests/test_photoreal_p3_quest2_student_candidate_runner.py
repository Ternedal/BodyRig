from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import bodyrig.photoreal_p3_quest2_student_candidate_runner as runner
from bodyrig.photoreal_p3_quest2_student_candidate_runner import (
    PhotorealP3Quest2StudentCandidateRunnerError,
    build_candidate_receipt,
    validate_candidate_manifest,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _request() -> dict[str, object]:
    return {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p3_device_distillation_plan_sha256": "2" * 64,
        "p3_device_distillation_request_sha256": "3" * 64,
        "target_profile": {"target_model": "quest-2"},
        "adapter": "quest2-candidate",
        "adapter_revision": "4" * 64,
        "student_representation": "skinned-mesh-pbr",
        "student_components": list(runner.REQUIRED_STUDENT_COMPONENTS),
        "staged_teacher_sources": [
            {
                "kind": "teacher-checkpoint",
                "root_kind": "teacher-output",
                "relative_path": "teacher-output/checkpoint/snapshot_4.pth",
                "size_bytes": 10,
                "sha256": "5" * 64,
            }
        ],
    }


def _candidate(tmp_path: Path) -> tuple[dict[str, object], dict[str, object], Path]:
    output = tmp_path / "output"
    student = output / "student"
    student.mkdir(parents=True)
    avatar = student / "avatar.vrm"
    basecolor = student / "basecolor.png"
    avatar.write_bytes(b"vrm-bytes")
    basecolor.write_bytes(b"png-bytes")

    request = _request()
    metrics = {
        "appearance_method": "exavatar-gaussian-nearest-canonical-uv-v1",
        "canonical_uv_template_sha256": "6" * 64,
        "teacher_point_count": 20000.0,
        "baked_basecolor_sha256": _sha(basecolor.read_bytes()),
        "bake_width": 1024.0,
        "bake_height": 1024.0,
        "bake_occupied_texel_count": 500000.0,
        "bake_occupied_ratio": 0.47,
        "bake_padded_texel_ratio": 0.55,
        "bake_gutter_pixels": 8.0,
        "teacher_point_distance_mean": 0.001,
        "teacher_point_distance_p95": 0.004,
        "teacher_point_distance_max": 0.02,
    }
    value: dict[str, object] = {
        "format": runner.CANDIDATE_FORMAT,
        "version": 1,
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "p3_device_distillation_plan_sha256": request[
            "p3_device_distillation_plan_sha256"
        ],
        "p3_device_distillation_request_sha256": request[
            "p3_device_distillation_request_sha256"
        ],
        "target_model": "quest-2",
        "adapter": request["adapter"],
        "adapter_revision": request["adapter_revision"],
        "student_representation": "skinned-mesh-pbr",
        "required_student_components": list(runner.REQUIRED_STUDENT_COMPONENTS),
        "implemented_student_components": [],
        "geometry_source": "accepted-exavatar-refined-first-subdivision-gaussian-surface",
        "appearance_source": "accepted-exavatar-refined-zero-pose-gaussian-rgb",
        "teacher_checkpoint_sha256": "5" * 64,
        "student_artifacts": [
            {
                "kind": "student-runtime-package",
                "relative_path": "student/avatar.vrm",
                "size_bytes": avatar.stat().st_size,
                "sha256": _sha(avatar.read_bytes()),
            },
            {
                "kind": "teacher-derived-basecolor",
                "relative_path": "student/basecolor.png",
                "size_bytes": basecolor.stat().st_size,
                "sha256": _sha(basecolor.read_bytes()),
            },
        ],
        "appearance_metrics": metrics,
        "teacher_point_count": 20000,
        "body_vertex_count": 42000,
        "body_face_count": 20908 * 4,
        "joint_count": 55,
        "student_candidate_complete": True,
        "p3_distillation_complete": False,
        "remaining_blockers": list(runner.BLOCKERS),
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    value["p3_quest2_student_candidate_sha256"] = runner._digest(value)
    return request, value, output


def _reseal(value: dict[str, object]) -> None:
    value["p3_quest2_student_candidate_sha256"] = runner._digest(
        value,
        omit="p3_quest2_student_candidate_sha256",
    )


def test_candidate_manifest_verifies_real_artifact_bytes(
    tmp_path: Path,
) -> None:
    request, value, output = _candidate(tmp_path)

    validated = validate_candidate_manifest(
        value,
        request=request,
        output_dir=output,
    )
    receipt = build_candidate_receipt(validated)

    assert validated["student_candidate_complete"] is True
    assert validated["p3_distillation_complete"] is False
    assert receipt["artifact_bytes_verified_by_core"] is True
    assert receipt["implemented_student_components"] == []
    assert receipt["remaining_blockers"] == list(runner.BLOCKERS)
    assert receipt["runtime_acceptance_authority"] is False
    assert receipt["photoreal_acceptance_authority"] is False
    assert receipt["production_activation"] is False


def test_candidate_manifest_rejects_basecolor_byte_drift(
    tmp_path: Path,
) -> None:
    request, value, output = _candidate(tmp_path)
    (output / "student" / "basecolor.png").write_bytes(b"changed")

    with pytest.raises(
        PhotorealP3Quest2StudentCandidateRunnerError,
        match="size/path mismatch|SHA-256 mismatch",
    ):
        validate_candidate_manifest(
            value,
            request=request,
            output_dir=output,
        )


def test_candidate_manifest_rejects_undeclared_output(
    tmp_path: Path,
) -> None:
    request, value, output = _candidate(tmp_path)
    (output / "student" / "extra.bin").write_bytes(b"x")

    with pytest.raises(
        PhotorealP3Quest2StudentCandidateRunnerError,
        match="artifact universe differs",
    ):
        validate_candidate_manifest(
            value,
            request=request,
            output_dir=output,
        )


def test_candidate_cannot_claim_eye_or_hair_implemented(
    tmp_path: Path,
) -> None:
    request, value, output = _candidate(tmp_path)
    value["implemented_student_components"] = ["specialized-eye-component"]
    _reseal(value)

    with pytest.raises(
        PhotorealP3Quest2StudentCandidateRunnerError,
        match="may not claim implemented eye/hair",
    ):
        validate_candidate_manifest(
            value,
            request=request,
            output_dir=output,
        )


def test_candidate_rejects_low_resolution_mannequin_topology(
    tmp_path: Path,
) -> None:
    request, value, output = _candidate(tmp_path)
    value["body_vertex_count"] = 10475
    value["body_face_count"] = 20908
    _reseal(value)

    with pytest.raises(
        PhotorealP3Quest2StudentCandidateRunnerError,
        match="first-subdivision surface|canonical first subdivision",
    ):
        validate_candidate_manifest(
            value,
            request=request,
            output_dir=output,
        )


def test_candidate_cannot_claim_p3_complete(
    tmp_path: Path,
) -> None:
    request, value, output = _candidate(tmp_path)
    value["p3_distillation_complete"] = True
    _reseal(value)

    with pytest.raises(
        PhotorealP3Quest2StudentCandidateRunnerError,
        match="p3_distillation_complete",
    ):
        validate_candidate_manifest(
            value,
            request=request,
            output_dir=output,
        )


def test_candidate_rejects_resealed_runtime_authority(
    tmp_path: Path,
) -> None:
    request, value, output = _candidate(tmp_path)
    value["runtime_acceptance_authority"] = True
    _reseal(value)

    with pytest.raises(
        PhotorealP3Quest2StudentCandidateRunnerError,
        match="runtime_acceptance_authority",
    ):
        validate_candidate_manifest(
            value,
            request=request,
            output_dir=output,
        )


def test_candidate_rejects_boolean_v1(tmp_path: Path) -> None:
    request, value, output = _candidate(tmp_path)
    value["version"] = True
    _reseal(value)

    with pytest.raises(
        PhotorealP3Quest2StudentCandidateRunnerError,
        match="format/version mismatch",
    ):
        validate_candidate_manifest(
            value,
            request=request,
            output_dir=output,
        )

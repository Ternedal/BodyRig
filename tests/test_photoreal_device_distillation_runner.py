from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_device_distillation_execution_receipt import (
    PhotorealDeviceDistillationExecutionReceiptError,
    build_device_distillation_execution_receipt,
    validate_device_distillation_execution_receipt,
)
from bodyrig.photoreal_device_distillation_plan import (
    CANDIDATE_REPRESENTATIONS,
    FIDELITY_DIMENSIONS,
)
from bodyrig.photoreal_device_distillation_runner import (
    PhotorealDeviceDistillationRunnerError,
    build_distillation_request,
    validate_distillation_config,
    validate_distillation_result,
)


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _profile() -> dict[str, object]:
    refresh = 72.0
    return {
        "format": "bodyrig-photoreal-device-target-profile",
        "version": 1,
        "operator_supplied": True,
        "target_family": "meta-quest",
        "target_model": "quest-2",
        "target_runtime": "standalone",
        "target_refresh_hz": refresh,
        "max_frame_time_ms": round(1000.0 / refresh, 6),
        "stereo_rendering_required": True,
        "vr_safe_frame_pacing_required": True,
        "teacher_quality_ceiling_preserved": True,
        "fidelity_delta_reporting_required": True,
        "production_activation": False,
    }


def _plan(source_sha: str, source_size: int) -> dict[str, object]:
    profile = _profile()
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-device-distillation-plan",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "teacher_manifest_sha256": "b" * 64,
        "static_teacher_review_sha256": "c" * 64,
        "animation_plan_sha256": "d" * 64,
        "animation_execution_receipt_sha256": "e" * 64,
        "animated_teacher_review_sha256": "f" * 64,
        "target_profile": profile,
        "target_profile_sha256": _digest(profile, "target_profile_sha256"),
        "distillation_source_artifact_count": 1,
        "distillation_source_artifacts": [
            {
                "kind": "animated-review-media",
                "relative_path": "animation/motion.bin",
                "size_bytes": source_size,
                "sha256": source_sha,
            }
        ],
        "source_artifact_bytes_reverified": True,
        "candidate_student_representations": list(CANDIDATE_REPRESENTATIONS),
        "gaussian_splat_requires_explicit_target_support": True,
        "teacher_remains_visual_authority": True,
        "student_may_not_claim_fidelity_above_teacher": True,
        "required_fidelity_delta_dimensions": list(FIDELITY_DIMENSIONS),
        "required_fidelity_delta_dimension_count": len(FIDELITY_DIMENSIONS),
        "fidelity_delta_measurement_required": True,
        "human_runtime_visual_acceptance_required": True,
        "distillation_adapter_required": True,
        "distillation_adapter_selected": False,
        "p3_distillation_execution_authorized": True,
        "runtime_acceptance_authority": False,
        "production_activation": False,
    }
    value["device_distillation_plan_sha256"] = _digest(value, "device_distillation_plan_sha256")
    return value


def _config(*, representation: str = "skinned-mesh-neural-texture", gaussian_support: bool = False) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-device-distillation-config",
        "version": 1,
        "adapter": "test-distiller",
        "revision": "rev-1",
        "student_representation": representation,
        "command": ["python", "adapter.py"],
        "timeout_seconds": 3600,
        "supported_target_models": ["quest-2"],
        "supported_fidelity_delta_dimensions": list(FIDELITY_DIMENSIONS),
        "reports_teacher_student_delta": True,
        "gaussian_splat_target_support": gaussian_support,
    }


def _source_root(tmp_path: Path) -> tuple[Path, str, int]:
    root = tmp_path / "animation-output"
    source = root / "animation" / "motion.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"accepted-animated-teacher-output")
    (root / "animation-manifest.json").write_text("{}\n", encoding="utf-8")
    return root, hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size


def _result(tmp_path: Path, request: dict[str, object]) -> tuple[Path, dict[str, object]]:
    output = tmp_path / "student-output"
    artifact = output / "student" / "avatar.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"distilled-student-bytes")
    measurements = [
        {
            "dimension": dimension,
            "metric": "test-delta",
            "value": round((index + 1) / 100.0, 6),
            "unit": "normalized-delta",
            "teacher_reference": "accepted-animated-teacher",
            "student_reference": "distilled-student",
        }
        for index, dimension in enumerate(FIDELITY_DIMENSIONS)
    ]
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-device-distillation-manifest",
        "version": 1,
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "teacher_manifest_sha256": request["teacher_manifest_sha256"],
        "static_teacher_review_sha256": request["static_teacher_review_sha256"],
        "animation_plan_sha256": request["animation_plan_sha256"],
        "animation_execution_receipt_sha256": request["animation_execution_receipt_sha256"],
        "animated_teacher_review_sha256": request["animated_teacher_review_sha256"],
        "device_distillation_plan_sha256": request["device_distillation_plan_sha256"],
        "target_profile_sha256": request["target_profile_sha256"],
        "adapter": request["adapter"],
        "adapter_revision": request["adapter_revision"],
        "student_representation": request["student_representation"],
        "distillation_complete": True,
        "consumed_distillation_source_artifacts": [
            {
                "relative_path": request["distillation_source_artifacts"][0]["relative_path"],
                "sha256": request["distillation_source_artifacts"][0]["sha256"],
            }
        ],
        "fidelity_delta_measurements": measurements,
        "student_artifacts": [
            {
                "kind": "student-runtime-package",
                "relative_path": "student/avatar.bin",
                "size_bytes": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
        ],
        "student_fidelity_claim_exceeds_teacher": False,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "production_activation": False,
    }
    return output, value


def test_valid_p3_runner_boundary_produces_core_receipt_without_runtime_acceptance(tmp_path: Path) -> None:
    source_root, source_sha, source_size = _source_root(tmp_path)
    request = build_distillation_request(_config(), _plan(source_sha, source_size), animation_output_root=source_root)
    output, raw = _result(tmp_path, request)
    validated = validate_distillation_result(raw, request=request, output_dir=output)
    receipt = validate_device_distillation_execution_receipt(build_device_distillation_execution_receipt(validated))
    assert receipt["distillation_complete"] is True
    assert receipt["artifact_bytes_verified_by_core"] is True
    assert [item["dimension"] for item in receipt["fidelity_delta_measurements"]] == list(FIDELITY_DIMENSIONS)
    assert receipt["student_fidelity_claim_exceeds_teacher"] is False
    assert receipt["human_runtime_visual_acceptance_required"] is True
    assert receipt["runtime_acceptance_authority"] is False
    assert receipt["production_activation"] is False


def test_gaussian_representation_requires_explicit_target_support() -> None:
    with pytest.raises(PhotorealDeviceDistillationRunnerError, match="explicit target support"):
        validate_distillation_config(_config(representation="gaussian-splat-optional", gaussian_support=False))


def test_build_request_rejects_source_byte_drift(tmp_path: Path) -> None:
    source_root, source_sha, source_size = _source_root(tmp_path)
    plan = _plan(source_sha, source_size)
    (source_root / "animation" / "motion.bin").write_bytes(b"changed")
    with pytest.raises(PhotorealDeviceDistillationRunnerError, match="size drifted|bytes drifted"):
        build_distillation_request(_config(), plan, animation_output_root=source_root)


def test_result_rejects_missing_fidelity_dimension(tmp_path: Path) -> None:
    source_root, source_sha, source_size = _source_root(tmp_path)
    request = build_distillation_request(_config(), _plan(source_sha, source_size), animation_output_root=source_root)
    output, raw = _result(tmp_path, request)
    raw["fidelity_delta_measurements"].pop()
    with pytest.raises(PhotorealDeviceDistillationRunnerError, match="fidelity delta universe is incomplete"):
        validate_distillation_result(raw, request=request, output_dir=output)


def test_result_rejects_unauthorized_consumed_source(tmp_path: Path) -> None:
    source_root, source_sha, source_size = _source_root(tmp_path)
    request = build_distillation_request(_config(), _plan(source_sha, source_size), animation_output_root=source_root)
    output, raw = _result(tmp_path, request)
    raw["consumed_distillation_source_artifacts"][0]["sha256"] = "9" * 64
    with pytest.raises(PhotorealDeviceDistillationRunnerError, match="unauthorized source artifact bytes"):
        validate_distillation_result(raw, request=request, output_dir=output)


def test_result_rejects_student_artifact_byte_drift(tmp_path: Path) -> None:
    source_root, source_sha, source_size = _source_root(tmp_path)
    request = build_distillation_request(_config(), _plan(source_sha, source_size), animation_output_root=source_root)
    output, raw = _result(tmp_path, request)
    (output / "student" / "avatar.bin").write_bytes(b"changed-after-distillation")
    with pytest.raises(PhotorealDeviceDistillationRunnerError, match="size mismatch|SHA-256 mismatch"):
        validate_distillation_result(raw, request=request, output_dir=output)


def test_result_cannot_self_authorize_runtime_acceptance(tmp_path: Path) -> None:
    source_root, source_sha, source_size = _source_root(tmp_path)
    request = build_distillation_request(_config(), _plan(source_sha, source_size), animation_output_root=source_root)
    output, raw = _result(tmp_path, request)
    raw["runtime_acceptance_authority"] = True
    with pytest.raises(PhotorealDeviceDistillationRunnerError, match="crossed runtime/production authority"):
        validate_distillation_result(raw, request=request, output_dir=output)


def test_execution_receipt_rejects_resealed_runtime_authority_tamper(tmp_path: Path) -> None:
    source_root, source_sha, source_size = _source_root(tmp_path)
    request = build_distillation_request(_config(), _plan(source_sha, source_size), animation_output_root=source_root)
    output, raw = _result(tmp_path, request)
    validated = validate_distillation_result(raw, request=request, output_dir=output)
    receipt = build_device_distillation_execution_receipt(validated)
    receipt["runtime_acceptance_authority"] = True
    receipt["device_distillation_execution_receipt_sha256"] = _digest(
        receipt, "device_distillation_execution_receipt_sha256"
    )
    with pytest.raises(PhotorealDeviceDistillationExecutionReceiptError, match="crossed runtime/production authority"):
        validate_device_distillation_execution_receipt(receipt)

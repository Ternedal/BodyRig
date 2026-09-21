from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p3_device_distillation_runner as runner
from bodyrig.photoreal_p3_device_distillation_runner import (
    CANDIDATE_STUDENT_REPRESENTATIONS,
    CONFIG_FORMAT,
    FIDELITY_DELTA_DIMENSIONS,
    PhotorealP3DeviceDistillationRunnerError,
    build_distillation_request,
    build_execution_receipt,
    stage_teacher_sources,
    validate_distillation_config,
    validate_distillation_result,
    validate_execution_receipt,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _roots(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    teacher = tmp_path / "teacher"
    identity = tmp_path / "identity"
    checkpoint = teacher / "checkpoint" / "snapshot_4.pth"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"checkpoint")

    sources: list[dict[str, object]] = [
        {
            "kind": "teacher-checkpoint",
            "root_kind": "teacher-output",
            "relative_path": "checkpoint/snapshot_4.pth",
            "size_bytes": checkpoint.stat().st_size,
            "sha256": _sha(checkpoint.read_bytes()),
        }
    ]
    for kind, name, payload in (
        ("shape-param", "shape_param.json", b"shape"),
        ("face-offset", "face_offset.json", b"face"),
        ("joint-offset", "joint_offset.json", b"joint"),
        ("locator-offset", "locator_offset.json", b"locator"),
    ):
        path = identity / "identity" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        sources.append(
            {
                "kind": kind,
                "root_kind": "identity-export",
                "relative_path": f"identity/{name}",
                "size_bytes": path.stat().st_size,
                "sha256": _sha(path.read_bytes()),
            }
        )
    sources.sort(
        key=lambda item: (
            item["root_kind"],
            item["kind"],
            item["relative_path"],
        )
    )

    profile = {
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
    }
    plan: dict[str, object] = {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "p2_animated_human_review_sha256": "4" * 64,
        "p3_device_distillation_plan_sha256": "5" * 64,
        "target_profile": profile,
        "target_profile_sha256": "6" * 64,
        "teacher_source_artifacts": sources,
        "candidate_student_representations": list(
            CANDIDATE_STUDENT_REPRESENTATIONS
        ),
    }
    return teacher, identity, plan


def _config(
    *,
    representation: str = "skinned-mesh-neural-texture",
    gaussian_support: bool = False,
) -> dict[str, object]:
    return {
        "format": CONFIG_FORMAT,
        "version": 1,
        "adapter": "test-distiller",
        "revision": "rev-1",
        "student_representation": representation,
        "student_components": list(runner.REQUIRED_STUDENT_COMPONENTS),
        "command": ["python", "adapter.py"],
        "timeout_seconds": 3600,
        "supported_target_models": ["quest-2"],
        "supported_fidelity_delta_dimensions": list(
            FIDELITY_DELTA_DIMENSIONS
        ),
        "reports_teacher_student_delta": True,
        "gaussian_splat_target_support": gaussian_support,
        "consumes_staged_teacher_only": True,
    }


def _trust_plan(
    monkeypatch: pytest.MonkeyPatch,
    plan: dict[str, object],
) -> None:
    monkeypatch.setattr(
        runner,
        "require_p3_distillation_execution_authority",
        lambda value: plan,
    )


def _result(
    output: Path,
    request: dict[str, object],
) -> dict[str, object]:
    artifact = output / "student" / "avatar.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"student-runtime")
    measurements = [
        {
            "dimension": dimension,
            "metric": "normalized-delta",
            "value": round((index + 1) / 100.0, 6),
            "unit": "delta",
            "teacher_reference": "accepted-exavatar-teacher",
            "student_reference": "student-runtime",
        }
        for index, dimension in enumerate(FIDELITY_DELTA_DIMENSIONS)
    ]
    return {
        "format": runner.RESULT_FORMAT,
        "version": 1,
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "p2_animation_plan_sha256": request["p2_animation_plan_sha256"],
        "p2_exavatar_animation_execution_input_sha256": request[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "p2_animated_human_review_sha256": request[
            "p2_animated_human_review_sha256"
        ],
        "p3_device_distillation_plan_sha256": request[
            "p3_device_distillation_plan_sha256"
        ],
        "p3_device_distillation_request_sha256": request[
            "p3_device_distillation_request_sha256"
        ],
        "target_profile_sha256": request["target_profile_sha256"],
        "adapter": request["adapter"],
        "adapter_revision": request["adapter_revision"],
        "student_representation": request["student_representation"],
        "student_components": request["student_components"],
        "distillation_complete": True,
        "consumed_teacher_sources": [
            {
                "kind": item["kind"],
                "root_kind": item["root_kind"],
                "relative_path": item["relative_path"],
                "sha256": item["sha256"],
            }
            for item in request["staged_teacher_sources"]
        ],
        "fidelity_delta_measurements": measurements,
        "student_artifacts": [
            {
                "kind": "student-runtime-package",
                "relative_path": "student/avatar.bin",
                "size_bytes": artifact.stat().st_size,
                "sha256": _sha(artifact.read_bytes()),
            }
        ],
        "student_fidelity_claim_exceeds_teacher": False,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def test_stage_teacher_sources_copies_exact_five_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, plan = _roots(tmp_path)
    _trust_plan(monkeypatch, plan)

    staged = stage_teacher_sources(
        plan,
        teacher_output_root=teacher,
        identity_root=identity,
        staged_root=tmp_path / "staged",
    )

    assert len(staged) == 5
    assert {item["kind"] for item in staged} == {
        "teacher-checkpoint",
        "shape-param",
        "face-offset",
        "joint-offset",
        "locator-offset",
    }
    assert all(
        item["relative_path"].startswith(
            ("teacher-output/", "identity-export/")
        )
        for item in staged
    )


def test_stage_teacher_sources_rejects_original_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, plan = _roots(tmp_path)
    _trust_plan(monkeypatch, plan)
    (identity / "identity" / "face_offset.json").write_bytes(b"changed")

    with pytest.raises(
        PhotorealP3DeviceDistillationRunnerError,
        match="size/path drifted|bytes drifted",
    ):
        stage_teacher_sources(
            plan,
            teacher_output_root=teacher,
            identity_root=identity,
            staged_root=tmp_path / "staged",
        )


def test_build_request_binds_staged_teacher_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, plan = _roots(tmp_path)
    _trust_plan(monkeypatch, plan)
    staged = stage_teacher_sources(
        plan,
        teacher_output_root=teacher,
        identity_root=identity,
        staged_root=tmp_path / "staged",
    )

    request = build_distillation_request(
        _config(),
        plan,
        staged_teacher_sources=staged,
    )

    assert request["staged_teacher_only"] is True
    assert request["teacher_remains_visual_authority"] is True
    assert request["student_may_not_claim_fidelity_above_teacher"] is True
    assert request["runtime_acceptance_authority"] is False
    assert request["production_activation"] is False
    assert len(request["staged_teacher_sources"]) == 5


def test_gaussian_representation_requires_explicit_support() -> None:
    with pytest.raises(
        PhotorealP3DeviceDistillationRunnerError,
        match="explicit target support",
    ):
        validate_distillation_config(
            _config(
                representation="gaussian-splat-optional",
                gaussian_support=False,
            )
        )


def test_adapter_must_consume_staged_teacher_only() -> None:
    config = _config()
    config["consumes_staged_teacher_only"] = False
    with pytest.raises(
        PhotorealP3DeviceDistillationRunnerError,
        match="staged teacher copies only",
    ):
        validate_distillation_config(config)


def test_valid_result_becomes_core_receipt_without_runtime_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, plan = _roots(tmp_path)
    _trust_plan(monkeypatch, plan)
    staged = stage_teacher_sources(
        plan,
        teacher_output_root=teacher,
        identity_root=identity,
        staged_root=tmp_path / "staged",
    )
    request = build_distillation_request(
        _config(),
        plan,
        staged_teacher_sources=staged,
    )
    output = tmp_path / "output"
    output.mkdir()
    raw = _result(output, request)

    validated = validate_distillation_result(
        raw,
        request=request,
        output_dir=output,
    )
    receipt = build_execution_receipt(validated)
    assert validate_execution_receipt(receipt) == receipt
    assert receipt["distillation_complete"] is True
    assert receipt["artifact_bytes_verified_by_core"] is True
    assert receipt["staged_teacher_only"] is True
    assert receipt["student_fidelity_claim_exceeds_teacher"] is False
    assert [
        item["dimension"] for item in receipt["fidelity_delta_measurements"]
    ] == list(FIDELITY_DELTA_DIMENSIONS)
    assert receipt["runtime_acceptance_authority"] is False
    assert receipt["photoreal_acceptance_authority"] is False
    assert receipt["production_activation"] is False


def test_result_rejects_missing_fidelity_dimension(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, plan = _roots(tmp_path)
    _trust_plan(monkeypatch, plan)
    staged = stage_teacher_sources(
        plan,
        teacher_output_root=teacher,
        identity_root=identity,
        staged_root=tmp_path / "staged",
    )
    request = build_distillation_request(
        _config(),
        plan,
        staged_teacher_sources=staged,
    )
    output = tmp_path / "output"
    output.mkdir()
    raw = _result(output, request)
    raw["fidelity_delta_measurements"].pop()

    with pytest.raises(
        PhotorealP3DeviceDistillationRunnerError,
        match="fidelity delta universe is incomplete",
    ):
        validate_distillation_result(
            raw,
            request=request,
            output_dir=output,
        )


def test_result_rejects_unauthorized_teacher_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, plan = _roots(tmp_path)
    _trust_plan(monkeypatch, plan)
    staged = stage_teacher_sources(
        plan,
        teacher_output_root=teacher,
        identity_root=identity,
        staged_root=tmp_path / "staged",
    )
    request = build_distillation_request(
        _config(),
        plan,
        staged_teacher_sources=staged,
    )
    output = tmp_path / "output"
    output.mkdir()
    raw = _result(output, request)
    raw["consumed_teacher_sources"][0]["sha256"] = "9" * 64

    with pytest.raises(
        PhotorealP3DeviceDistillationRunnerError,
        match="unauthorized teacher source bytes",
    ):
        validate_distillation_result(
            raw,
            request=request,
            output_dir=output,
        )


def test_result_rejects_student_artifact_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, plan = _roots(tmp_path)
    _trust_plan(monkeypatch, plan)
    staged = stage_teacher_sources(
        plan,
        teacher_output_root=teacher,
        identity_root=identity,
        staged_root=tmp_path / "staged",
    )
    request = build_distillation_request(
        _config(),
        plan,
        staged_teacher_sources=staged,
    )
    output = tmp_path / "output"
    output.mkdir()
    raw = _result(output, request)
    (output / "student" / "avatar.bin").write_bytes(b"changed")

    with pytest.raises(
        PhotorealP3DeviceDistillationRunnerError,
        match="size/path mismatch|SHA-256 mismatch",
    ):
        validate_distillation_result(
            raw,
            request=request,
            output_dir=output,
        )


def test_result_cannot_self_authorize_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, plan = _roots(tmp_path)
    _trust_plan(monkeypatch, plan)
    staged = stage_teacher_sources(
        plan,
        teacher_output_root=teacher,
        identity_root=identity,
        staged_root=tmp_path / "staged",
    )
    request = build_distillation_request(
        _config(),
        plan,
        staged_teacher_sources=staged,
    )
    output = tmp_path / "output"
    output.mkdir()
    raw = _result(output, request)
    raw["runtime_acceptance_authority"] = True

    with pytest.raises(
        PhotorealP3DeviceDistillationRunnerError,
        match="crossed authority boundary",
    ):
        validate_distillation_result(
            raw,
            request=request,
            output_dir=output,
        )


def test_execution_receipt_rejects_resealed_runtime_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, plan = _roots(tmp_path)
    _trust_plan(monkeypatch, plan)
    staged = stage_teacher_sources(
        plan,
        teacher_output_root=teacher,
        identity_root=identity,
        staged_root=tmp_path / "staged",
    )
    request = build_distillation_request(
        _config(),
        plan,
        staged_teacher_sources=staged,
    )
    output = tmp_path / "output"
    output.mkdir()
    raw = _result(output, request)
    receipt = build_execution_receipt(
        validate_distillation_result(
            raw,
            request=request,
            output_dir=output,
        )
    )
    receipt["runtime_acceptance_authority"] = True
    receipt["p3_device_distillation_execution_receipt_sha256"] = (
        runner._digest(
            receipt,
            omit="p3_device_distillation_execution_receipt_sha256",
        )
    )

    with pytest.raises(
        PhotorealP3DeviceDistillationRunnerError,
        match="runtime_acceptance_authority",
    ):
        validate_execution_receipt(receipt)


def test_boolean_v1_is_rejected() -> None:
    config = _config()
    config["version"] = True
    with pytest.raises(
        PhotorealP3DeviceDistillationRunnerError,
        match="format/version mismatch",
    ):
        validate_distillation_config(config)

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_animation_plan import ANIMATION_REQUIREMENTS
from bodyrig.photoreal_animation_runner import (
    PhotorealAnimationRunnerError,
    build_animation_request,
    validate_animation_config,
    validate_animation_result,
)


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _teacher_root(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "teacher"
    artifact = root / "checkpoint" / "teacher.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"accepted-static-teacher")
    entry = {
        "kind": "checkpoint",
        "relative_path": "checkpoint/teacher.bin",
        "size_bytes": artifact.stat().st_size,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    return root, entry


def _plan(artifact: dict[str, object]) -> dict[str, object]:
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-animation-plan",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "teacher_manifest_sha256": "b" * 64,
        "static_teacher_review_sha256": "c" * 64,
        "review_render_set_sha256": "d" * 64,
        "static_teacher_photoreal_accepted": True,
        "p1_human_acceptance_required_and_verified": True,
        "teacher_artifact_count": 1,
        "teacher_artifacts": [artifact],
        "teacher_artifact_bytes_reverified": True,
        "animation_model_policy": "rig-drives-teacher-does-not-replace-teacher-v1",
        "body_correspondence_policy": "canonical-skeleton-smplx-correspondence-v1",
        "face_control_policy": "explicit-facial-expression-representation-v1",
        "required_validation_dimensions": list(ANIMATION_REQUIREMENTS),
        "required_validation_dimension_count": len(ANIMATION_REQUIREMENTS),
        "animation_adapter_required": True,
        "animation_adapter_selected": False,
        "p2_animation_execution_authorized": True,
        "animated_teacher_acceptance_authority": False,
        "human_animated_visual_acceptance_required": True,
        "p3_device_distillation_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["animation_plan_sha256"] = _digest(value, "animation_plan_sha256")
    return value


def _config() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-animation-config",
        "version": 1,
        "adapter": "test-animation-adapter",
        "revision": "revision-a",
        "representation": "test-animated-teacher",
        "command": ["python", "adapter.py"],
        "timeout_seconds": 3600,
        "supported_validation_dimensions": list(ANIMATION_REQUIREMENTS),
        "body_correspondence_policy": "canonical-skeleton-smplx-correspondence-v1",
        "face_control_policy": "explicit-facial-expression-representation-v1",
    }


def _request(tmp_path: Path) -> tuple[Path, dict[str, object], dict[str, object]]:
    root, artifact = _teacher_root(tmp_path)
    plan = _plan(artifact)
    request = build_animation_request(_config(), plan, teacher_output_root=root)
    return root, plan, request


def _result(output: Path, request: dict[str, object]) -> dict[str, object]:
    artifact = output / "animation" / "clip.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"animated-teacher-output")
    teacher = request["teacher_artifacts"][0]
    return {
        "format": "bodyrig-photoreal-animation-manifest",
        "version": 1,
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "teacher_manifest_sha256": request["teacher_manifest_sha256"],
        "static_teacher_review_sha256": request["static_teacher_review_sha256"],
        "animation_plan_sha256": request["animation_plan_sha256"],
        "adapter": request["adapter"],
        "adapter_revision": request["adapter_revision"],
        "representation": request["representation"],
        "animation_complete": True,
        "consumed_teacher_artifacts": [
            {
                "relative_path": teacher["relative_path"],
                "sha256": teacher["sha256"],
            }
        ],
        "implemented_validation_dimensions": list(ANIMATION_REQUIREMENTS),
        "animation_artifacts": [
            {
                "kind": "animated-teacher",
                "relative_path": "animation/clip.bin",
                "size_bytes": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
        ],
        "animated_teacher_acceptance_authority": False,
        "human_animated_visual_acceptance_required": True,
        "p3_device_distillation_authorized": False,
        "production_activation": False,
    }


def test_animation_request_requires_exact_p2_plan_and_reverified_teacher_bytes(tmp_path: Path) -> None:
    root, plan, request = _request(tmp_path)
    assert request["static_teacher_photoreal_accepted"] is True
    assert request["p2_animation_execution_authorized"] is True
    assert request["required_validation_dimensions"] == list(ANIMATION_REQUIREMENTS)
    assert request["animated_teacher_acceptance_authority"] is False
    assert request["p3_device_distillation_authorized"] is False
    assert request["production_activation"] is False
    assert root.is_dir()
    assert plan["animation_plan_sha256"] == request["animation_plan_sha256"]


def test_animation_config_rejects_incomplete_capability_universe() -> None:
    config = _config()
    config["supported_validation_dimensions"] = list(ANIMATION_REQUIREMENTS[:-1])
    with pytest.raises(PhotorealAnimationRunnerError, match="canonical P2 validation universe"):
        validate_animation_config(config)


def test_animation_config_rejects_boolean_v1() -> None:
    config = _config()
    config["version"] = True
    with pytest.raises(PhotorealAnimationRunnerError, match="numeric v1"):
        validate_animation_config(config)


def test_animation_request_rejects_plan_tamper_even_when_authority_flag_stays_true(tmp_path: Path) -> None:
    root, artifact = _teacher_root(tmp_path)
    plan = _plan(artifact)
    plan["representation_injected"] = "bad"
    with pytest.raises(PhotorealAnimationRunnerError, match="fields must match v1 exactly"):
        build_animation_request(_config(), plan, teacher_output_root=root)


def test_animation_request_rejects_teacher_byte_drift_after_plan(tmp_path: Path) -> None:
    root, artifact = _teacher_root(tmp_path)
    plan = _plan(artifact)
    (root / "checkpoint" / "teacher.bin").write_bytes(b"changed")
    with pytest.raises(PhotorealAnimationRunnerError, match="size drifted|bytes drifted"):
        build_animation_request(_config(), plan, teacher_output_root=root)


def test_animation_result_records_execution_without_granting_p2_acceptance_or_p3(tmp_path: Path) -> None:
    _, _, request = _request(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    result = validate_animation_result(_result(output, request), request=request, output_dir=output)
    assert result["animation_complete"] is True
    assert result["implemented_validation_dimensions"] == list(ANIMATION_REQUIREMENTS)
    assert result["animated_teacher_acceptance_authority"] is False
    assert result["human_animated_visual_acceptance_required"] is True
    assert result["p3_device_distillation_authorized"] is False
    assert result["production_activation"] is False


def test_animation_result_rejects_unauthorized_consumed_teacher_artifact(tmp_path: Path) -> None:
    _, _, request = _request(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    result = _result(output, request)
    result["consumed_teacher_artifacts"][0]["sha256"] = "9" * 64
    with pytest.raises(PhotorealAnimationRunnerError, match="unauthorized teacher artifact bytes"):
        validate_animation_result(result, request=request, output_dir=output)


def test_animation_result_cannot_self_authorize_p3(tmp_path: Path) -> None:
    _, _, request = _request(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    result = _result(output, request)
    result["p3_device_distillation_authorized"] = True
    with pytest.raises(PhotorealAnimationRunnerError, match="prematurely authorized P3"):
        validate_animation_result(result, request=request, output_dir=output)


def test_animation_result_rejects_output_byte_drift(tmp_path: Path) -> None:
    _, _, request = _request(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    result = _result(output, request)
    (output / "animation" / "clip.bin").write_bytes(b"changed-after-manifest")
    with pytest.raises(PhotorealAnimationRunnerError, match="size mismatch|SHA-256 mismatch"):
        validate_animation_result(result, request=request, output_dir=output)

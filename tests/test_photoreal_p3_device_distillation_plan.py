from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

import bodyrig.photoreal_p3_device_distillation_plan as p3
from bodyrig.photoreal_p3_device_distillation_plan import (
    CANDIDATE_STUDENT_REPRESENTATIONS,
    FIDELITY_DELTA_DIMENSIONS,
    PhotorealP3DeviceDistillationPlanError,
    build_p3_device_distillation_plan,
    require_p3_distillation_execution_authority,
    validate_device_target_profile,
    validate_p3_device_distillation_plan,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _roots(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    teacher = tmp_path / "teacher"
    identity = tmp_path / "identity-root"
    checkpoint = teacher / "checkpoint" / "snapshot_4.pth"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"accepted-exavatar-checkpoint")

    records: list[dict[str, object]] = []
    for kind, name, payload in (
        ("shape-param", "shape_param.json", b"shape"),
        ("face-offset", "face_offset.json", b"face"),
        ("joint-offset", "joint_offset.json", b"joint"),
        ("locator-offset", "locator_offset.json", b"locator"),
    ):
        path = identity / "identity" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        records.append(
            {
                "kind": kind,
                "source_relative_path": f"smplx_optimized/{name}",
                "export_relative_path": f"identity/{name}",
                "size_bytes": len(payload),
                "sha256": _sha(payload),
            }
        )

    execution_input: dict[str, object] = {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "teacher_checkpoint": {
            "relative_path": "checkpoint/snapshot_4.pth",
            "size_bytes": checkpoint.stat().st_size,
            "sha256": _sha(checkpoint.read_bytes()),
        },
        "identity_artifacts": records,
    }
    return teacher, identity, execution_input


def _review(execution_input: dict[str, object]) -> dict[str, object]:
    return {
        "performer_id": execution_input["performer_id"],
        "selected_epoch_id": execution_input["selected_epoch_id"],
        "teacher_input_sha256": execution_input["teacher_input_sha256"],
        "p2_animation_plan_sha256": execution_input["p2_animation_plan_sha256"],
        "p2_exavatar_animation_execution_input_sha256": execution_input[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "consumed_checkpoint_sha256": execution_input["teacher_checkpoint"]["sha256"],
        "p2_heldout_animated_human_review_sha256": "4" * 64,
        "human_animated_review_status": "pass",
        "p2_animated_teacher_acceptance_authority": True,
        "p3_device_distillation_authorized": True,
    }


def _profile(model: str = "quest-2") -> dict[str, object]:
    refresh = 72.0
    return {
        "format": p3.PROFILE_FORMAT,
        "version": 1,
        "operator_supplied": True,
        "target_family": "meta-quest",
        "target_model": model,
        "target_runtime": "standalone",
        "target_refresh_hz": refresh,
        "max_frame_time_ms": round(1000.0 / refresh, 6),
        "stereo_rendering_required": True,
        "vr_safe_frame_pacing_required": True,
        "teacher_quality_ceiling_preserved": True,
        "fidelity_delta_reporting_required": True,
        "production_activation": False,
    }


def _trust(
    monkeypatch: pytest.MonkeyPatch,
    review: dict[str, object],
    execution_input: dict[str, object],
) -> None:
    monkeypatch.setattr(
        p3,
        "require_p3_device_distillation_authority",
        lambda value: review,
    )
    monkeypatch.setattr(
        p3,
        "validate_exavatar_animation_execution_input",
        lambda value: execution_input,
    )


def test_p2_human_pass_builds_quest_plan_from_teacher_bytes_not_review_media(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, execution = _roots(tmp_path)
    review = _review(execution)
    _trust(monkeypatch, review, execution)

    plan = build_p3_device_distillation_plan(
        review,
        execution,
        _profile(),
        teacher_output_root=teacher,
        identity_root=identity,
    )
    validated = validate_p3_device_distillation_plan(plan)

    assert validated["target_profile"]["target_model"] == "quest-2"
    assert validated["teacher_source_artifact_count"] == 5
    assert validated["teacher_source_bytes_reverified"] is True
    assert validated["review_media_is_quality_evidence_not_teacher_source"] is True
    assert {item["kind"] for item in validated["teacher_source_artifacts"]} == {
        "teacher-checkpoint",
        "shape-param",
        "face-offset",
        "joint-offset",
        "locator-offset",
    }
    assert all(
        not item["relative_path"].endswith(".mp4")
        for item in validated["teacher_source_artifacts"]
    )
    assert validated["candidate_student_representations"] == list(
        CANDIDATE_STUDENT_REPRESENTATIONS
    )
    assert validated["required_fidelity_delta_dimensions"] == list(
        FIDELITY_DELTA_DIMENSIONS
    )
    assert validated["p3_distillation_execution_authorized"] is True
    assert validated["runtime_acceptance_authority"] is False
    assert validated["production_activation"] is False
    assert require_p3_distillation_execution_authority(validated) == validated


def test_p2_human_fail_cannot_open_p3(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, execution = _roots(tmp_path)
    review = _review(execution)

    def reject(_value: object) -> object:
        raise p3.PhotorealP2HeldoutAnimatedHumanReviewError(
            "P3 device distillation requires an exact human P2 animated-teacher PASS"
        )

    monkeypatch.setattr(p3, "require_p3_device_distillation_authority", reject)
    monkeypatch.setattr(
        p3,
        "validate_exavatar_animation_execution_input",
        lambda value: execution,
    )

    with pytest.raises(
        PhotorealP3DeviceDistillationPlanError,
        match="exact human P2 animated-teacher PASS",
    ):
        build_p3_device_distillation_plan(
            review,
            execution,
            _profile(),
            teacher_output_root=teacher,
            identity_root=identity,
        )


def test_p3_rejects_human_pass_for_different_execution_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, execution = _roots(tmp_path)
    review = _review(execution)
    review["p2_exavatar_animation_execution_input_sha256"] = "9" * 64
    _trust(monkeypatch, review, execution)

    with pytest.raises(
        PhotorealP3DeviceDistillationPlanError,
        match="different ExAvatar execution input",
    ):
        build_p3_device_distillation_plan(
            review,
            execution,
            _profile(),
            teacher_output_root=teacher,
            identity_root=identity,
        )


def test_p3_rejects_checkpoint_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, execution = _roots(tmp_path)
    review = _review(execution)
    _trust(monkeypatch, review, execution)
    (teacher / "checkpoint" / "snapshot_4.pth").write_bytes(b"changed")

    with pytest.raises(
        PhotorealP3DeviceDistillationPlanError,
        match="size/path drifted|bytes drifted",
    ):
        build_p3_device_distillation_plan(
            review,
            execution,
            _profile(),
            teacher_output_root=teacher,
            identity_root=identity,
        )


def test_p3_rejects_identity_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, execution = _roots(tmp_path)
    review = _review(execution)
    _trust(monkeypatch, review, execution)
    (identity / "identity" / "face_offset.json").write_bytes(b"changed")

    with pytest.raises(
        PhotorealP3DeviceDistillationPlanError,
        match="size/path drifted|bytes drifted",
    ):
        build_p3_device_distillation_plan(
            review,
            execution,
            _profile(),
            teacher_output_root=teacher,
            identity_root=identity,
        )


def test_profile_requires_exact_refresh_derived_frame_budget() -> None:
    profile = _profile()
    profile["max_frame_time_ms"] = 10.0
    with pytest.raises(
        PhotorealP3DeviceDistillationPlanError,
        match="1000/target_refresh_hz",
    ):
        validate_device_target_profile(profile)


def test_profile_rejects_boolean_v1() -> None:
    profile = _profile()
    profile["version"] = True
    with pytest.raises(
        PhotorealP3DeviceDistillationPlanError,
        match="format/version mismatch",
    ):
        validate_device_target_profile(profile)


def test_readback_rejects_resealed_teacher_source_policy_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, execution = _roots(tmp_path)
    review = _review(execution)
    _trust(monkeypatch, review, execution)
    plan = build_p3_device_distillation_plan(
        review,
        execution,
        _profile(),
        teacher_output_root=teacher,
        identity_root=identity,
    )
    plan["review_media_is_quality_evidence_not_teacher_source"] = False
    plan["p3_device_distillation_plan_sha256"] = p3._digest(
        plan,
        omit="p3_device_distillation_plan_sha256",
    )

    with pytest.raises(
        PhotorealP3DeviceDistillationPlanError,
        match="review_media_is_quality_evidence_not_teacher_source",
    ):
        validate_p3_device_distillation_plan(plan)


def test_readback_rejects_resealed_representation_universe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, execution = _roots(tmp_path)
    review = _review(execution)
    _trust(monkeypatch, review, execution)
    plan = build_p3_device_distillation_plan(
        review,
        execution,
        _profile(),
        teacher_output_root=teacher,
        identity_root=identity,
    )
    plan["candidate_student_representations"] = ["gaussian-splat-optional"]
    plan["p3_device_distillation_plan_sha256"] = p3._digest(
        plan,
        omit="p3_device_distillation_plan_sha256",
    )

    with pytest.raises(
        PhotorealP3DeviceDistillationPlanError,
        match="candidate universe mismatch",
    ):
        validate_p3_device_distillation_plan(plan)


def test_readback_rejects_resealed_runtime_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher, identity, execution = _roots(tmp_path)
    review = _review(execution)
    _trust(monkeypatch, review, execution)
    plan = build_p3_device_distillation_plan(
        review,
        execution,
        _profile(),
        teacher_output_root=teacher,
        identity_root=identity,
    )
    plan["runtime_acceptance_authority"] = True
    plan["p3_device_distillation_plan_sha256"] = p3._digest(
        plan,
        omit="p3_device_distillation_plan_sha256",
    )

    with pytest.raises(
        PhotorealP3DeviceDistillationPlanError,
        match="runtime_acceptance_authority",
    ):
        validate_p3_device_distillation_plan(plan)

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p1_likeness_review as likeness
import bodyrig.photoreal_p2_animation_plan as p2
from bodyrig.photoreal_p2_animation_plan import (
    PhotorealP2AnimationPlanError,
    build_p2_animation_plan,
    build_p2_animation_plan_files,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _p1_artifacts() -> tuple[dict[str, object], dict[str, object]]:
    manifest: dict[str, object] = {
        "format": likeness.MANIFEST_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "semantic_alignment_sha256": "b" * 64,
        "p1_pairing_sha256": "c" * 64,
        "criterion_count": 2,
        "pairs": [
            {"criterion": "face-front"},
            {"criterion": "full-body-front"},
        ],
        "human_visual_review_required": True,
        "human_visual_review_complete": False,
        "p1_static_teacher_acceptance_authority": False,
        "human_visual_likeness_acceptance": False,
        "p2_animation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    manifest["p1_likeness_review_manifest_sha256"] = likeness._digest(
        manifest,
        omit="p1_likeness_review_manifest_sha256",
    )
    receipt: dict[str, object] = {
        "format": likeness.RECEIPT_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "semantic_alignment_sha256": "b" * 64,
        "p1_pairing_sha256": "c" * 64,
        "p1_likeness_review_manifest_sha256": manifest[
            "p1_likeness_review_manifest_sha256"
        ],
        "criterion_results": [
            {"criterion": "face-front", "decision": "pass"},
            {"criterion": "full-body-front", "decision": "pass"},
        ],
        "reviewed_by": "operator",
        "review_notes": "All P1 criteria passed against held-out evidence.",
        "human_visual_review_required": True,
        "human_visual_review_complete": True,
        "p1_static_teacher_status": "pass",
        "p1_static_teacher_acceptance_authority": True,
        "human_visual_likeness_acceptance": True,
        "p2_animation_authorized": True,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    receipt["p1_likeness_review_sha256"] = likeness._digest(
        receipt,
        omit="p1_likeness_review_sha256",
    )
    return manifest, receipt


def _teacher(tmp_path: Path) -> tuple[dict[str, object], Path]:
    output = tmp_path / "teacher-output"
    checkpoint = output / "checkpoint" / "snapshot_4.pth"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"accepted-static-teacher-checkpoint")
    (output / "teacher-manifest.json").write_text("{}\n", encoding="utf-8")
    teacher: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-manifest",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "adapter": p2.STATIC_TEACHER_ADAPTER,
        "adapter_revision": "d" * 64,
        "upstream_repository": "https://github.com/mks0601/ExAvatar_RELEASE",
        "upstream_commit": "d45268730c779fae4118f1a361cf9ff639bc4d1e",
        "training_complete": True,
        "artifacts": [
            {
                "kind": "checkpoint",
                "relative_path": p2.EXPECTED_CHECKPOINT,
                "size_bytes": checkpoint.stat().st_size,
                "sha256": _sha(checkpoint),
            }
        ],
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "production_activation": False,
    }
    return teacher, output


def test_p2_plan_binds_p1_pass_static_checkpoint_and_exact_upstream_animation_contract(
    tmp_path: Path,
) -> None:
    teacher, output = _teacher(tmp_path)
    manifest, receipt = _p1_artifacts()

    plan = build_p2_animation_plan(teacher, output, manifest, receipt)

    assert plan["p2_animation_build_authorized"] is True
    assert plan["p2_animated_teacher_acceptance_authority"] is False
    assert plan["quest_distillation_authorized"] is False
    assert plan["photoreal_acceptance_authority"] is False
    assert plan["production_activation"] is False
    assert plan["teacher_checkpoint"]["relative_path"] == "checkpoint/snapshot_4.pth"
    assert plan["animation_contract"]["upstream_script"] == "avatar/main/animate.py"
    assert plan["animation_contract"]["test_epoch"] == "4"
    assert plan["animation_contract"]["required_smplx_fields"] == list(
        p2.REQUIRED_SMPLX_FIELDS
    )
    assert plan["animation_contract"]["required_camera_fields"] == list(
        p2.REQUIRED_CAMERA_FIELDS
    )
    assert plan["required_motion_validation_criteria"] == list(
        p2.REQUIRED_MOTION_VALIDATION_CRITERIA
    )
    assert plan["p2_animation_plan_sha256"] == p2._digest(
        plan,
        omit="p2_animation_plan_sha256",
    )


def test_p2_plan_rejects_completed_p1_failure(tmp_path: Path) -> None:
    teacher, output = _teacher(tmp_path)
    manifest, receipt = _p1_artifacts()
    receipt["criterion_results"][0]["decision"] = "fail"
    receipt["p1_static_teacher_status"] = "fail"
    receipt["p1_static_teacher_acceptance_authority"] = False
    receipt["human_visual_likeness_acceptance"] = False
    receipt["p2_animation_authorized"] = False
    receipt["p1_likeness_review_sha256"] = likeness._digest(
        receipt,
        omit="p1_likeness_review_sha256",
    )

    with pytest.raises(PhotorealP2AnimationPlanError, match="all-PASS P1"):
        build_p2_animation_plan(teacher, output, manifest, receipt)


def test_p2_plan_rejects_p1_teacher_provenance_drift(tmp_path: Path) -> None:
    teacher, output = _teacher(tmp_path)
    manifest, receipt = _p1_artifacts()
    teacher["selected_epoch_id"] = "epoch-b"

    with pytest.raises(
        PhotorealP2AnimationPlanError,
        match="P1/static-teacher provenance mismatch: selected_epoch_id",
    ):
        build_p2_animation_plan(teacher, output, manifest, receipt)


def test_p2_plan_rejects_checkpoint_byte_drift(tmp_path: Path) -> None:
    teacher, output = _teacher(tmp_path)
    manifest, receipt = _p1_artifacts()
    (output / "checkpoint" / "snapshot_4.pth").write_bytes(b"tampered")

    with pytest.raises(
        PhotorealP2AnimationPlanError,
        match="checkpoint bytes differ",
    ):
        build_p2_animation_plan(teacher, output, manifest, receipt)


def test_p2_plan_rejects_noncanonical_checkpoint_epoch(tmp_path: Path) -> None:
    teacher, output = _teacher(tmp_path)
    manifest, receipt = _p1_artifacts()
    checkpoint = output / "checkpoint" / "snapshot_4.pth"
    teacher["artifacts"][0]["relative_path"] = "checkpoint/snapshot_3.pth"

    with pytest.raises(
        PhotorealP2AnimationPlanError,
        match="canonical final ExAvatar epoch",
    ):
        build_p2_animation_plan(teacher, output, manifest, receipt)

    assert checkpoint.is_file()


def test_file_plan_uses_runner_workspace_and_reuses_only_exact_canonical_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "teacher-workspace"
    output = workspace / "output"
    output.mkdir(parents=True)
    teacher, fixture_output = _teacher(tmp_path / "fixture")
    checkpoint_source = fixture_output / "checkpoint" / "snapshot_4.pth"
    checkpoint_target = output / "checkpoint" / "snapshot_4.pth"
    checkpoint_target.parent.mkdir()
    checkpoint_target.write_bytes(checkpoint_source.read_bytes())
    (output / "teacher-manifest.json").write_text("{}\n", encoding="utf-8")
    teacher["artifacts"][0]["sha256"] = _sha(checkpoint_target)
    teacher["artifacts"][0]["size_bytes"] = checkpoint_target.stat().st_size

    p1_root = tmp_path / "p1-review"
    p1_root.mkdir()
    manifest, receipt = _p1_artifacts()
    (p1_root / "p1-likeness-review-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "p1-likeness-review.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    config = tmp_path / "config.json"
    teacher_input = tmp_path / "teacher-input.json"
    config.write_text("{}\n", encoding="utf-8")
    teacher_input.write_text("{}\n", encoding="utf-8")
    target = tmp_path / "p2-animation-plan.json"
    captured: dict[str, object] = {}

    def fake_strict(config_path, teacher_input_path, workspace_path):
        captured["workspace"] = Path(workspace_path).resolve()
        return copy.deepcopy(teacher)

    monkeypatch.setattr(p2, "validate_external_teacher_files_strict", fake_strict)

    first = build_p2_animation_plan_files(
        config,
        teacher_input,
        workspace,
        p1_root,
        receipt_path,
        target,
    )
    second = build_p2_animation_plan_files(
        config,
        teacher_input,
        workspace,
        p1_root,
        receipt_path,
        target,
        reuse_existing=True,
    )

    assert first == second
    assert captured["workspace"] == workspace.resolve()
    assert second["p2_animation_build_authorized"] is True


def test_file_plan_reuse_rejects_tampered_existing_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "teacher-workspace"
    output = workspace / "output"
    output.mkdir(parents=True)
    teacher, fixture_output = _teacher(tmp_path / "fixture")
    checkpoint_target = output / "checkpoint" / "snapshot_4.pth"
    checkpoint_target.parent.mkdir()
    checkpoint_target.write_bytes(
        (fixture_output / "checkpoint" / "snapshot_4.pth").read_bytes()
    )
    (output / "teacher-manifest.json").write_text("{}\n", encoding="utf-8")
    teacher["artifacts"][0]["sha256"] = _sha(checkpoint_target)
    teacher["artifacts"][0]["size_bytes"] = checkpoint_target.stat().st_size

    p1_root = tmp_path / "p1-review"
    p1_root.mkdir()
    manifest, receipt = _p1_artifacts()
    (p1_root / "p1-likeness-review-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    target = tmp_path / "plan.json"
    target.write_text('{"tampered":true}\n', encoding="utf-8")

    monkeypatch.setattr(
        p2,
        "validate_external_teacher_files_strict",
        lambda *_args: copy.deepcopy(teacher),
    )

    with pytest.raises(
        PhotorealP2AnimationPlanError,
        match="differs from canonical current state",
    ):
        build_p2_animation_plan_files(
            tmp_path / "config.json",
            tmp_path / "teacher-input.json",
            workspace,
            p1_root,
            receipt_path,
            target,
            reuse_existing=True,
        )

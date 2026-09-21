from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p2_heldout_animated_human_review as review
from bodyrig.photoreal_p2_heldout_animated_human_review import (
    PhotorealP2HeldoutAnimatedHumanReviewError,
    QUALITY_CHECKS,
    build_animated_human_review_pack,
    record_animated_human_review,
    require_p3_device_distillation_authority,
    validate_animated_human_review_pack,
    validate_animated_human_review_receipt,
)
from bodyrig.photoreal_p2_heldout_animated_review_plan import REVIEW_DIMENSIONS


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _plan(video_sha: str, video_size: int) -> dict[str, object]:
    selections = [
        {
            "dimension": dimension,
            "held_out_source_ref": "src-eval",
            "held_out_frame_count": 2,
            "held_out_frame_ids": [10, 11],
            "heldout_evaluation_execution_receipt_sha256": "8" * 64,
            "review_artifact_kind": "heldout-animation-review-video",
            "review_artifact_relative_path": "review/heldout-animation.mp4",
            "review_artifact_size_bytes": video_size,
            "review_artifact_sha256": video_sha,
        }
        for dimension in REVIEW_DIMENSIONS
    ]
    return {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "train_animation_execution_receipt_sha256": "4" * 64,
        "consumed_checkpoint_sha256": "5" * 64,
        "p2_heldout_animated_review_plan_sha256": "6" * 64,
        "selections": selections,
    }


def _workspace(tmp_path: Path) -> tuple[Path, dict[str, object], dict[str, object]]:
    root = tmp_path / "eval"
    video = root / "output" / "review" / "heldout-animation.mp4"
    video.parent.mkdir(parents=True)
    payload = b"heldout-evaluation-video"
    video.write_bytes(payload)
    receipt = {
        "held_out_source_ref": "src-eval",
        "p2_exavatar_heldout_evaluation_execution_receipt_sha256": "8" * 64,
    }
    (root / "heldout-evaluation-execution-receipt.json").write_text(
        json.dumps(receipt) + "\n",
        encoding="utf-8",
    )
    return root, receipt, _plan(_sha(payload), len(payload))


def _trust(
    monkeypatch: pytest.MonkeyPatch,
    plan: dict[str, object],
    receipt: dict[str, object],
) -> None:
    monkeypatch.setattr(
        review,
        "revalidate_heldout_animated_review_plan",
        lambda value, evaluation_workspaces: plan,
    )
    monkeypatch.setattr(
        review,
        "validate_heldout_animated_review_plan",
        lambda value: plan,
    )
    monkeypatch.setattr(
        review,
        "validate_heldout_evaluation_receipt",
        lambda value: receipt,
    )


def _decisions(value: str = "pass") -> dict[str, str]:
    return {item: value for item in REVIEW_DIMENSIONS}


def _quality(value: str = "pass") -> dict[str, str]:
    return {item: value for item in QUALITY_CHECKS}


def test_review_pack_copies_exact_heldout_video_and_stays_non_accepting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, receipt, plan = _workspace(tmp_path)
    _trust(monkeypatch, plan, receipt)
    output = tmp_path / "review"

    manifest = build_animated_human_review_pack(
        plan,
        evaluation_workspaces=[workspace],
        output_root=output,
    )

    assert manifest["review_dimensions"] == list(REVIEW_DIMENSIONS)
    assert manifest["quality_checks"] == list(QUALITY_CHECKS)
    assert manifest["evidence_source_count"] == 1
    assert manifest["dimension_evidence_count"] == 6
    assert manifest["human_animated_review_complete"] is False
    assert manifest["p2_animated_teacher_acceptance_authority"] is False
    assert manifest["p3_device_distillation_authorized"] is False
    assert manifest["production_activation"] is False
    assert (output / "review-index.html").is_file()
    assert (output / "evidence" / "src-eval.mp4").read_bytes() == (
        workspace / "output" / "review" / "heldout-animation.mp4"
    ).read_bytes()


def test_review_pack_detects_copied_video_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, receipt, plan = _workspace(tmp_path)
    _trust(monkeypatch, plan, receipt)
    output = tmp_path / "review"
    build_animated_human_review_pack(
        plan,
        evaluation_workspaces=[workspace],
        output_root=output,
    )
    (output / "evidence" / "src-eval.mp4").write_bytes(b"tampered")

    with pytest.raises(
        PhotorealP2HeldoutAnimatedHumanReviewError,
        match="copied video bytes changed",
    ):
        validate_animated_human_review_pack(output)


def test_all_pass_opens_p3_but_not_production(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, receipt, plan = _workspace(tmp_path)
    _trust(monkeypatch, plan, receipt)
    manifest = build_animated_human_review_pack(
        plan,
        evaluation_workspaces=[workspace],
        output_root=tmp_path / "review",
    )

    result = record_animated_human_review(
        manifest,
        dimension_decisions=_decisions(),
        quality_decisions=_quality(),
        reviewed_by="operator",
        review_notes="Reviewed all HELD-OUT motion evidence.",
        confirm_review_complete=True,
    )

    assert result["human_animated_review_status"] == "pass"
    assert result["animated_teacher_photoreal_accepted"] is True
    assert result["p2_animated_teacher_acceptance_authority"] is True
    assert result["p3_device_distillation_authorized"] is True
    assert result["quest_distillation_authorized"] is True
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False
    assert require_p3_device_distillation_authority(result) == result


def test_one_quality_fail_persists_valid_fail_and_blocks_p3(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, receipt, plan = _workspace(tmp_path)
    _trust(monkeypatch, plan, receipt)
    manifest = build_animated_human_review_pack(
        plan,
        evaluation_workspaces=[workspace],
        output_root=tmp_path / "review",
    )
    quality = _quality()
    quality["temporal_stability"] = "fail"

    result = record_animated_human_review(
        manifest,
        dimension_decisions=_decisions(),
        quality_decisions=quality,
        reviewed_by="operator",
        review_notes="Temporal instability observed.",
        confirm_review_complete=True,
    )

    assert result["human_animated_review_status"] == "fail"
    assert result["p2_animated_teacher_acceptance_authority"] is False
    assert result["p3_device_distillation_authorized"] is False
    with pytest.raises(
        PhotorealP2HeldoutAnimatedHumanReviewError,
        match="requires an exact human P2 animated-teacher PASS",
    ):
        require_p3_device_distillation_authority(result)


def test_review_requires_explicit_completion_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, receipt, plan = _workspace(tmp_path)
    _trust(monkeypatch, plan, receipt)
    manifest = build_animated_human_review_pack(
        plan,
        evaluation_workspaces=[workspace],
        output_root=tmp_path / "review",
    )

    with pytest.raises(
        PhotorealP2HeldoutAnimatedHumanReviewError,
        match="explicit human P2 animated review completion confirmation",
    ):
        record_animated_human_review(
            manifest,
            dimension_decisions=_decisions(),
            quality_decisions=_quality(),
            reviewed_by="operator",
            review_notes="Reviewed.",
            confirm_review_complete=False,
        )


def test_review_requires_every_dimension_and_quality_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, receipt, plan = _workspace(tmp_path)
    _trust(monkeypatch, plan, receipt)
    manifest = build_animated_human_review_pack(
        plan,
        evaluation_workspaces=[workspace],
        output_root=tmp_path / "review",
    )
    decisions = _decisions()
    decisions.pop(REVIEW_DIMENSIONS[0])

    with pytest.raises(
        PhotorealP2HeldoutAnimatedHumanReviewError,
        match="every required item exactly once",
    ):
        record_animated_human_review(
            manifest,
            dimension_decisions=decisions,
            quality_decisions=_quality(),
            reviewed_by="operator",
            review_notes="Incomplete.",
            confirm_review_complete=True,
        )


def test_resealed_receipt_cannot_claim_pass_against_failed_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, receipt, plan = _workspace(tmp_path)
    _trust(monkeypatch, plan, receipt)
    manifest = build_animated_human_review_pack(
        plan,
        evaluation_workspaces=[workspace],
        output_root=tmp_path / "review",
    )
    result = record_animated_human_review(
        manifest,
        dimension_decisions=_decisions(),
        quality_decisions=_quality(),
        reviewed_by="operator",
        review_notes="Reviewed.",
        confirm_review_complete=True,
    )
    result["quality_results"][0]["decision"] = "fail"
    result["p2_heldout_animated_human_review_sha256"] = review._digest(
        result,
        omit="p2_heldout_animated_human_review_sha256",
    )

    with pytest.raises(
        PhotorealP2HeldoutAnimatedHumanReviewError,
        match="status does not match detailed decisions",
    ):
        validate_animated_human_review_receipt(result)


def test_boolean_v1_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, receipt, plan = _workspace(tmp_path)
    _trust(monkeypatch, plan, receipt)
    manifest = build_animated_human_review_pack(
        plan,
        evaluation_workspaces=[workspace],
        output_root=tmp_path / "review",
    )
    result = record_animated_human_review(
        manifest,
        dimension_decisions=_decisions(),
        quality_decisions=_quality(),
        reviewed_by="operator",
        review_notes="Reviewed.",
        confirm_review_complete=True,
    )
    result["version"] = True
    result["p2_heldout_animated_human_review_sha256"] = review._digest(
        result,
        omit="p2_heldout_animated_human_review_sha256",
    )

    with pytest.raises(
        PhotorealP2HeldoutAnimatedHumanReviewError,
        match="format/version mismatch",
    ):
        validate_animated_human_review_receipt(result)

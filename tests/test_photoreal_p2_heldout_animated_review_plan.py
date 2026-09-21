from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p2_heldout_animated_review_plan as review
from bodyrig.photoreal_p2_heldout_animated_review_plan import (
    PhotorealP2HeldoutAnimatedReviewPlanError,
    REVIEW_DIMENSIONS,
    build_heldout_animated_review_plan,
    revalidate_heldout_animated_review_plan,
    validate_heldout_animated_review_plan,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _workspace(
    root: Path,
    source_ref: str,
    *,
    performer_id: str = "42",
    checkpoint_sha: str = "a" * 64,
) -> tuple[Path, dict[str, object]]:
    root.mkdir(parents=True)
    video = root / "output" / "review" / "heldout-animation.mp4"
    video.parent.mkdir(parents=True)
    payload = f"heldout-{source_ref}".encode()
    video.write_bytes(payload)
    receipt = {
        "performer_id": performer_id,
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "train_animation_execution_receipt_sha256": "4" * 64,
        "consumed_checkpoint_sha256": checkpoint_sha,
        "held_out_source_ref": source_ref,
        "held_out_frame_count": 2,
        "held_out_frame_ids": [10, 11],
        "evaluation_artifacts": [
            {
                "kind": "heldout-animation-review-video",
                "relative_path": "review/heldout-animation.mp4",
                "size_bytes": len(payload),
                "sha256": _sha(payload),
            }
        ],
        "p2_exavatar_heldout_evaluation_execution_receipt_sha256": (
            "5" if source_ref == "src-eval-a" else "6"
        )
        * 64,
    }
    (root / "heldout-evaluation-execution-receipt.json").write_text(
        json.dumps(receipt) + "\n",
        encoding="utf-8",
    )
    return root, receipt


def _selection(a: str = "src-eval-a", b: str = "src-eval-b") -> dict[str, object]:
    refs = [a, a, b, b, a, b]
    return {
        "format": review.SELECTION_FORMAT,
        "version": 1,
        "reviewer": "operator",
        "operator_supplied": True,
        "selections": [
            {"dimension": dimension, "held_out_source_ref": ref}
            for dimension, ref in zip(REVIEW_DIMENSIONS, refs, strict=True)
        ],
    }


def _trust_receipts(
    monkeypatch: pytest.MonkeyPatch,
    by_ref: dict[str, dict[str, object]],
) -> None:
    monkeypatch.setattr(
        review,
        "validate_heldout_evaluation_receipt",
        lambda value: by_ref[value["held_out_source_ref"]],
    )


def test_review_plan_binds_each_dimension_to_exact_heldout_video(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wa, ra = _workspace(tmp_path / "a", "src-eval-a")
    wb, rb = _workspace(tmp_path / "b", "src-eval-b")
    _trust_receipts(monkeypatch, {"src-eval-a": ra, "src-eval-b": rb})

    plan = build_heldout_animated_review_plan(
        _selection(),
        evaluation_workspaces=[wa, wb],
    )

    assert plan["review_dimensions"] == list(REVIEW_DIMENSIONS)
    assert plan["selection_count"] == 6
    assert plan["evidence_source_count"] == 2
    assert plan["held_out_evaluation_only"] is True
    assert plan["evaluation_artifact_bytes_reverified"] is True
    assert plan["human_animated_review_complete"] is False
    assert plan["p2_animated_teacher_acceptance_authority"] is False
    assert plan["quest_distillation_authorized"] is False
    assert plan["production_activation"] is False
    assert {item["held_out_source_ref"] for item in plan["selections"]} == {
        "src-eval-a",
        "src-eval-b",
    }


def test_review_plan_rejects_duplicate_dimension(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wa, ra = _workspace(tmp_path / "a", "src-eval-a")
    _trust_receipts(monkeypatch, {"src-eval-a": ra})
    selection = _selection("src-eval-a", "src-eval-a")
    selection["selections"][-1]["dimension"] = REVIEW_DIMENSIONS[0]

    with pytest.raises(
        PhotorealP2HeldoutAnimatedReviewPlanError,
        match="repeats a dimension|dimension universe",
    ):
        build_heldout_animated_review_plan(
            selection,
            evaluation_workspaces=[wa],
        )


def test_review_plan_rejects_unavailable_selected_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wa, ra = _workspace(tmp_path / "a", "src-eval-a")
    _trust_receipts(monkeypatch, {"src-eval-a": ra})

    with pytest.raises(
        PhotorealP2HeldoutAnimatedReviewPlanError,
        match="unavailable evaluation evidence",
    ):
        build_heldout_animated_review_plan(
            _selection(),
            evaluation_workspaces=[wa],
        )


def test_review_plan_rejects_cross_teacher_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wa, ra = _workspace(tmp_path / "a", "src-eval-a")
    wb, rb = _workspace(tmp_path / "b", "src-eval-b", performer_id="43")
    _trust_receipts(monkeypatch, {"src-eval-a": ra, "src-eval-b": rb})

    with pytest.raises(
        PhotorealP2HeldoutAnimatedReviewPlanError,
        match="lineage mismatch: performer_id",
    ):
        build_heldout_animated_review_plan(
            _selection(),
            evaluation_workspaces=[wa, wb],
        )


def test_review_plan_rejects_video_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wa, ra = _workspace(tmp_path / "a", "src-eval-a")
    _trust_receipts(monkeypatch, {"src-eval-a": ra})
    (wa / "output" / "review" / "heldout-animation.mp4").write_bytes(b"changed")

    with pytest.raises(
        PhotorealP2HeldoutAnimatedReviewPlanError,
        match="size/path drifted|bytes drifted",
    ):
        build_heldout_animated_review_plan(
            _selection("src-eval-a", "src-eval-a"),
            evaluation_workspaces=[wa],
        )


def test_resealed_review_plan_cannot_self_authorize_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wa, ra = _workspace(tmp_path / "a", "src-eval-a")
    _trust_receipts(monkeypatch, {"src-eval-a": ra})
    plan = build_heldout_animated_review_plan(
        _selection("src-eval-a", "src-eval-a"),
        evaluation_workspaces=[wa],
    )
    plan["p2_animated_teacher_acceptance_authority"] = True
    plan["p2_heldout_animated_review_plan_sha256"] = review._digest(
        plan,
        omit="p2_heldout_animated_review_plan_sha256",
    )

    with pytest.raises(
        PhotorealP2HeldoutAnimatedReviewPlanError,
        match="authority mismatch: p2_animated_teacher_acceptance_authority",
    ):
        validate_heldout_animated_review_plan(plan)


def test_strict_revalidation_catches_current_video_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wa, ra = _workspace(tmp_path / "a", "src-eval-a")
    _trust_receipts(monkeypatch, {"src-eval-a": ra})
    plan = build_heldout_animated_review_plan(
        _selection("src-eval-a", "src-eval-a"),
        evaluation_workspaces=[wa],
    )
    (wa / "output" / "review" / "heldout-animation.mp4").write_bytes(b"drifted")

    with pytest.raises(
        PhotorealP2HeldoutAnimatedReviewPlanError,
        match="size/path drifted|bytes drifted",
    ):
        revalidate_heldout_animated_review_plan(
            copy.deepcopy(plan),
            evaluation_workspaces=[wa],
        )

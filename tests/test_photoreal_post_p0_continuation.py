from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_post_p0_continuation import (
    PhotorealPostP0ContinuationError,
    advance_post_p0_teacher,
)
from bodyrig.photoreal_teacher_authority import validate_teacher_input_document
from bodyrig.photoreal_teacher_input_p0_root import resolve_authorized_p0_root


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "review-tools" / "VERIFY_PHYSICAL_P0_READY.ps1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source(key: str, group: str) -> dict[str, object]:
    return {
        "kind": "video",
        "source_id": key,
        "group_id": group,
        "path": key.split(":", 2)[-1],
        "information_score": 100.0,
        "projection": "flat",
        "stereo_layout": "mono",
        "width": 3840,
        "height": 2160,
        "duration_seconds": 120.0,
        "frame_rate": 30.0,
        "performer_count": 1,
        "source_binding": "scene-performer",
    }


def _observation(
    *,
    source: str,
    group: str,
    split: str,
    frame: str,
) -> dict[str, object]:
    return {
        "source_key": source,
        "source_sha256": "a" * 64 if split == "train" else "b" * 64,
        "split": split,
        "group_id": group,
        "kind": "video",
        "timestamp_seconds": 1.0,
        "eye": "mono",
        "projection": "flat",
        "frame_sha256": frame * 64,
        "perceptual_hash": "0123456789abcdef" if split == "train" else "fedcba9876543210",
        "width": 3840,
        "height": 2160,
        "view_bin": "front",
        "face_visibility": 0.95,
        "full_body_visibility": 0.92,
        "person_fraction": 0.8,
        "sharpness": 0.9,
        "motion": 0.1,
        "occlusion": 0.05,
        "identity_measurement_status": "available",
        "identity_similarity": 0.96,
        "target_identity_verified": True,
        "identity_authority": "calibrated-identity-bank-v1",
        "eligible_for_teacher": True,
        "coverage": ["face-front", "full-body-front"],
    }


def _build_p0(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "p0-run"
    root.mkdir()
    revision = "a" * 40

    train_key = "scene:t:E:/train.mp4"
    eval_key = "scene:e:E:/eval.mp4"
    plan = {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": [_source(train_key, "scene:t")],
        "evaluation": [_source(eval_key, "scene:e")],
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    receipt = {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "sources": [
            {
                "kind": "video",
                "source_key": train_key,
                "resolved_path": r"C:\media\train.mp4",
                "size_bytes": 100,
                "sha256": "a" * 64,
            },
            {
                "kind": "video",
                "source_key": eval_key,
                "resolved_path": r"C:\media\eval.mp4",
                "size_bytes": 200,
                "sha256": "b" * 64,
            },
        ],
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    frame_index = {
        "format": "bodyrig-photoreal-frame-index",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "analyzer_model_set_sha256": "c" * 64,
        "identity_bank_sha256": "d" * 64,
        "identity_calibration_sha256": "e" * 64,
        "held_out_view_coverage_required": ["face-front", "full-body-front"],
        "observations": [
            _observation(source=train_key, group="scene:t", split="train", frame="1"),
            _observation(source=eval_key, group="scene:e", split="evaluation", frame="2"),
        ],
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }

    plan_path = root / "dataset-plan.json"
    receipt_path = root / "source-receipt.json"
    frame_index_path = root / "frame-index.json"
    _write_json(plan_path, plan)
    _write_json(receipt_path, receipt)
    _write_json(frame_index_path, frame_index)

    status_path = root / "p0-status.json"
    status = {
        "format": "bodyrig-photoreal-p0-status",
        "version": 1,
        "bodyrig_revision": revision,
        "performer_id": "42",
        "status": "teacher-training-authorized",
        "teacher_training_authorized": True,
        "blockers": [],
        "human_visual_acceptance_required": True,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "outputs": {
            "dataset_plan": str(plan_path.resolve()),
            "source_receipt": str(receipt_path.resolve()),
            "frame_index": str(frame_index_path.resolve()),
        },
    }
    _write_json(status_path, status)

    summary_path = tmp_path / "performer-42-summary.json"
    summary = {
        "format": "bodyrig-photoreal-v2-overnight-summary",
        "version": 1,
        "performer_id": "42",
        "output_root": str(root.resolve()),
        "status": "completed",
        "exit_code": 0,
        "p0_status": str(status_path.resolve()),
        "p0_status_sha256": _sha256(status_path),
        "bodyrig_revision": revision,
        "teacher_training_authorized": True,
        "human_visual_acceptance_required": True,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    _write_json(summary_path, summary)

    physical_path = root / "P0_PHYSICAL_VERIFICATION.json"
    physical = {
        "format": "bodyrig-photoreal-p0-physical-verification",
        "version": 1,
        "performer_id": "42",
        "exact_bodyrig_revision": revision,
        "overnight_summary": str(summary_path.resolve()),
        "overnight_summary_sha256": _sha256(summary_path),
        "p0_status": str(status_path.resolve()),
        "p0_status_sha256": _sha256(status_path),
        "physical_p0_verified": True,
        "teacher_training_authorized": True,
        "human_visual_acceptance_required": True,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    _write_json(physical_path, physical)

    readiness_path = root / "P0_DOWNSTREAM_READINESS.json"
    readiness = {
        "format": "bodyrig-photoreal-p0-downstream-readiness",
        "version": 1,
        "performer_id": "42",
        "exact_bodyrig_revision": revision,
        "verifier_bodyrig_revision": "f" * 40,
        "verifier_script_path": "review-tools/VERIFY_PHYSICAL_P0_READY.ps1",
        "verifier_script_sha256": _sha256(VERIFIER),
        "verifier_software_qualification_complete": True,
        "physical_verification": str(physical_path.resolve()),
        "physical_verification_sha256": _sha256(physical_path),
        "overnight_summary": str(summary_path.resolve()),
        "overnight_summary_sha256": _sha256(summary_path),
        "p0_status": str(status_path.resolve()),
        "p0_status_sha256": _sha256(status_path),
        "software_qualification_complete": True,
        "physical_p0_verified": True,
        "teacher_training_authorized": True,
        "downstream_teacher_flow_ready": True,
        "human_visual_acceptance_required": True,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    _write_json(readiness_path, readiness)
    return root, readiness_path


def test_authorized_p0_root_can_be_validated_before_epoch_selection(tmp_path: Path) -> None:
    root, _readiness = _build_p0(tmp_path)

    status, status_path, plan_path, receipt_path, frame_index_path = resolve_authorized_p0_root(root)

    assert status["teacher_training_authorized"] is True
    assert status_path == (root / "p0-status.json").resolve()
    assert plan_path == (root / "dataset-plan.json").resolve()
    assert receipt_path == (root / "source-receipt.json").resolve()
    assert frame_index_path == (root / "frame-index.json").resolve()


def test_post_p0_continuation_stops_at_explicit_human_review(tmp_path: Path) -> None:
    root, readiness = _build_p0(tmp_path)
    work = tmp_path / "teacher-work"

    result = advance_post_p0_teacher(
        p0_root=root,
        readiness_path=readiness,
        work_root=work,
        expected_performer_id="42",
    )

    assert result["state"] == "human-appearance-epoch-review-required"
    assert result["human_review_complete"] is False
    assert result["teacher_input_ready"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False
    assert {item["split"] for item in result["candidate_source_groups"]} == {"train", "evaluation"}
    assert (work / "appearance-epoch-plan.json").is_file()
    assert (work / "appearance-epoch-review-handoff.json").is_file()
    assert (work / "appearance-epoch-review-template.json").is_file()
    assert not (work / "appearance-epoch-human-review.json").exists()
    assert not (work / "teacher-input.json").exists()


def test_post_p0_continuation_reaches_strict_teacher_input_after_human_review(tmp_path: Path) -> None:
    root, readiness = _build_p0(tmp_path)
    work = tmp_path / "teacher-work"

    result = advance_post_p0_teacher(
        p0_root=root,
        readiness_path=readiness,
        work_root=work,
        expected_performer_id="42",
        selected_epoch_id="epoch-42-a",
        selected_source_group_ids=["scene:t", "scene:e"],
        reviewed_by="operator",
        review_notes="Reviewed train and held-out evaluation source groups for one coherent appearance epoch.",
        approve_human_review=True,
    )

    assert result["state"] == "teacher-input-ready"
    assert result["human_review_complete"] is True
    assert result["teacher_input_ready"] is True
    assert result["teacher_training_authorized"] is True
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False

    teacher_input_path = Path(result["teacher_input"])
    teacher_input = json.loads(teacher_input_path.read_text(encoding="utf-8"))
    validated = validate_teacher_input_document(teacher_input)
    assert validated["performer_id"] == "42"
    assert validated["evaluation_bytes_excluded_from_teacher_request"] is True
    assert validated["human_visual_acceptance_required"] is True

    replay = advance_post_p0_teacher(
        p0_root=root,
        readiness_path=readiness,
        work_root=work,
        expected_performer_id="42",
    )
    assert replay["state"] == "teacher-input-ready"
    assert replay["teacher_input"] == result["teacher_input"]


def test_post_p0_continuation_rejects_tampered_canonical_artifact(tmp_path: Path) -> None:
    root, readiness = _build_p0(tmp_path)
    work = tmp_path / "teacher-work"
    first = advance_post_p0_teacher(
        p0_root=root,
        readiness_path=readiness,
        work_root=work,
        expected_performer_id="42",
    )
    assert first["state"] == "human-appearance-epoch-review-required"

    plan_path = work / "appearance-epoch-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["performer_id"] = "99"
    _write_json(plan_path, plan)

    with pytest.raises(PhotorealPostP0ContinuationError, match="canonical continuation state"):
        advance_post_p0_teacher(
            p0_root=root,
            readiness_path=readiness,
            work_root=work,
            expected_performer_id="42",
        )


def test_post_p0_continuation_rejects_readiness_outside_exact_p0_root(tmp_path: Path) -> None:
    root, readiness = _build_p0(tmp_path)
    moved = tmp_path / "legacy-shared-readiness.json"
    moved.write_bytes(readiness.read_bytes())
    readiness.unlink()

    with pytest.raises(PhotorealPostP0ContinuationError, match="exact P0 output root"):
        advance_post_p0_teacher(
            p0_root=root,
            readiness_path=moved,
            work_root=tmp_path / "teacher-work",
            expected_performer_id="42",
        )


def test_post_p0_continuation_rejects_boolean_summary_exit_code(tmp_path: Path) -> None:
    root, readiness = _build_p0(tmp_path)
    value = json.loads(readiness.read_text(encoding="utf-8"))
    summary_path = Path(value["overnight_summary"])
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["exit_code"] = False
    _write_json(summary_path, summary)
    value["overnight_summary_sha256"] = _sha256(summary_path)
    _write_json(readiness, value)

    with pytest.raises(PhotorealPostP0ContinuationError, match="completed P0 success"):
        advance_post_p0_teacher(
            p0_root=root,
            readiness_path=readiness,
            work_root=tmp_path / "teacher-work",
            expected_performer_id="42",
        )

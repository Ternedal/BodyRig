from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_static_teacher_review import (
    CHECKS,
    PhotorealStaticTeacherReviewError,
    finalize_static_teacher_review,
)


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _write_review_bytes(tmp_path: Path) -> tuple[Path, Path, str, str]:
    teacher_root = tmp_path / "teacher"
    reference_root = tmp_path / "materialized"
    render_path = teacher_root / "review" / "neutral-pose" / "25.png"
    reference_path = reference_root / "references" / f"{'c' * 64}.png"
    render_path.parent.mkdir(parents=True)
    reference_path.parent.mkdir(parents=True)
    render_path.write_bytes(b"exact-teacher-render")
    reference_path.write_bytes(b"exact-held-out-reference")
    return (
        teacher_root,
        reference_root,
        hashlib.sha256(render_path.read_bytes()).hexdigest(),
        hashlib.sha256(reference_path.read_bytes()).hexdigest(),
    )


def _render_set(render_sha: str) -> dict[str, object]:
    renders = []
    for index in range(50):
        renders.append({
            "relative_path": f"review/neutral-pose/{index}.png",
            "size_bytes": 20,
            "sha256": render_sha if index == 25 else format(index % 16, "x") * 64,
            "camera": {"orbit_index": index},
            "semantic_view_label": None,
            "semantic_view_authority": False,
            "human_semantic_view_mapping_required": True,
        })
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-review-render-set",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "teacher_manifest_sha256": "b" * 64,
        "adapter": "exavatar-benchmark",
        "upstream_repository": "https://github.com/mks0601/ExAvatar_RELEASE",
        "upstream_commit": "d45268730c779fae4118f1a361cf9ff639bc4d1e",
        "camera_calibration_source": "avatar/main/get_neutral_pose.py",
        "camera_calibration_formula": "azim=pi+2*pi*i/50;elev=-pi/6;view_num=50",
        "render_count": 50,
        "renders": renders,
        "render_bytes_verified": True,
        "camera_geometry_authority": True,
        "semantic_view_authority": False,
        "human_semantic_view_mapping_required": True,
        "held_out_reference_binding_present": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["review_render_set_sha256"] = _digest(value, "review_render_set_sha256")
    return value


def _mapping(render_set: dict[str, object], render_sha: str) -> dict[str, object]:
    mappings = []
    for coverage in ("face-front", "full-body-front"):
        mappings.append({
            "coverage": coverage,
            "render_orbit_index": 25,
            "render_relative_path": "review/neutral-pose/25.png",
            "render_sha256": render_sha,
            "render_camera": {"orbit_index": 25},
            "reference_observation_id": "c" * 64,
            "reference_source_key": "scene:eval:E:/eval.mp4",
            "reference_source_resolved_path": r"\\stash\VR_E\eval.mp4",
            "reference_source_sha256": "d" * 64,
            "reference_frame_sha256": "e" * 64,
            "reference_timestamp_seconds": 2.0,
            "reference_eye": "mono",
            "reference_view_bin": "front",
            "reference_coverage": ["face-front", "full-body-front"],
            "reference_bytes_materialized": False,
            "reference_frame_hash_verified": False,
        })
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-review-mapping",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "review_render_set_sha256": render_set["review_render_set_sha256"],
        "held_out_reference_catalog_sha256": "f" * 64,
        "reviewer": "mapping-operator",
        "operator_supplied": True,
        "mapping_count": 2,
        "mappings": mappings,
        "semantic_view_mapping_complete": True,
        "semantic_view_authority": "human-operator-mapping-v1",
        "reference_selection_complete": True,
        "reference_selection_authority": "human-operator-selection-v1",
        "reference_bytes_materialized": False,
        "reference_frame_hashes_verified": False,
        "likeness_review_complete": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["review_mapping_sha256"] = _digest(value, "review_mapping_sha256")
    return value


def _materialization(mapping: dict[str, object], png_sha: str) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-reference-frame-materialization-receipt",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "review_mapping_sha256": mapping["review_mapping_sha256"],
        "held_out_reference_catalog_sha256": "f" * 64,
        "adapter": "bodyrig-reference-frame-materializer-v1",
        "revision": "1" * 64,
        "source_count": 1,
        "sample_count": 1,
        "materialized_references": [{
            "observation_id": "c" * 64,
            "source_key": "scene:eval:E:/eval.mp4",
            "expected_frame_sha256": "e" * 64,
            "observed_frame_sha256": "e" * 64,
            "timestamp_seconds": 2.0,
            "eye": "mono",
            "coverages": ["face-front", "full-body-front"],
            "source_hash_verified": True,
            "frame_hash_verified": True,
            "png_relative_path": f"references/{'c' * 64}.png",
            "png_size_bytes": 24,
            "png_sha256": png_sha,
        }],
        "all_source_hashes_verified": True,
        "all_frame_hashes_verified": True,
        "decode_semantics": "opencv-bgr-array-v1",
        "frame_hash_semantics": "sha256(shape-ascii-newline+contiguous-bgr-bytes)",
        "teacher_process_disclosure": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _human_input(*, outcome: str = "pass") -> dict[str, object]:
    check_outcome = "pass" if outcome == "pass" else "fail"
    return {
        "format": "bodyrig-photoreal-static-teacher-human-review-input",
        "version": 1,
        "reviewer": "operator",
        "operator_supplied": True,
        "coverage_reviews": [
            {"coverage": "face-front", "outcome": outcome},
            {"coverage": "full-body-front", "outcome": outcome},
        ],
        "checklist": {key: check_outcome for key in sorted(CHECKS)},
        "overall_decision": outcome,
        "quality_note": "Reviewed exact static teacher against exact held-out references.",
    }


def _inputs(tmp_path: Path) -> tuple[dict[str, object], dict[str, object], dict[str, object], Path, Path]:
    teacher_root, reference_root, render_sha, png_sha = _write_review_bytes(tmp_path)
    render_set = _render_set(render_sha)
    mapping = _mapping(render_set, render_sha)
    materialization = _materialization(mapping, png_sha)
    return render_set, mapping, materialization, teacher_root, reference_root


def test_static_teacher_human_pass_grants_p1_acceptance_but_not_production(tmp_path: Path) -> None:
    render_set, mapping, materialization, teacher_root, reference_root = _inputs(tmp_path)
    result = finalize_static_teacher_review(
        render_set,
        mapping,
        materialization,
        _human_input(outcome="pass"),
        teacher_output_root=teacher_root,
        reference_output_root=reference_root,
        materialization_receipt_sha256="9" * 64,
    )
    assert result["human_review_complete"] is True
    assert result["human_review_outcome"] == "pass"
    assert result["human_review_pass"] is True
    assert result["static_teacher_photoreal_accepted"] is True
    assert result["photoreal_acceptance_authority"] is True
    assert result["p2_animation_work_authorized"] is True
    assert result["production_activation"] is False


def test_static_teacher_human_fail_is_valid_persistent_rejection_without_acceptance(tmp_path: Path) -> None:
    render_set, mapping, materialization, teacher_root, reference_root = _inputs(tmp_path)
    result = finalize_static_teacher_review(
        render_set,
        mapping,
        materialization,
        _human_input(outcome="fail"),
        teacher_output_root=teacher_root,
        reference_output_root=reference_root,
        materialization_receipt_sha256="9" * 64,
    )
    assert result["human_review_complete"] is True
    assert result["human_review_outcome"] == "fail"
    assert result["human_review_pass"] is False
    assert result["static_teacher_photoreal_accepted"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["p2_animation_work_authorized"] is False
    assert result["production_activation"] is False


def test_static_teacher_review_rejects_contradictory_overall_pass(tmp_path: Path) -> None:
    render_set, mapping, materialization, teacher_root, reference_root = _inputs(tmp_path)
    review = _human_input(outcome="pass")
    review["checklist"]["eyes_source_consistent"] = "fail"
    with pytest.raises(PhotorealStaticTeacherReviewError, match="contradicts detailed outcomes"):
        finalize_static_teacher_review(
            render_set, mapping, materialization, review,
            teacher_output_root=teacher_root,
            reference_output_root=reference_root,
            materialization_receipt_sha256="9" * 64,
        )


def test_static_teacher_review_rejects_teacher_render_byte_drift(tmp_path: Path) -> None:
    render_set, mapping, materialization, teacher_root, reference_root = _inputs(tmp_path)
    (teacher_root / "review" / "neutral-pose" / "25.png").write_bytes(b"changed")
    with pytest.raises(PhotorealStaticTeacherReviewError, match="teacher render bytes drifted"):
        finalize_static_teacher_review(
            render_set, mapping, materialization, _human_input(),
            teacher_output_root=teacher_root,
            reference_output_root=reference_root,
            materialization_receipt_sha256="9" * 64,
        )


def test_static_teacher_review_rejects_reference_png_byte_drift(tmp_path: Path) -> None:
    render_set, mapping, materialization, teacher_root, reference_root = _inputs(tmp_path)
    (reference_root / "references" / f"{'c' * 64}.png").write_bytes(b"changed")
    with pytest.raises(PhotorealStaticTeacherReviewError, match="reference PNG bytes drifted"):
        finalize_static_teacher_review(
            render_set, mapping, materialization, _human_input(),
            teacher_output_root=teacher_root,
            reference_output_root=reference_root,
            materialization_receipt_sha256="9" * 64,
        )


def test_static_teacher_review_requires_exact_coverage_universe(tmp_path: Path) -> None:
    render_set, mapping, materialization, teacher_root, reference_root = _inputs(tmp_path)
    review = _human_input()
    review["coverage_reviews"].pop()
    with pytest.raises(PhotorealStaticTeacherReviewError, match="semantic-view universe exactly"):
        finalize_static_teacher_review(
            render_set, mapping, materialization, review,
            teacher_output_root=teacher_root,
            reference_output_root=reference_root,
            materialization_receipt_sha256="9" * 64,
        )

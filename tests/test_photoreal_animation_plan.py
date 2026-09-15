from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_animation_plan import (
    ANIMATION_REQUIREMENTS,
    PhotorealAnimationPlanError,
    build_animation_plan,
)
from bodyrig.photoreal_static_teacher_review import CHECKS


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


def _teacher(tmp_path: Path) -> tuple[Path, dict[str, object], str]:
    root = tmp_path / "teacher-output"
    checkpoint = root / "checkpoint" / "teacher.bin"
    render = root / "review" / "neutral-pose" / "0.png"
    checkpoint.parent.mkdir(parents=True)
    render.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"exact-static-teacher-checkpoint")
    render.write_bytes(b"exact-reviewed-render")
    artifacts = [
        {
            "kind": "checkpoint",
            "relative_path": "checkpoint/teacher.bin",
            "size_bytes": checkpoint.stat().st_size,
            "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        },
        {
            "kind": "neutral-pose-render",
            "relative_path": "review/neutral-pose/0.png",
            "size_bytes": render.stat().st_size,
            "sha256": hashlib.sha256(render.read_bytes()).hexdigest(),
        },
    ]
    manifest: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-manifest",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "adapter": "test-teacher",
        "adapter_revision": "revision-a",
        "upstream_repository": "https://example.invalid/teacher",
        "upstream_commit": "1" * 40,
        "training_complete": True,
        "consumed_training_source_keys": ["scene:train"],
        "consumed_training_observations": [
            {
                "source_key": "scene:train",
                "frame_sha256": "2" * 64,
                "timestamp_seconds": 1.0,
                "eye": "mono",
            }
        ],
        "artifacts": artifacts,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "production_activation": False,
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    return root, manifest, hashlib.sha256(manifest_bytes).hexdigest()


def _render_set(manifest_sha: str) -> dict[str, object]:
    renders = [
        {
            "relative_path": f"review/neutral-pose/{index}.png",
            "size_bytes": 1,
            "sha256": format(index % 16, "x") * 64,
            "camera": {"orbit_index": index},
            "semantic_view_label": None,
            "semantic_view_authority": False,
            "human_semantic_view_mapping_required": True,
        }
        for index in range(50)
    ]
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-review-render-set",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "teacher_manifest_sha256": manifest_sha,
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


def _accepted_review(render_set_sha: str) -> dict[str, object]:
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-static-teacher-human-review",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "review_render_set_sha256": render_set_sha,
        "review_mapping_sha256": "b" * 64,
        "held_out_reference_catalog_sha256": "c" * 64,
        "materialization_receipt_sha256": "d" * 64,
        "reviewer": "operator",
        "reviewed_utc": "2026-09-15T08:00:00Z",
        "operator_supplied": True,
        "comparison_count": 1,
        "comparisons": [
            {
                "coverage": "face-front",
                "teacher_render_orbit_index": 0,
                "teacher_render_relative_path": "review/neutral-pose/0.png",
                "teacher_render_sha256": "e" * 64,
                "reference_observation_id": "f" * 64,
                "reference_png_relative_path": "references/ref.png",
                "reference_png_sha256": "3" * 64,
                "reference_frame_sha256": "4" * 64,
                "human_outcome": "pass",
            }
        ],
        "checklist": {key: "pass" for key in sorted(CHECKS)},
        "quality_note": "Exact static teacher passed human likeness review.",
        "human_review_complete": True,
        "human_review_outcome": "pass",
        "human_review_pass": True,
        "static_teacher_photoreal_accepted": True,
        "photoreal_acceptance_authority": True,
        "p2_animation_work_authorized": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["static_teacher_review_sha256"] = _digest(value, "static_teacher_review_sha256")
    return value


def _inputs(tmp_path: Path) -> tuple[Path, dict[str, object], str, dict[str, object], dict[str, object]]:
    root, manifest, manifest_sha = _teacher(tmp_path)
    render_set = _render_set(manifest_sha)
    review = _accepted_review(str(render_set["review_render_set_sha256"]))
    return root, manifest, manifest_sha, render_set, review


def test_p1_pass_opens_p2_work_but_not_p2_acceptance_or_p3(tmp_path: Path) -> None:
    root, manifest, manifest_sha, render_set, review = _inputs(tmp_path)
    result = build_animation_plan(
        review,
        render_set,
        manifest,
        teacher_output_root=root,
        teacher_manifest_sha256=manifest_sha,
    )
    assert result["static_teacher_photoreal_accepted"] is True
    assert result["p1_human_acceptance_required_and_verified"] is True
    assert result["teacher_artifact_bytes_reverified"] is True
    assert result["p2_animation_execution_authorized"] is True
    assert result["animated_teacher_acceptance_authority"] is False
    assert result["p3_device_distillation_authorized"] is False
    assert result["production_activation"] is False
    assert tuple(result["required_validation_dimensions"]) == ANIMATION_REQUIREMENTS


def test_p1_fail_cannot_open_p2_even_when_receipt_is_well_formed(tmp_path: Path) -> None:
    root, manifest, manifest_sha, render_set, review = _inputs(tmp_path)
    failed = copy.deepcopy(review)
    failed["comparisons"][0]["human_outcome"] = "fail"
    failed["checklist"] = {key: "fail" for key in sorted(CHECKS)}
    failed["human_review_outcome"] = "fail"
    for key in (
        "human_review_pass",
        "static_teacher_photoreal_accepted",
        "photoreal_acceptance_authority",
        "p2_animation_work_authorized",
    ):
        failed[key] = False
    failed["static_teacher_review_sha256"] = _digest(failed, "static_teacher_review_sha256")
    with pytest.raises(PhotorealAnimationPlanError, match="P2 animation work requires"):
        build_animation_plan(
            failed,
            render_set,
            manifest,
            teacher_output_root=root,
            teacher_manifest_sha256=manifest_sha,
        )


def test_animation_plan_rejects_static_review_digest_tamper(tmp_path: Path) -> None:
    root, manifest, manifest_sha, render_set, review = _inputs(tmp_path)
    review["quality_note"] = "tampered after review"
    with pytest.raises(PhotorealAnimationPlanError, match="does not match receipt content"):
        build_animation_plan(
            review,
            render_set,
            manifest,
            teacher_output_root=root,
            teacher_manifest_sha256=manifest_sha,
        )


def test_animation_plan_rejects_teacher_artifact_byte_drift(tmp_path: Path) -> None:
    root, manifest, manifest_sha, render_set, review = _inputs(tmp_path)
    (root / "checkpoint" / "teacher.bin").write_bytes(b"changed-teacher")
    with pytest.raises(PhotorealAnimationPlanError, match="artifact size mismatch|artifact SHA-256 mismatch"):
        build_animation_plan(
            review,
            render_set,
            manifest,
            teacher_output_root=root,
            teacher_manifest_sha256=manifest_sha,
        )


def test_animation_plan_rejects_different_teacher_manifest_lineage(tmp_path: Path) -> None:
    root, manifest, manifest_sha, render_set, review = _inputs(tmp_path)
    changed = copy.deepcopy(render_set)
    changed["teacher_manifest_sha256"] = "9" * 64
    changed["review_render_set_sha256"] = _digest(changed, "review_render_set_sha256")
    review["review_render_set_sha256"] = changed["review_render_set_sha256"]
    review["static_teacher_review_sha256"] = _digest(review, "static_teacher_review_sha256")
    with pytest.raises(PhotorealAnimationPlanError, match="different teacher manifest bytes"):
        build_animation_plan(
            review,
            changed,
            manifest,
            teacher_output_root=root,
            teacher_manifest_sha256=manifest_sha,
        )


def test_animation_plan_rejects_boolean_render_set_version_even_if_resealed(tmp_path: Path) -> None:
    root, manifest, manifest_sha, render_set, review = _inputs(tmp_path)
    changed = copy.deepcopy(render_set)
    changed["version"] = True
    changed["review_render_set_sha256"] = _digest(changed, "review_render_set_sha256")
    review["review_render_set_sha256"] = changed["review_render_set_sha256"]
    review["static_teacher_review_sha256"] = _digest(review, "static_teacher_review_sha256")
    with pytest.raises(PhotorealAnimationPlanError, match="numeric v1"):
        build_animation_plan(
            review,
            changed,
            manifest,
            teacher_output_root=root,
            teacher_manifest_sha256=manifest_sha,
        )

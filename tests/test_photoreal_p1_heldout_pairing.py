from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_p1_heldout_pairing import (
    PhotorealP1HeldoutPairingError,
    build_p1_pairing_handoff,
    record_p1_pairing,
)


def _digest(value: dict[str, object], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(*, key: str, group: str, path: str, sha: str) -> dict[str, object]:
    return {
        "source_key": key,
        "group_id": group,
        "kind": "video",
        "resolved_path": path,
        "size_bytes": 123456,
        "sha256": sha * 64,
        "information_score": 100.0,
        "width": 3840,
        "height": 2160,
        "projection": "flat",
        "stereo_layout": "mono",
    }


def _observation(*, key: str, group: str, split: str, sha: str) -> dict[str, object]:
    return {
        "source_key": key,
        "group_id": group,
        "split": split,
        "frame_sha256": sha * 64,
        "timestamp_seconds": 1.25,
        "eye": "mono",
        "view_bin": "front",
        "coverage": ["face-front", "full-body-front"],
    }


def _teacher_input() -> dict[str, object]:
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-input",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "selected_epoch_id": "epoch-a",
        "appearance_epoch_selection_sha256": "a" * 64,
        "identity_bank_sha256": "b" * 64,
        "identity_calibration_sha256": "c" * 64,
        "analyzer_model_set_sha256": "d" * 64,
        "training_sources": [
            _source(
                key="scene:train:E:/train.mp4",
                group="scene:train",
                path=r"\\stash\VR_E\train.mp4",
                sha="e",
            )
        ],
        "held_out_evaluation_sources": [
            _source(
                key="scene:eval:E:/eval.mp4",
                group="scene:eval",
                path=r"\\stash\VR_E\eval.mp4",
                sha="f",
            )
        ],
        "training_observations": [
            _observation(
                key="scene:train:E:/train.mp4",
                group="scene:train",
                split="train",
                sha="1",
            )
        ],
        "held_out_evaluation_observations": [
            _observation(
                key="scene:eval:E:/eval.mp4",
                group="scene:eval",
                split="evaluation",
                sha="2",
            )
        ],
        "held_out_view_coverage_required": ["face-front", "full-body-front"],
        "held_out_view_coverage_observed": ["face-front", "full-body-front"],
        "held_out_view_coverage_missing": [],
        "training_source_count": 1,
        "held_out_evaluation_source_count": 1,
        "training_observation_count": 1,
        "held_out_evaluation_observation_count": 1,
        "evaluation_bytes_excluded_from_teacher_request": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["teacher_input_sha256"] = _digest(value)
    return value


def _semantic_alignment(teacher: dict[str, object]) -> dict[str, object]:
    labels = [
        ("front", 25),
        ("front-left-three-quarter", 31),
        ("left-profile", 37),
        ("rear", 0),
        ("right-profile", 12),
        ("front-right-three-quarter", 19),
    ]
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-p1-semantic-camera-alignment",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": teacher["teacher_input_sha256"],
        "teacher_manifest_file_sha256": "3" * 64,
        "camera_manifest_sha256": "4" * 64,
        "camera_manifest_file_sha256": "5" * 64,
        "semantic_alignment_handoff_sha256": "6" * 64,
        "alignments": [
            {
                "semantic_label": label,
                "index": index,
                "render_relative_path": f"review/neutral-pose/{index}.png",
                "render_sha256": f"{index % 10}" * 64,
                "upstream_azimuth_radians": float(index),
                "upstream_azimuth_degrees": float(index),
                "normalized_azimuth_degrees": float(index),
                "elevation_radians": -0.5,
                "elevation_degrees": -30.0,
            }
            for label, index in labels
        ],
        "reviewed_by": "operator",
        "review_notes": "Human semantic orientation review.",
        "human_semantic_alignment_required": True,
        "human_semantic_alignment_complete": True,
        "semantic_camera_alignment_authority": True,
        "human_visual_likeness_acceptance": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    value["semantic_alignment_sha256"] = _digest(value)
    return value


def _review_pack(tmp_path: Path, teacher: dict[str, object]) -> tuple[dict[str, object], Path, str]:
    root = tmp_path / "appearance-review"
    frames = root / "frames"
    frames.mkdir(parents=True)
    eval_png = frames / "eval.png"
    eval_png.write_bytes(b"held-out-reference")
    html = root / "review-index.html"
    html.write_text("<html>appearance review</html>\n", encoding="utf-8")

    source_key = teacher["held_out_evaluation_observations"][0]["source_key"]
    source_ref = hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:20]
    frame_id = "review-frame-eval"
    manifest: dict[str, object] = {
        "format": "bodyrig-photoreal-appearance-epoch-visual-review-manifest",
        "version": 1,
        "bodyrig_revision": "7" * 40,
        "performer_id": "42",
        "dataset_plan_sha256": "8" * 64,
        "source_receipt_sha256": "9" * 64,
        "frame_index_sha256": "a" * 64,
        "group_count": 2,
        "train_group_count": 1,
        "evaluation_group_count": 1,
        "eligible_observation_count": 2,
        "groups": [
            {
                "group_id": "scene:train",
                "split": "train",
                "observation_count": 1,
                "view_bins": ["front"],
                "frames": [],
            },
            {
                "group_id": "scene:eval",
                "split": "evaluation",
                "observation_count": 1,
                "view_bins": ["front"],
                "frames": [
                    {
                        "frame_id": frame_id,
                        "source_ref": source_ref,
                        "frame_sha256": "2" * 64,
                        "timestamp_seconds": 1.25,
                        "eye": "mono",
                        "view_bin": "front",
                        "coverage": ["face-front", "full-body-front"],
                        "relative_path": "frames/eval.png",
                        "staged_png_sha256": _file_sha(eval_png),
                        "width": 3840,
                        "height": 2160,
                    }
                ],
            },
        ],
        "source_paths_disclosed": False,
        "source_media_rehash_performed": False,
        "exact_p0_frame_hashes_reproduced": True,
        "review_only": True,
        "human_appearance_epoch_review_required": True,
        "teacher_input_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "review_index_sha256": _file_sha(html),
    }
    manifest_path = root / "appearance-epoch-visual-review-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest, root, frame_id


def _selections(frame_id: str) -> dict[str, dict[str, str]]:
    return {
        "face-front": {"semantic_label": "front", "frame_id": frame_id},
        "full-body-front": {"semantic_label": "front", "frame_id": frame_id},
    }


def test_pairing_handoff_uses_only_selected_teacher_input_held_out_universe(tmp_path: Path) -> None:
    teacher = _teacher_input()
    semantic = _semantic_alignment(teacher)
    manifest, root, frame_id = _review_pack(tmp_path, teacher)

    handoff = build_p1_pairing_handoff(teacher, semantic, manifest, root)

    assert handoff["required_p1_criteria"] == ["face-front", "full-body-front"]
    assert len(handoff["candidate_held_out_frames"]) == 1
    assert handoff["candidate_held_out_frames"][0]["frame_id"] == frame_id
    assert handoff["human_pairing_required"] is True
    assert handoff["human_pairing_complete"] is False
    assert handoff["held_out_pairing_authority"] is False
    assert handoff["human_visual_likeness_acceptance"] is False
    assert handoff["photoreal_acceptance_authority"] is False
    assert handoff["production_activation"] is False


def test_pairing_receipt_grants_pairing_authority_only(tmp_path: Path) -> None:
    teacher = _teacher_input()
    semantic = _semantic_alignment(teacher)
    manifest, root, frame_id = _review_pack(tmp_path, teacher)
    handoff = build_p1_pairing_handoff(teacher, semantic, manifest, root)

    receipt = record_p1_pairing(
        handoff,
        selections=_selections(frame_id),
        reviewed_by="operator",
        review_notes="Reviewed teacher/reference orientation pairing; no likeness decision was made.",
        approve_human_review=True,
    )

    assert len(receipt["pairs"]) == 2
    assert receipt["human_pairing_complete"] is True
    assert receipt["held_out_pairing_authority"] is True
    assert receipt["human_visual_likeness_acceptance"] is False
    assert receipt["photoreal_acceptance_authority"] is False
    assert receipt["production_activation"] is False


def test_pairing_rejects_frame_without_required_coverage(tmp_path: Path) -> None:
    teacher = _teacher_input()
    semantic = _semantic_alignment(teacher)
    manifest, root, frame_id = _review_pack(tmp_path, teacher)
    handoff = build_p1_pairing_handoff(teacher, semantic, manifest, root)
    handoff["candidate_held_out_frames"][0]["coverage"] = ["face-front"]
    handoff["p1_pairing_handoff_sha256"] = _digest(
        handoff,
        omit="p1_pairing_handoff_sha256",
    )

    with pytest.raises(PhotorealP1HeldoutPairingError, match="does not cover criterion"):
        record_p1_pairing(
            handoff,
            selections=_selections(frame_id),
            reviewed_by="operator",
            review_notes="Bad full-body pairing should fail.",
            approve_human_review=True,
        )


def test_pairing_rejects_semantic_label_outside_criterion_family(tmp_path: Path) -> None:
    teacher = _teacher_input()
    semantic = _semantic_alignment(teacher)
    manifest, root, frame_id = _review_pack(tmp_path, teacher)
    handoff = build_p1_pairing_handoff(teacher, semantic, manifest, root)
    selections = _selections(frame_id)
    selections["face-front"]["semantic_label"] = "left-profile"

    with pytest.raises(PhotorealP1HeldoutPairingError, match="not valid for criterion"):
        record_p1_pairing(
            handoff,
            selections=selections,
            reviewed_by="operator",
            review_notes="Wrong semantic family should fail.",
            approve_human_review=True,
        )


def test_pairing_handoff_rejects_tampered_held_out_png(tmp_path: Path) -> None:
    teacher = _teacher_input()
    semantic = _semantic_alignment(teacher)
    manifest, root, _frame_id = _review_pack(tmp_path, teacher)
    (root / "frames" / "eval.png").write_bytes(b"tampered")

    with pytest.raises(PhotorealP1HeldoutPairingError, match="PNG bytes changed"):
        build_p1_pairing_handoff(teacher, semantic, manifest, root)


def test_pairing_handoff_rejects_held_out_frame_not_in_selected_teacher_epoch(tmp_path: Path) -> None:
    teacher = _teacher_input()
    semantic = _semantic_alignment(teacher)
    manifest, root, _frame_id = _review_pack(tmp_path, teacher)
    manifest = copy.deepcopy(manifest)
    manifest["groups"][1]["frames"][0]["frame_sha256"] = "9" * 64

    with pytest.raises(PhotorealP1HeldoutPairingError, match="complete selected held-out teacher universe"):
        build_p1_pairing_handoff(teacher, semantic, manifest, root)

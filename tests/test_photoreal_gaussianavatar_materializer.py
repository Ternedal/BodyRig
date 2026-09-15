from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bodyrig import photoreal_gaussianavatar_materializer as materializer
from bodyrig.photoreal_teacher_comparison_plan import build_teacher_comparison_plan


def _teacher_input() -> dict[str, object]:
    source = "scene:best:E:/best.mp4"
    observations = [
        {
            "source_key": source,
            "group_id": "best",
            "split": "train",
            "frame_sha256": str(index + 1) * 64,
            "timestamp_seconds": float(index + 1),
            "eye": "mono",
            "view_bin": "front",
            "coverage": ["face-front", "full-body-front"],
        }
        for index in range(3)
    ]
    return {
        "format": "bodyrig-photoreal-teacher-input",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "d" * 64,
        "training_sources": [{
            "source_key": source,
            "group_id": "best",
            "kind": "video",
            "resolved_path": r"\\stash\VR_E\best.mp4",
            "size_bytes": 1000,
            "sha256": "a" * 64,
            "information_score": 100.0,
            "width": 3840,
            "height": 2160,
            "projection": "flat",
            "stereo_layout": "mono",
        }],
        "training_observations": observations,
        "training_source_count": 1,
        "training_observation_count": 3,
        "held_out_evaluation_sources": [{"source_key": "scene:eval:F:/secret.mp4"}],
        "held_out_evaluation_observations": [{"frame_sha256": "e" * 64}],
        "held_out_view_coverage_missing": [],
        "evaluation_bytes_excluded_from_teacher_request": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _plan() -> dict[str, object]:
    return build_teacher_comparison_plan(_teacher_input())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_materializer_plan_boundary_contains_train_path_but_no_eval_path() -> None:
    plan = _plan()
    comparison_sha, source_key, source_sha, resolved, observations = materializer._validate_plan(plan)
    assert comparison_sha == plan["comparison_plan_sha256"]
    assert source_key == "scene:best:E:/best.mp4"
    assert source_sha == "a" * 64
    assert resolved.endswith("best.mp4")
    assert len(observations) == 3
    encoded = str(plan)
    assert "secret.mp4" not in encoded
    assert "e" * 64 not in encoded


def test_materializer_rejects_comparison_digest_tamper() -> None:
    plan = _plan()
    plan["selected_source_sha256"] = "f" * 64
    with pytest.raises(materializer.PhotorealGaussianAvatarMaterializerError, match="digest mismatch"):
        materializer._validate_plan(plan)


def test_materializer_rejects_eval_path_serialization_even_with_recomputed_digest() -> None:
    plan = _plan()
    plan["evaluation_source_paths_serialized"] = True
    plan["comparison_plan_sha256"] = materializer._digest(plan, omit="comparison_plan_sha256")
    with pytest.raises(materializer.PhotorealGaussianAvatarMaterializerError, match="serialized evaluation paths"):
        materializer._validate_plan(plan)


def test_receipt_requires_exact_female_smpl_and_staged_png_bytes(tmp_path: Path) -> None:
    plan = _plan()
    comparison_sha, source_key, source_sha, _resolved, observations = materializer._validate_plan(plan)
    request = materializer._build_request(
        plan,
        comparison_sha=comparison_sha,
        source_key=source_key,
        source_sha=source_sha,
        linux_source="/mnt/e/best.mp4",
        observations=observations,
    )
    frames = []
    for index, observation in enumerate(observations):
        path = tmp_path / "train" / "images" / f"{index:08d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"png-{index}".encode())
        frames.append({
            "gaussianavatar_frame_index": index,
            "source_key": source_key,
            "source_frame_sha256": observation["frame_sha256"],
            "timestamp_seconds": observation["timestamp_seconds"],
            "eye": "mono",
            "relative_path": f"train/images/{index:08d}.png",
            "staged_png_sha256": _sha(path),
            "width": 1920,
            "height": 1080,
        })
    receipt = {
        "format": materializer.RECEIPT_FORMAT,
        "version": 1,
        "benchmark": "gaussianavatar",
        "upstream_commit": materializer.UPSTREAM_COMMIT,
        "comparison_plan_sha256": comparison_sha,
        "teacher_input_sha256": request["teacher_input_sha256"],
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "smpl_gender": "female",
        "smpl_type": "smpl",
        "source_key": source_key,
        "source_sha256": source_sha,
        "frame_count": len(frames),
        "frames": frames,
        "exact_p0_frame_hashes_reproduced": True,
        "held_out_evaluation_disclosed": False,
        "original_video_copied": False,
        "independent_preprocessing_required": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "production_activation": False,
    }
    assert materializer._validate_receipt(receipt, request=request, output=tmp_path)["smpl_gender"] == "female"

    changed = copy.deepcopy(receipt)
    changed["smpl_gender"] = "neutral"
    with pytest.raises(materializer.PhotorealGaussianAvatarMaterializerError, match="geometry-prior mismatch"):
        materializer._validate_receipt(changed, request=request, output=tmp_path)

    (tmp_path / "train" / "images" / "00000000.png").write_bytes(b"changed")
    with pytest.raises(materializer.PhotorealGaussianAvatarMaterializerError, match="staged PNG bytes mismatch"):
        materializer._validate_receipt(receipt, request=request, output=tmp_path)

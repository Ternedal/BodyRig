from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_preprocess as preprocess


def _dataset(tmp_path: Path, *, spatial: bool) -> Path:
    dataset = tmp_path / "dataset" / "bodyrig-42"
    dataset.mkdir(parents=True)
    (dataset / "bodyrig-source-map.json").write_text(
        json.dumps({
            "format": "bodyrig-photoreal-exavatar-source-map",
            "normalization_action": (
                "exact-authorized-deprojection" if spatial else "preserve-flat-mono-video"
            ),
            "frames": [{"exavatar_frame_index": i} for i in range(2)],
        }), encoding="utf-8",
    )
    optimized = dataset / "smplx_optimized"
    for directory in ("smplx_params", "meshes", "renders"):
        (optimized / directory).mkdir(parents=True)
    for index in range(2):
        (optimized / "smplx_params" / f"{index}.json").write_text(
            json.dumps({"trans": [float(index), 0, 1]}), encoding="utf-8"
        )
        (optimized / "meshes" / f"{index}_smplx.ply").write_bytes(b"ply placeholder" + bytes([index]))
        (optimized / "renders" / f"{index}_smplx.jpg").write_bytes(b"jpg placeholder" + bytes([index]))
    (dataset / "smplx_optimized.mp4").write_bytes(b"video placeholder")
    return dataset


def test_preserve_spatial_fit_copies_without_temporal_filtering(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path, spatial=True)
    optimized = dataset / "smplx_optimized"
    inputs = {
        path: path.read_bytes()
        for directory in ("smplx_params", "meshes", "renders")
        for path in (optimized / directory).iterdir()
    }
    policy_path = preprocess._preserve_spatial_fit_without_temporal_smoothing(
        dataset, [0, 1]
    )

    assert policy_path is not None
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert policy["action"] == "preserve-optimized-without-temporal-smoothing"
    assert policy["teacher_training_authority"] is False
    assert policy["human_visual_fit_review_required"] is True
    assert policy["frame_count"] == 2
    assert policy["optimized_video_sha256"] == hashlib.sha256(
        (dataset / "smplx_optimized.mp4").read_bytes()
    ).hexdigest()
    assert (dataset / "smplx_optimized_smoothed.mp4").read_bytes() == (
        dataset / "smplx_optimized.mp4"
    ).read_bytes()
    for path, content in inputs.items():
        assert path.read_bytes() == content
        subdir = {
            "smplx_params": "smplx_params_smoothed",
            "meshes": "meshes_smoothed",
            "renders": "renders_smoothed",
        }[path.parent.name]
        assert (optimized / subdir / path.name).read_bytes() == content


def test_flat_video_keeps_upstream_smoothing_policy(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path, spatial=False)
    assert preprocess._preserve_spatial_fit_without_temporal_smoothing(
        dataset, [0, 1]
    ) is None
    assert not (dataset / "smplx_optimized_smoothed.mp4").exists()
    assert not (dataset / "smplx_optimized" / "smplx_params_smoothed").exists()


def test_spatial_fit_preservation_fails_closed_on_missing_mesh(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path, spatial=True)
    (dataset / "smplx_optimized" / "meshes" / "1_smplx.ply").unlink()

    with pytest.raises(preprocess.PhotorealExAvatarPreprocessError, match="missing"):
        preprocess._preserve_spatial_fit_without_temporal_smoothing(dataset, [0, 1])
    assert not (dataset / "smplx_optimized" / "meshes_smoothed").exists()
    assert not (dataset / "smplx_optimized_smoothed.mp4").exists()

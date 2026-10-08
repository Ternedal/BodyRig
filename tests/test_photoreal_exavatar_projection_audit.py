from __future__ import annotations

import json
from pathlib import Path
import struct

import pytest

from bodyrig import photoreal_exavatar_fit_diagnostic as diagnostic


def _mesh(path: Path, *, center_x: float = 0.0, binary: bool = True) -> None:
    vertices = [
        (center_x + (i % 20 - 10) * 0.01, (i // 20 - 10) * 0.01, 1.0)
        for i in range(400)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        header = (
            b"ply\nformat binary_little_endian 1.0\n"
            b"element vertex 400\nproperty float x\nproperty float y\n"
            b"property float z\nend_header\n"
        )
        with path.open("wb") as stream:
            stream.write(header)
            for xyz in vertices:
                stream.write(struct.pack("<fff", *xyz))
    else:
        with path.open("w", encoding="ascii") as stream:
            stream.write(
                "ply\nformat ascii 1.0\nelement vertex 400\n"
                "property float x\nproperty float y\nproperty float z\nend_header\n"
            )
            for xyz in vertices:
                stream.write("%f %f %f\n" % xyz)


def _dataset(tmp_path: Path, *, smooth_x: float = 0.0) -> Path:
    dataset = tmp_path / "dataset" / "bodyrig-42"
    for directory in ("frames", "cam_params", "keypoints_whole_body"):
        (dataset / directory).mkdir(parents=True)
    (dataset / "frame_list_all.txt").write_text("75\n", encoding="utf-8")
    (dataset / "frames" / "75.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
        + struct.pack(">II", 100, 100)
    )
    (dataset / "cam_params" / "75.json").write_text(
        json.dumps({"R": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    "t": [0, 0, 0], "focal": [100, 100], "princpt": [50, 50]}),
        encoding="utf-8",
    )
    points = [[(i % 5 - 2) * 5 + 50, (i // 5 - 2) * 5 + 50, 0.9]
              for i in range(17)] + [[0, 0, 0] for _ in range(116)]
    (dataset / "keypoints_whole_body" / "75.json").write_text(
        json.dumps(points), encoding="utf-8",
    )
    optimized = dataset / "smplx_optimized"
    _mesh(optimized / "meshes" / "75_smplx.ply", binary=False)
    _mesh(optimized / "meshes_smoothed" / "75_smplx.ply", center_x=smooth_x)
    return dataset


def test_binary_and_ascii_ply_projection(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    frame = diagnostic.diagnose_frame(dataset, 75)
    assert frame["valid_body_keypoints"] == 17
    assert frame["metrics"]["optimized"]["mesh_vertex_count"] == 400
    assert frame["metrics"]["smoothed"]["forward_mesh_vertices"] == 400
    assert frame["metrics"]["optimized"]["mesh_keypoint_bbox_iou"] > 0.5


def test_report_detects_displaced_mesh_and_does_not_authorize_training(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path, smooth_x=0.8)
    result = diagnostic.analyze_dataset(dataset, (75, 76))
    assert result["training_authority"] is False
    assert result["human_fit_review_accepted"] is False
    assert result["diagnostic_error_count"] == 0
    assert "Frame not in dataset index" == result["frames"][1]["error"]
    frame = result["frames"][0]
    assert frame["metrics"]["smoothed"]["mesh_keypoint_bbox_iou"] == 0.0
    assert frame["metrics"]["smoothed"]["center_dx_normalized"] > 0.7
    assert frame["metrics"]["optimized"]["mesh_keypoint_bbox_iou"] > 0.5


def test_reports_missing_mesh_without_fabricating_alignment(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    (dataset / "smplx_optimized" / "meshes_smoothed" / "75_smplx.ply").unlink()
    result = diagnostic.analyze_dataset(dataset, (75,))
    assert result["diagnostic_error_count"] == 1
    assert "Missing mesh" in result["frames"][0]["error"]


def test_rejects_malformed_png_header(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    (dataset / "frames" / "75.png").write_bytes(b"not a png")
    with pytest.raises(diagnostic.FitDiagnosticError, match="Invalid PNG"):
        diagnostic.diagnose_frame(dataset, 75)

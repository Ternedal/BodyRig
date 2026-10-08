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
    assert result["diagnostic_error_count"] == 1
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


def test_optimized_only_does_not_touch_corrupted_smoothing(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    (dataset / "smplx_optimized" / "meshes_smoothed" / "75_smplx.ply").unlink()
    report = diagnostic.analyze_dataset(dataset, (75,), include_smoothed=False)
    assert report["diagnostic_error_count"] == 0
    assert report["analyzed_frame_count"] == 1
    assert "optimized" in report["frames"][0]["metrics"]
    assert "smoothed" not in report["frames"][0]["metrics"]
    assert report["training_authority"] is False
    assert report["human_fit_review_accepted"] is False
    assert report["metric_is_quality_acceptance"] is False
    assert report["camera_translation_authority"] is False


def test_all_frames_index_is_bound_to_existing_dataset(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    assert diagnostic._indexed_frames(dataset) == (75,)
    index = dataset / "frame_list_all.txt"
    index.write_text("75\n75\n", encoding="utf-8")
    with pytest.raises(diagnostic.FitDiagnosticError, match="repeated"):
        diagnostic._indexed_frames(dataset)
    index.write_text("75\nnot-an-index\n", encoding="utf-8")
    with pytest.raises(diagnostic.FitDiagnosticError, match="non-decimal"):
        diagnostic._indexed_frames(dataset)


def test_tiers_do_not_turn_iou_into_training_acceptance() -> None:
    assert diagnostic._triage_frame({
        "frame": 1, "valid_body_keypoints": 17, "body_bbox_touches_frame": False,
        "anatomical_evidence": {"full_body_fit_evidence": True},
        "metrics": {"optimized": {
            "mesh_keypoint_bbox_iou": 0.94,
            "center_dx_normalized": 0.01,
            "center_dy_normalized": 0.02,
            "height_ratio_to_keypoint_bbox": 1.1,
        }},
    }) == "geometry_proxy_promising_review_required"
    assert diagnostic._triage_frame({
        "frame": 1, "valid_body_keypoints": 17, "body_bbox_touches_frame": False,
        "anatomical_evidence": {"full_body_fit_evidence": True},
        "metrics": {"optimized": {
            "mesh_keypoint_bbox_iou": 0.05,
            "center_dx_normalized": 0.4,
            "center_dy_normalized": 0.5,
            "height_ratio_to_keypoint_bbox": 2.5,
        }},
    }) == "suspect_optimized_geometry"
    assert diagnostic._triage_frame({
        "frame": 1, "valid_body_keypoints": 8,
        "anatomical_evidence": {"full_body_fit_evidence": False},
        "metrics": {},
    }) == "partial_or_insufficient_anatomical_evidence"
    assert diagnostic._triage_frame({"frame": 1, "error": "missing"}) == "unreadable_evidence"


def test_all_frame_cli_outputs_report_outside_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    dataset = _dataset(tmp_path)
    (dataset / "smplx_optimized" / "meshes_smoothed" / "75_smplx.ply").unlink()
    output = tmp_path / "audit.json"
    monkeypatch.setattr(
        "sys.argv", [
            "diagnostic", "--dataset", str(dataset), "--all-frames",
            "--optimized-only", "--output", str(output),
        ],
    )
    assert diagnostic.main() == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["include_smoothed"] is False
    assert [row["frame"] for row in result["frames"]] == [75]
    assert result["training_authority"] is False
    assert result["priority_review_frames"][0]["frame"] == 75
    assert "Audited: 1 frames" in capsys.readouterr().out


def test_anatomical_evidence_requires_torso_and_upper_lower_limb_pairs() -> None:
    rows = [[50.0, 50.0, 0.9] for _ in range(17)]
    points, evidence = diagnostic._body_keypoint_evidence(rows, 100, 100)
    assert len(points) == 17
    assert evidence["scope"] == "full_body_evidence"
    assert evidence["full_body_fit_evidence"] is True
    assert evidence["bilateral_shoulders"] is True
    assert evidence["bilateral_hips"] is True

    # Raw count can still be high while all ankle evidence is absent.
    rows[15][2] = 0.0
    rows[16][2] = 0.0
    _, evidence = diagnostic._body_keypoint_evidence(rows, 100, 100)
    assert evidence["scope"] == "upper_body_evidence"
    assert evidence["full_body_fit_evidence"] is False
    assert evidence["groups"]["legs"]["visible"] == 2


def test_diagnostic_records_anatomical_scope_without_training_authority(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    result = diagnostic.analyze_dataset(dataset, (75,), include_smoothed=False)
    frame = result["frames"][0]
    assert frame["anatomical_evidence"]["scope"] == "full_body_evidence"
    assert result["anatomical_scope_counts"]["full_body_evidence"] == 1
    assert result["anatomical_evidence_is_training_acceptance"] is False
    assert result["training_authority"] is False

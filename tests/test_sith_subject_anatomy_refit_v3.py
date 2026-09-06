from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_subject_anatomy_refit_v3 import (  # noqa: E402
    METHOD_V3,
    NORMAL_ALIGNMENT_AUTHORITY,
    NORMAL_SAMPLE_METHOD,
    build_receipt_v3,
)


def test_v3_receipt_requires_distance_and_bake_aligned_normal_non_regression() -> None:
    receipt = build_receipt_v3(
        target_family="female",
        initial_p95=0.043934,
        initial_rms=0.022300,
        final_p95=0.035700,
        final_rms=0.016900,
        initial_normal_mean=0.90,
        initial_normal_p05=0.64,
        final_normal_mean=0.91,
        final_normal_p05=0.66,
        normal_sample_count=4096,
        iterations=120,
    )

    assert receipt["method"] == METHOD_V3
    assert receipt["normalAlignmentAuthority"] == NORMAL_ALIGNMENT_AUTHORITY
    assert receipt["normalSampleMethod"] == NORMAL_SAMPLE_METHOD
    assert receipt["normalAwareNonRegression"] is True
    assert receipt["fitDidNotRegress"] is True
    assert receipt["comparisonOnly"] is True
    assert receipt["productionReady"] is False


def test_v3_rejects_real_lauren_style_distance_win_with_normal_regression() -> None:
    receipt = build_receipt_v3(
        target_family="female",
        initial_p95=0.043934,
        initial_rms=0.022300,
        final_p95=0.035678,
        final_rms=0.016812,
        initial_normal_mean=0.917377,
        initial_normal_p05=0.696926,
        final_normal_mean=0.896571,
        final_normal_p05=0.610147,
        normal_sample_count=4096,
        iterations=120,
    )

    assert receipt["normalAwareNonRegression"] is False
    assert receipt["fitDidNotRegress"] is False


def test_v3_uses_same_sith_surface_primitives_as_texture_bake() -> None:
    source = (BRIDGES / "sith_subject_anatomy_refit_v3.py").read_text(encoding="utf-8")

    assert "from recon.models.ops.mesh.closest_point import closest_point_fast" in source
    assert "from recon.models.ops.mesh.per_face_normals import per_face_normals" in source
    assert "sith-closest-source-triangle-face-normal-v1" in source
    assert "deterministic-smplx-face-centroids-v1" in source
    assert "nearest-source-vertex-area-weighted-v1" not in source

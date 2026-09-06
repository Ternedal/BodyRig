from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_exact_anatomy_bake_score import (  # noqa: E402
    ExactAnatomyBakeScoreError,
    METHOD,
    RESOLUTION,
    build_receipt,
)


def _metrics() -> dict[str, float]:
    return {
        "body_scale": 1.904077,
        "bake_surface_distance_p95": 0.036301,
        "bake_surface_distance_max": 0.108112,
        "normal_alignment_mean": 0.917377,
        "normal_alignment_p05": 0.696926,
        "normal_low_alignment_ratio": 0.060064,
        "normal_retry_texel_ratio": 0.226843,
        "bake_occupied_ratio": 0.739595,
        "bake_padded_texel_ratio": 0.827693,
    }


def test_exact_score_receipt_uses_production_bake_metrics_without_human_pass() -> None:
    receipt = build_receipt(
        donor_sha256="1" * 64,
        reconstruction_sha256="2" * 64,
        source_mesh_sha256="3" * 64,
        source_texture_sha256="4" * 64,
        gender="female",
        metrics=_metrics(),
    )

    assert receipt["method"] == METHOD
    assert receipt["resolution"] == RESOLUTION == 1024
    assert receipt["exactProductionBakePath"] is True
    assert receipt["comparisonOnly"] is True
    assert receipt["humanReviewRequired"] is True
    assert receipt["humanFidelityPass"] is False
    assert receipt["productionReady"] is False
    assert receipt["reconstructionRerun"] is False
    assert receipt["metrics"]["surface_distance_p95_body_ratio"] == pytest.approx(0.036301 / 1.904077)
    assert receipt["metrics"]["normal_alignment_mean"] == pytest.approx(0.917377)
    assert receipt["metrics"]["normal_alignment_p05"] == pytest.approx(0.696926)


def test_exact_score_receipt_rejects_invalid_metrics_and_gender() -> None:
    bad = _metrics()
    bad["normal_alignment_p05"] = -1.5
    with pytest.raises(ExactAnatomyBakeScoreError, match="normal metrics"):
        build_receipt(
            donor_sha256="1" * 64,
            reconstruction_sha256="2" * 64,
            source_mesh_sha256="3" * 64,
            source_texture_sha256="4" * 64,
            gender="female",
            metrics=bad,
        )

    with pytest.raises(ExactAnatomyBakeScoreError, match="gender"):
        build_receipt(
            donor_sha256="1" * 64,
            reconstruction_sha256="2" * 64,
            source_mesh_sha256="3" * 64,
            source_texture_sha256="4" * 64,
            gender="other",
            metrics=_metrics(),
        )


def test_exact_score_bridge_calls_the_same_production_anatomy_bake() -> None:
    source = (BRIDGES / "sith_exact_anatomy_bake_score.py").read_text(encoding="utf-8")
    assert "bake_sith_surface_to_anatomy_canonical_smplx(" in source
    assert "resolution=RESOLUTION" in source
    assert "RESOLUTION = 1024" in source
    assert "optimizer" not in source.lower()
    assert "humanFidelityPass\": False" in source


def test_exact_score_windows_operator_avoids_powershell_home_collision() -> None:
    source = (ROOT / "score-exact-anatomy-bake.ps1").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "$home =" not in lowered
    assert "$wslhome" in lowered
    assert "exact clean bodyrig checkout" in lowered
    assert "read-only exact anatomy bake scoring changed retained or donor bytes" in lowered

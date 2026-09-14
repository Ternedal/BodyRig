from __future__ import annotations

from pathlib import Path

import pytest

from bodyrig.hands_feet_nails_toenail_domain import (
    HandsFeetNailsToenailDomainError,
    TOE_LABELS,
    toe_source_landmarks,
)


def _projection() -> dict[str, object]:
    return {
        "landmarks": {
            "big_toe": {"x_norm": 0.25, "y_norm": 0.20, "confidence": 0.95},
            "small_toe": {"x_norm": 0.75, "y_norm": 0.24, "confidence": 0.90},
            "heel": {"x_norm": 0.50, "y_norm": 0.80, "confidence": 0.98},
        }
    }


def test_toe_source_landmarks_preserve_observed_endpoints_and_disclose_interpolation() -> None:
    result = toe_source_landmarks(_projection())
    assert tuple(result) == TOE_LABELS
    assert result["big_toe"]["interpolated"] is False
    assert result["small_toe"]["interpolated"] is False
    assert all(result[label]["interpolated"] is True for label in ("toe_2", "toe_3", "toe_4"))
    xs = [float(result[label]["x_norm"]) for label in TOE_LABELS]
    assert xs == sorted(xs)
    assert all(0.0 <= float(result[label]["x_norm"]) <= 1.0 for label in TOE_LABELS)
    assert all(0.0 <= float(result[label]["y_norm"]) <= 1.0 for label in TOE_LABELS)


@pytest.mark.parametrize("bad", [True, False, "0.5", None, float("nan")])
def test_toe_source_landmarks_reject_non_numeric_or_non_finite_authority(bad: object) -> None:
    projection = _projection()
    landmarks = projection["landmarks"]
    assert isinstance(landmarks, dict)
    big = landmarks["big_toe"]
    assert isinstance(big, dict)
    big["x_norm"] = bad
    with pytest.raises(HandsFeetNailsToenailDomainError):
        toe_source_landmarks(projection)


def test_toenail_materialization_is_wired_end_to_end() -> None:
    root = Path(__file__).resolve().parents[1]
    texture = (root / "bodyrig" / "hands_feet_nails_detail_texture.py").read_text(encoding="utf-8")
    geometry = (root / "bodyrig" / "hands_feet_nails_toenail_geometry_candidate.py").read_text(encoding="utf-8")
    continuation = (root / "bodyrig" / "high_fidelity_hfn_continuation.py").read_text(encoding="utf-8")
    review = (root / "bodyrig" / "high_fidelity_hfn_review.py").read_text(encoding="utf-8")
    probe = (root / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigRendererProbe.cs").read_text(encoding="utf-8")
    preflight = (root / "high-fidelity-rig-preflight.ps1").read_text(encoding="utf-8")

    assert "source-landmark-fingernail-toenail-residual-skinned-uv-v3" in texture
    assert "toenail_triangle_groups" in texture
    assert "toe_source_landmarks" in texture
    assert "TOE_LABELS" in texture
    assert 'NODE_NAME = "BodyRigToenailPlates"' in geometry
    assert '"plate_count": embedded["plateCount"]' in geometry
    assert '"individual_middle_toe_landmarks_observed": False' in geometry
    assert "read_toenail_geometry_candidate" in continuation
    assert "prepare-hands-feet-nails-toenail-geometry-candidate.ps1" in continuation
    assert '"toenail_plate_count"' in continuation
    assert "read_toenail_geometry_candidate" in review
    assert 'new ExpectedRenderPayload("toenails", "BodyRigToenailPlates")' in probe
    assert '"prepare-hands-feet-nails-toenail-geometry-candidate.ps1"' in preflight


def test_toenail_geometry_preserves_review_and_production_boundaries() -> None:
    root = Path(__file__).resolve().parents[1]
    geometry = (root / "bodyrig" / "hands_feet_nails_toenail_geometry_candidate.py").read_text(encoding="utf-8")
    for marker in (
        '"human_review_required": True',
        '"production_activation": False',
        '"source_grounded": True',
        '"additive_geometry_only": True',
        '"texture_modified": False',
        '"individualMiddleToeLandmarksObserved": False',
    ):
        assert marker in geometry

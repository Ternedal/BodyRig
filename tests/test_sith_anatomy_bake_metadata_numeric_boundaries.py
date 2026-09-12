from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

import sith_anatomy_bake_metadata as metadata  # noqa: E402


def _metrics() -> dict:
    return {
        "appearance_method": metadata.INTERNAL_METHOD,
        "anatomy_region_count": 6,
        "anatomy_restricted_texel_ratio": 1.0,
        "normal_retry_texel_count": 10,
        "normal_retry_texel_ratio": 0.02,
        "normal_alignment_mean": 0.91,
        "normal_alignment_p05": 0.55,
        "normal_low_alignment_ratio": 0.01,
        "body_scale": 2.0,
        "region_torso_texel_ratio": 0.30,
        "region_head_texel_ratio": 0.10,
        "region_left_arm_texel_ratio": 0.10,
        "region_right_arm_texel_ratio": 0.10,
        "region_left_leg_texel_ratio": 0.20,
        "region_right_leg_texel_ratio": 0.20,
    }


def test_numeric_helpers_normalize_huge_integer_overflow() -> None:
    with pytest.raises(metadata.AnatomyBakeMetadataError, match="distance is invalid"):
        metadata._finite_nonnegative(10**400, label="distance")
    with pytest.raises(metadata.AnatomyBakeMetadataError, match="alignment is invalid"):
        metadata._finite_signed(10**400, label="alignment")


def test_anatomy_mapping_huge_signed_metric_fails_with_domain_error(monkeypatch) -> None:
    monkeypatch.setattr(metadata, "canonical_appearance_transfer", lambda bodyrig, compatibility: {})
    metrics = _metrics()
    metrics["normal_alignment_mean"] = 10**400

    with pytest.raises(metadata.AnatomyBakeMetadataError, match="normal alignment mean is invalid"):
        metadata.anatomy_appearance_transfer({}, metrics)


def test_ordinary_anatomy_mapping_metrics_remain_valid(monkeypatch) -> None:
    monkeypatch.setattr(metadata, "canonical_appearance_transfer", lambda bodyrig, compatibility: {})

    receipt = metadata.anatomy_appearance_transfer({}, _metrics())

    assert receipt["method"] == metadata.METHOD
    assert receipt["anatomyRestrictedTexelRatio"] == 1.0
    assert receipt["normalAlignmentMean"] == 0.91
    assert receipt["bodyScale"] == 2.0

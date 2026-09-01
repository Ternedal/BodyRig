from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


BRIDGES = Path(__file__).resolve().parents[1] / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_donor_vrm_metadata import (  # noqa: E402
    DonorVrmMetadataError,
    _appearance_refinement_authority,
    _finite_nonnegative_metric,
)


def test_donor_metric_accepts_finite_nonnegative_value() -> None:
    assert _finite_nonnegative_metric(0.125, label="metric") == 0.125
    assert _finite_nonnegative_metric(0, label="metric") == 0.0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -0.001, True, "0.1", None])
def test_donor_metric_rejects_invalid_values(value: object) -> None:
    with pytest.raises(DonorVrmMetadataError, match="metric is invalid"):
        _finite_nonnegative_metric(value, label="metric")


def test_donor_metric_result_is_finite() -> None:
    value = _finite_nonnegative_metric(1.0, label="metric")
    assert math.isfinite(value)


def _appearance_receipts() -> dict[str, object]:
    return {
        "materialRefinement": {
            "method": "source-derived-pbr-v1",
            "physicalMeasurement": False,
            "sourceDerivedHeuristic": True,
        },
        "baseColorDetailRefinement": {
            "method": "source-luminance-bounded-detail-v1",
            "sourceBaseColorSha256": "a" * 64,
            "refinedBaseColorSha256": "b" * 64,
            "channelDeltaCap": 0.035,
            "maxObservedChannelDelta": 0.031,
            "sourceDerived": True,
            "generative": False,
        },
    }


def test_donor_appearance_authority_requires_bounded_source_derived_receipts() -> None:
    authority = _appearance_refinement_authority(_appearance_receipts())
    assert authority["pbr_method"] == "source-derived-pbr-v1"
    assert authority["basecolor_method"] == "source-luminance-bounded-detail-v1"
    assert authority["source_basecolor_sha256"] == "a" * 64
    assert authority["refined_basecolor_sha256"] == "b" * 64


def test_donor_appearance_authority_rejects_missing_pbr_receipt() -> None:
    bodyrig = _appearance_receipts()
    del bodyrig["materialRefinement"]
    with pytest.raises(DonorVrmMetadataError, match="PBR refinement receipt is missing"):
        _appearance_refinement_authority(bodyrig)


def test_donor_appearance_authority_rejects_generative_basecolor() -> None:
    bodyrig = _appearance_receipts()
    detail = dict(bodyrig["baseColorDetailRefinement"])  # type: ignore[arg-type]
    detail["generative"] = True
    bodyrig["baseColorDetailRefinement"] = detail
    with pytest.raises(DonorVrmMetadataError, match="base-color refinement authority"):
        _appearance_refinement_authority(bodyrig)


def test_donor_appearance_authority_rejects_delta_above_declared_cap() -> None:
    bodyrig = _appearance_receipts()
    detail = dict(bodyrig["baseColorDetailRefinement"])  # type: ignore[arg-type]
    detail["maxObservedChannelDelta"] = 0.05
    bodyrig["baseColorDetailRefinement"] = detail
    with pytest.raises(DonorVrmMetadataError, match="exceeded its declared cap"):
        _appearance_refinement_authority(bodyrig)

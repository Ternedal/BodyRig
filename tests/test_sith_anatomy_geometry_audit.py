from __future__ import annotations

import numpy as np

from bodyrig.bridges.sith_anatomy_geometry_audit import summarize_geometry


def _synthetic_body() -> np.ndarray:
    points: list[tuple[float, float, float]] = []
    for y in np.linspace(0.0, 2.0, 81):
        yn = y / 2.0
        if yn < 0.42:
            half_width, half_depth = 0.24, 0.16
        elif yn < 0.60:
            half_width, half_depth = 0.34, 0.22
        elif yn < 0.80:
            half_width, half_depth = 0.38, 0.24
        else:
            half_width, half_depth = 0.22, 0.20
        for x in np.linspace(-half_width, half_width, 5):
            for z in np.linspace(-half_depth, half_depth, 5):
                points.append((float(x), float(y), float(z)))
    return np.asarray(points, dtype=np.float64)


def test_anatomy_geometry_summary_passes_matching_body() -> None:
    donor = _synthetic_body()
    source = donor.copy()

    result = summarize_geometry(
        np,
        donor_positions=donor,
        source_positions=source,
        source_to_donor=np.zeros(len(source), dtype=np.float64),
        donor_to_source=np.zeros(len(donor), dtype=np.float64),
    )

    assert result["grossAnatomyPass"] is True
    assert result["humanReviewRequired"] is True
    assert result["sourceToDonorP95BodyHeightRatio"] == 0.0
    assert result["donorToSourceP95BodyHeightRatio"] == 0.0
    assert set(result["bands"]) == {"legs", "hips_waist", "torso_chest"}


def test_anatomy_geometry_summary_rejects_gross_torso_span_mismatch() -> None:
    donor = _synthetic_body()
    source = donor.copy()
    normalized_y = source[:, 1] / 2.0
    torso = (normalized_y >= 0.60) & (normalized_y < 0.80)
    source[torso, 0] *= 2.0

    result = summarize_geometry(
        np,
        donor_positions=donor,
        source_positions=source,
        source_to_donor=np.zeros(len(source), dtype=np.float64),
        donor_to_source=np.zeros(len(donor), dtype=np.float64),
    )

    assert result["grossAnatomyPass"] is False
    assert result["bands"]["torso_chest"]["grossBandPass"] is False
    assert result["bands"]["torso_chest"]["sourceToDonorWidthRatio"] > 1.65


def test_anatomy_geometry_summary_rejects_large_surface_distance() -> None:
    donor = _synthetic_body()
    source = donor.copy()
    source_to_donor = np.full(len(source), 0.20, dtype=np.float64)

    result = summarize_geometry(
        np,
        donor_positions=donor,
        source_positions=source,
        source_to_donor=source_to_donor,
        donor_to_source=np.zeros(len(donor), dtype=np.float64),
    )

    assert result["grossAnatomyPass"] is False
    assert result["sourceToDonorP95BodyHeightRatio"] == 0.1

from __future__ import annotations

import math

from bodyrig.mesh_topology_qa import _assessment, _quantile, _triangle_metrics


def test_triangle_metrics_identify_long_sliver() -> None:
    max_edge, altitude, aspect = _triangle_metrics(
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.5, 0.01, 0.0),
    )
    assert math.isclose(max_edge, 1.0)
    assert 0.009 <= altitude <= 0.011
    assert aspect >= 90.0


def test_triangle_metrics_keep_regular_triangle_well_conditioned() -> None:
    max_edge, altitude, aspect = _triangle_metrics(
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.5, math.sqrt(3.0) / 2.0, 0.0),
    )
    assert math.isclose(max_edge, 1.0)
    assert 0.8 < altitude < 0.9
    assert aspect < 1.3


def test_quantile_is_deterministic() -> None:
    values = [0.4, 0.1, 0.3, 0.2]
    assert math.isclose(_quantile(values, 0.0), 0.1)
    assert math.isclose(_quantile(values, 1.0), 0.4)
    assert math.isclose(_quantile(values, 0.5), 0.25)


def test_topology_classifier_fails_physically_observed_membrane_class() -> None:
    # Exact worst-edge ratio from the 2026-09-01 physical fail package.
    assert _assessment(max_edge_ratio=0.15053027, candidate_ratio=0.00319238) == "fail"


def test_topology_classifier_keeps_small_local_tessellation() -> None:
    assert _assessment(max_edge_ratio=0.03, candidate_ratio=0.0001) == "pass"


def test_topology_classifier_routes_borderline_mesh_to_review() -> None:
    assert _assessment(max_edge_ratio=0.09, candidate_ratio=0.0001) == "review"

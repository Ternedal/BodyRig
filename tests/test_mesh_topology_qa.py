from __future__ import annotations

import math

from bodyrig.mesh_topology_qa import _quantile, _triangle_metrics


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

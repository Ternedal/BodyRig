from __future__ import annotations

import math

import pytest

from bodyrig.bridges.sith_anatomy_geometry_audit import (
    AnatomyGeometryAuditError,
    band_geometry_gate,
    global_geometry_gate,
)


def test_global_anatomy_geometry_gate_passes_strict_match() -> None:
    assert global_geometry_gate(source_p95=0.02, donor_p95=0.015) is True


def test_global_anatomy_geometry_gate_rejects_large_source_distance() -> None:
    assert global_geometry_gate(source_p95=0.081, donor_p95=0.015) is False


def test_band_anatomy_geometry_gate_passes_plausible_span_and_distance() -> None:
    assert band_geometry_gate(
        source_p95=0.03,
        donor_p95=0.02,
        width_ratio=1.08,
        depth_ratio=0.94,
    ) is True


def test_band_anatomy_geometry_gate_rejects_gross_torso_span_mismatch() -> None:
    assert band_geometry_gate(
        source_p95=0.03,
        donor_p95=0.02,
        width_ratio=1.66,
        depth_ratio=1.0,
    ) is False


def test_band_anatomy_geometry_gate_rejects_large_surface_distance() -> None:
    assert band_geometry_gate(
        source_p95=0.081,
        donor_p95=0.02,
        width_ratio=1.0,
        depth_ratio=1.0,
    ) is False


def test_anatomy_geometry_gate_rejects_non_finite_metrics() -> None:
    with pytest.raises(AnatomyGeometryAuditError, match="is invalid"):
        global_geometry_gate(source_p95=math.inf, donor_p95=0.01)

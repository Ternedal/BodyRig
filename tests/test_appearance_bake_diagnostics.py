from __future__ import annotations

import pytest

from bodyrig.appearance_bake_diagnostics import (
    ANATOMY_METHOD,
    BAKE_RETRY_COSINE,
    AppearanceBakeDiagnosticsError,
    classify_appearance_transfer,
)


def appearance(**overrides: float | str | bool) -> dict:
    value: dict = {
        "method": ANATOMY_METHOD,
        "bodyScale": 2.0,
        "nearestSourceSurfaceDistanceP95": 0.012,
        "nearestSourceSurfaceDistanceMax": 0.041,
        "normalAlignmentMean": 0.91,
        "normalAlignmentP05": 0.82,
        "normalLowAlignmentRatio": 0.01,
        "normalRetryTexelRatio": 0.02,
        "occupiedTexelRatio": 0.667572,
        "paddedTexelRatio": 0.70,
    }
    value.update(overrides)
    return value


def test_nominal_anatomy_bake_diagnostics_never_claim_human_pass() -> None:
    result = classify_appearance_transfer(appearance())

    assert BAKE_RETRY_COSINE == 0.75
    assert result["diagnostic_risk"] == "nominal"
    assert result["reasons"] == []
    assert result["manual_review_required"] is True
    assert result["human_fidelity_pass"] is False
    assert result["metrics"]["surface_distance_p95_body_ratio"] == 0.006


def test_lauren_observed_correspondence_metrics_force_review() -> None:
    result = classify_appearance_transfer(
        appearance(
            bodyScale=1.934992,
            nearestSourceSurfaceDistanceP95=0.035545,
            nearestSourceSurfaceDistanceMax=0.105715,
            normalAlignmentMean=0.899489,
            normalAlignmentP05=0.554357,
            normalLowAlignmentRatio=0.04482,
            normalRetryTexelRatio=0.060553,
            occupiedTexelRatio=0.739595,
            paddedTexelRatio=0.827693,
        )
    )

    assert result["diagnostic_risk"] == "review"
    assert result["human_fidelity_pass"] is False
    assert any("p05" in reason or "source-surface" in reason for reason in result["reasons"])


def test_low_normal_alignment_forces_review() -> None:
    result = classify_appearance_transfer(
        appearance(normalAlignmentP05=0.55, normalLowAlignmentRatio=0.08)
    )

    assert result["diagnostic_risk"] == "review"
    assert any("normal-alignment" in reason for reason in result["reasons"])


def test_opposite_facing_and_large_projection_force_high_risk() -> None:
    result = classify_appearance_transfer(
        appearance(
            nearestSourceSurfaceDistanceP95=0.14,
            nearestSourceSurfaceDistanceMax=0.30,
            normalAlignmentP05=-0.20,
            normalLowAlignmentRatio=0.30,
        )
    )

    assert result["diagnostic_risk"] == "high-risk"
    assert result["human_fidelity_pass"] is False


def test_diagnostics_are_body_scale_normalized() -> None:
    small = classify_appearance_transfer(
        appearance(bodyScale=1.0, nearestSourceSurfaceDistanceP95=0.04)
    )
    large = classify_appearance_transfer(
        appearance(bodyScale=4.0, nearestSourceSurfaceDistanceP95=0.04)
    )

    assert small["diagnostic_risk"] == "review"
    assert large["diagnostic_risk"] == "nominal"


def test_wrong_appearance_authority_fails_closed() -> None:
    with pytest.raises(AppearanceBakeDiagnosticsError, match="canonical anatomy-aware"):
        classify_appearance_transfer(appearance(method="legacy"))


def test_invalid_coverage_fails_closed() -> None:
    with pytest.raises(AppearanceBakeDiagnosticsError, match="padded coverage"):
        classify_appearance_transfer(appearance(occupiedTexelRatio=0.8, paddedTexelRatio=0.7))

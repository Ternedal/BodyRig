from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_subject_anatomy_refit import (  # noqa: E402
    METHOD_V1,
    METHOD_V2,
    SubjectAnatomyRefitError,
    _fit_payload,
    build_receipt,
)


def _params() -> dict[str, list[float]]:
    return {
        "global_orient": [0.0] * 3,
        "body_pose": [0.0] * 63,
        "betas": [0.0] * 10,
        "left_hand_pose": [0.0] * 45,
        "right_hand_pose": [0.0] * 45,
        "jaw_pose": [0.0] * 3,
        "expression": [0.0] * 10,
        "leye_pose": [0.0] * 3,
        "reye_pose": [0.0] * 3,
        "transl": [0.0] * 3,
        "scale": [1.0],
    }


def test_subject_anatomy_receipt_is_comparison_only_and_non_generative() -> None:
    receipt = build_receipt(
        target_family="female",
        initial_p95=0.08,
        initial_rms=0.04,
        final_p95=0.05,
        final_rms=0.025,
        iterations=120,
    )

    assert receipt["targetModelFamily"] == "female"
    assert receipt["method"] == METHOD_V1
    assert receipt["fitDidNotRegress"] is True
    assert receipt["retainedReconstructionModified"] is False
    assert receipt["reconstructionRerun"] is False
    assert receipt["generativeGeometry"] is False
    assert receipt["comparisonOnly"] is True
    assert receipt["humanReviewRequired"] is True
    assert receipt["productionReady"] is False


def test_subject_anatomy_receipt_marks_regression_without_hiding_candidate() -> None:
    receipt = build_receipt(
        target_family="female",
        initial_p95=0.05,
        initial_rms=0.02,
        final_p95=0.051,
        final_rms=0.019,
        iterations=120,
    )

    assert receipt["fitDidNotRegress"] is False
    assert receipt["comparisonOnly"] is True


def test_normal_aware_receipt_requires_distance_and_normal_non_regression() -> None:
    receipt = build_receipt(
        target_family="female",
        initial_p95=0.08,
        initial_rms=0.04,
        final_p95=0.05,
        final_rms=0.025,
        iterations=120,
        initial_normal_mean=0.90,
        initial_normal_p05=0.65,
        final_normal_mean=0.92,
        final_normal_p05=0.69,
    )

    assert receipt["method"] == METHOD_V2
    assert receipt["normalAwareNonRegression"] is True
    assert receipt["fitDidNotRegress"] is True
    assert receipt["normalAlignmentAuthority"] == "nearest-source-vertex-area-weighted-v1"
    assert receipt["normalLossWeight"] > 0.0


def test_normal_aware_receipt_rejects_lauren_style_normal_regression_even_when_distance_improves() -> None:
    receipt = build_receipt(
        target_family="female",
        initial_p95=0.043934,
        initial_rms=0.022300,
        final_p95=0.035608,
        final_rms=0.016780,
        iterations=120,
        initial_normal_mean=0.917377,
        initial_normal_p05=0.696926,
        final_normal_mean=0.896571,
        final_normal_p05=0.610147,
    )

    assert receipt["method"] == METHOD_V2
    assert receipt["normalAwareNonRegression"] is False
    assert receipt["fitDidNotRegress"] is False
    assert receipt["comparisonOnly"] is True


def test_normal_aware_receipt_requires_complete_normal_metrics() -> None:
    with pytest.raises(SubjectAnatomyRefitError, match="requires all normal alignment metrics"):
        build_receipt(
            target_family="female",
            initial_p95=0.08,
            initial_rms=0.04,
            final_p95=0.05,
            final_rms=0.025,
            iterations=120,
            initial_normal_mean=0.9,
        )


def test_subject_anatomy_fit_payload_changes_only_shape_translation_and_scale() -> None:
    original = _params()
    derived = _fit_payload(
        original,
        betas=[0.1] * 10,
        transl=[0.01, -0.02, 0.03],
        scale=1.05,
    )

    assert derived["betas"] == [0.1] * 10
    assert derived["transl"] == [0.01, -0.02, 0.03]
    assert derived["scale"] == [1.05]
    for field in (
        "global_orient",
        "body_pose",
        "left_hand_pose",
        "right_hand_pose",
        "jaw_pose",
        "expression",
        "leye_pose",
        "reye_pose",
    ):
        assert derived[field] == original[field]


def test_subject_anatomy_refit_rejects_unknown_target_family() -> None:
    with pytest.raises(SubjectAnatomyRefitError, match="target SMPL-X model family is invalid"):
        build_receipt(
            target_family="other",
            initial_p95=0.08,
            initial_rms=0.04,
            final_p95=0.05,
            final_rms=0.025,
            iterations=120,
        )


def test_refit_source_contains_normal_aware_objective() -> None:
    source = (BRIDGES / "sith_subject_anatomy_refit.py").read_text(encoding="utf-8")
    assert "NORMAL_LOSS_WEIGHT" in source
    assert "normal_loss =" in source
    assert "_normal_alignment_values(" in source
    assert "normalAwareNonRegression" in source

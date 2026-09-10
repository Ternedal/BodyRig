from __future__ import annotations

import math
from pathlib import Path

import pytest

from bodyrig.exact_bake_anatomy_preview import (
    ExactBakeAnatomyPreviewError,
    METRIC_KEYS,
    SCORE_FORMAT,
    SCORE_METHOD,
    SCORE_VERSION,
    _expected_interpolation,
    _fit_matches,
    _metric_row,
    _validate_score,
)


ROOT = Path(__file__).resolve().parents[1]


def _fit() -> dict[str, list[float]]:
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


def _row(alpha: float = 0.375) -> dict[str, float]:
    return {
        "alpha": alpha,
        "surface_distance_p95_body_ratio": 0.02227,
        "surface_distance_max_body_ratio": 0.069667,
        "normal_alignment_mean": 0.900322,
        "normal_alignment_p05": 0.599237,
        "normal_low_alignment_ratio": 0.07855,
        "normal_retry_texel_ratio": 0.28574,
    }


def _score(row: dict[str, float]) -> dict[str, object]:
    return {
        "format": SCORE_FORMAT,
        "version": SCORE_VERSION,
        "method": SCORE_METHOD,
        "resolution": 1024,
        "metrics": {key: row[key] for key in METRIC_KEYS},
        "sourceDerived": True,
        "exactProductionBakePath": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "humanFidelityPass": False,
        "productionReady": False,
        "reconstructionRerun": False,
    }


def test_selected_fit_is_exact_retained_to_endpoint_interpolation() -> None:
    retained = _fit()
    endpoint = _fit()
    endpoint["betas"] = [2.0] * 10
    endpoint["transl"] = [4.0, 8.0, 12.0]
    endpoint["scale"] = [4.0]

    actual = _expected_interpolation(retained, endpoint, alpha=0.375)

    assert actual["betas"] == pytest.approx([0.75] * 10)
    assert actual["transl"] == pytest.approx([1.5, 3.0, 4.5])
    assert actual["scale"] == pytest.approx([math.exp(0.375 * math.log(4.0))])
    assert actual["body_pose"] == retained["body_pose"]
    assert _fit_matches(actual, actual)


def test_selected_fit_rejects_endpoint_or_pose_drift() -> None:
    retained = _fit()
    endpoint = _fit()
    endpoint["jaw_pose"][0] = 0.01

    with pytest.raises(ExactBakeAnatomyPreviewError, match="pose authority"):
        _expected_interpolation(retained, endpoint, alpha=0.375)

    endpoint = _fit()
    for alpha in (0.0, 1.0, -0.1, 1.1):
        with pytest.raises(ExactBakeAnatomyPreviewError, match="strictly between"):
            _expected_interpolation(retained, endpoint, alpha=alpha)


def test_selected_alpha_must_exist_exactly_once_in_line_search() -> None:
    row = _row()
    line_search = {"rows": [row]}

    assert _metric_row(line_search, alpha=0.375) == row

    with pytest.raises(ExactBakeAnatomyPreviewError, match="exactly one"):
        _metric_row({"rows": []}, alpha=0.375)
    with pytest.raises(ExactBakeAnatomyPreviewError, match="exactly one"):
        _metric_row({"rows": [row, dict(row)]}, alpha=0.375)


def test_selected_score_must_reproduce_line_search_metrics_and_stay_non_activating() -> None:
    row = _row()
    score = _score(row)
    _validate_score(score, row=row, alpha=0.375)

    drifted = _score(row)
    drifted["metrics"] = dict(drifted["metrics"])
    drifted["metrics"]["normal_alignment_p05"] = row["normal_alignment_p05"] - 0.001
    with pytest.raises(ExactBakeAnatomyPreviewError, match="does not match"):
        _validate_score(drifted, row=row, alpha=0.375)

    activating = _score(row)
    activating["productionReady"] = True
    with pytest.raises(ExactBakeAnatomyPreviewError, match="authority boundary"):
        _validate_score(activating, row=row, alpha=0.375)


def test_windows_operator_re_scores_current_revision_renders_and_cannot_promote() -> None:
    source = (ROOT / "run-exact-bake-anatomy-preview.ps1").read_text(encoding="utf-8")
    lowered = source.lower()

    assert "exact clean bodyrig checkout" in lowered
    assert "score-exact-anatomy-bake.ps1" in lowered
    assert "run-fidelity-windows-render-probe.ps1" in lowered
    assert "current exact-bake metric" in lowered
    assert "reconstruction_rerun = $false" in lowered
    assert "promotion_eligible = $false" in lowered
    assert "production_activation = $false" in lowered
    assert "promote-high-fidelity-anatomy.ps1" not in lowered
    assert "complete-reference-acceptance.ps1" not in lowered


def test_preview_workspace_contract_is_explicitly_non_promotable() -> None:
    source = (ROOT / "bodyrig" / "exact_bake_anatomy_preview.py").read_text(encoding="utf-8")
    assert '"comparisonOnly": True' in source
    assert '"humanReviewRequired": True' in source
    assert '"promotionEligible": False' in source
    assert '"productionReady": False' in source
    assert '"reconstructionRerun": False' in source
    assert "write_reconstruction_authority" in source

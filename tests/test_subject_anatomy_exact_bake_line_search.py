from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

import sith_smplx_vrm_fitter as base  # noqa: E402
from sith_subject_anatomy_line_search import (  # noqa: E402
    DEFAULT_ALPHAS,
    METHOD,
    SubjectAnatomyLineSearchError,
    interpolate_fit,
    parse_alphas,
)


def _fit() -> dict[str, list[float]]:
    return {
        field: [0.0] * width
        for field, width in base.FIT_PARAM_LENGTHS.items()
    }


def test_default_line_search_is_bounded_and_excludes_endpoints() -> None:
    values = parse_alphas(None)
    assert values == DEFAULT_ALPHAS
    assert values == tuple(sorted(values))
    assert all(0.0 < value < 1.0 for value in values)
    assert METHOD == "retained-to-v3-fit-parameter-line-search-exact-production-bake-v1"


def test_custom_alphas_are_sorted_unique_and_fail_closed() -> None:
    assert parse_alphas("0.75, 0.25,0.5,0.25") == (0.25, 0.5, 0.75)
    for raw in ("0", "1", "-0.1", "1.1", "nan", "0.2,,0.4"):
        with pytest.raises(SubjectAnatomyLineSearchError):
            parse_alphas(raw)


def test_fit_interpolation_keeps_pose_authority_and_uses_log_scale() -> None:
    retained = _fit()
    endpoint = _fit()
    retained["scale"] = [1.0]
    endpoint["scale"] = [4.0]
    retained["betas"] = [0.0] * 10
    endpoint["betas"] = [2.0] * 10
    retained["transl"] = [0.0, 1.0, 2.0]
    endpoint["transl"] = [2.0, 3.0, 4.0]
    retained["body_pose"][0] = 0.25
    endpoint["body_pose"][0] = 0.25

    result = interpolate_fit(retained, endpoint, alpha=0.5)

    assert result["betas"] == pytest.approx([1.0] * 10)
    assert result["transl"] == pytest.approx([1.0, 2.0, 3.0])
    assert result["scale"] == pytest.approx([2.0])
    assert result["body_pose"] == retained["body_pose"]
    assert math.isfinite(result["scale"][0])


def test_fit_interpolation_rejects_pose_or_expression_endpoint_drift() -> None:
    retained = _fit()
    endpoint = _fit()
    retained["scale"] = [1.0]
    endpoint["scale"] = [1.0]
    endpoint["expression"][3] = 0.1

    with pytest.raises(SubjectAnatomyLineSearchError, match="pose authority"):
        interpolate_fit(retained, endpoint, alpha=0.5)


def test_line_search_bridge_reuses_exact_production_bake_scorer() -> None:
    source = (BRIDGES / "sith_subject_anatomy_line_search.py").read_text(encoding="utf-8")
    assert "import sith_exact_anatomy_bake_score as exact_score" in source
    assert "exact_score.score(" in source
    assert "humanFidelityPass\": False" in source
    assert "productionReady\": False" in source
    assert "reconstructionRerun\": False" in source
    assert "optimizer" not in source.lower()


def test_line_search_windows_operator_preserves_authority_and_avoids_home_collision() -> None:
    source = (ROOT / "line-search-exact-anatomy-bake.ps1").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "$home =" not in lowered
    assert "$wslhome" in lowered
    assert "exact clean bodyrig checkout" in lowered
    assert "changed retained or endpoint authority bytes" in lowered
    assert "exact 1024x1024 production anatomy bake" in lowered
    assert "production:     false" in lowered

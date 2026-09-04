from __future__ import annotations

from pathlib import Path

from bodyrig import skin_qa


DONOR_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "bodyrig"
    / "bridges"
    / "sith_smplx_vrm_fitter_donor.py"
).read_text(encoding="utf-8")


def test_direct_donor_lbs_does_not_use_review_threshold_as_build_abort() -> None:
    assert "ANATOMY_GUARD_THRESHOLD" not in DONOR_SOURCE
    assert "_DONOR_DIRECT_LBS_HARD_MAX_FORBIDDEN_WEIGHT = 0.75" in DONOR_SOURCE
    assert "if mass > _DONOR_DIRECT_LBS_HARD_MAX_FORBIDDEN_WEIGHT + 1e-6:" in DONOR_SOURCE
    assert "donor_forbidden_weight_max" in DONOR_SOURCE


def test_physical_20260902_single_vertex_value_reaches_aggregate_skin_qa() -> None:
    observed_forbidden_weight = 0.172193
    assert observed_forbidden_weight > skin_qa.SUSPICIOUS_WEIGHT
    assert observed_forbidden_weight < 0.75
    assert skin_qa.SUSPICIOUS_WEIGHT == 0.10
    assert skin_qa.SEVERE_WEIGHT == 0.35


def test_downstream_skin_qa_remains_the_aggregate_risk_gate() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "bodyrig" / "skin_qa.py"
    ).read_text(encoding="utf-8")
    assert "severe_ratio > 0.002" in source
    assert "p95_forbidden > 0.15" in source
    assert "max_forbidden > 0.75" in source

from __future__ import annotations

import copy

import pytest

from bodyrig.fidelity_convergence import FidelityConvergenceError, FidelityPolicy, validate_measurement


MEASUREMENT = {
    "format": "bodyrig-fidelity-measurement",
    "version": 1,
    "iteration": 1,
    "candidate_sha256": "1" * 64,
    "reference_set_sha256": "2" * 64,
    "evaluator": {"name": "fixture", "revision": "fixture-v1"},
    "scores": {
        "face_appearance": 0.5,
        "body_silhouette": 0.5,
        "hair_appearance": 0.5,
        "skin_material": 0.5,
        "photorealism": 0.5,
        "human_plausibility": 0.5,
        "overall": 0.5,
    },
    "semantics": "visual-fidelity-not-identity-verification",
}


def test_huge_measurement_score_fails_with_domain_error() -> None:
    value = copy.deepcopy(MEASUREMENT)
    value["scores"]["overall"] = 10**400

    with pytest.raises(FidelityConvergenceError, match="scores.overall"):
        validate_measurement(value)


def test_huge_policy_ratio_fails_with_domain_error() -> None:
    with pytest.raises(FidelityConvergenceError, match="policy.face_appearance"):
        FidelityPolicy(face_appearance=10**400)

    with pytest.raises(FidelityConvergenceError, match="policy.min_improvement"):
        FidelityPolicy(min_improvement=10**400)


def test_boolean_measurement_version_is_rejected_but_numeric_v1_equality_is_preserved() -> None:
    boolean_version = copy.deepcopy(MEASUREMENT)
    boolean_version["version"] = True
    with pytest.raises(FidelityConvergenceError, match="format/version"):
        validate_measurement(boolean_version)

    numeric_version = copy.deepcopy(MEASUREMENT)
    numeric_version["version"] = 1.0
    assert validate_measurement(numeric_version)["version"] == 1


def test_score_boundaries_remain_inclusive() -> None:
    value = copy.deepcopy(MEASUREMENT)
    for index, field in enumerate(value["scores"]):
        value["scores"][field] = index % 2

    normalized = validate_measurement(value)
    assert set(normalized["scores"].values()) == {0.0, 1.0}

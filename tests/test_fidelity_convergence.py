from __future__ import annotations

import pytest

from bodyrig.fidelity_convergence import (
    FidelityConvergenceError,
    FidelityPolicy,
    decide_convergence,
    validate_measurement,
)


def measurement(
    iteration: int,
    *,
    overall: float,
    face: float | None = None,
    body: float | None = None,
    hair: float | None = None,
    skin: float | None = None,
    photorealism: float | None = None,
    reference: str = "a" * 64,
    evaluator_revision: str = "eval-r2",
    candidate: str | None = None,
) -> dict:
    return {
        "format": "bodyrig-fidelity-measurement",
        "version": 1,
        "iteration": iteration,
        "candidate_sha256": candidate or f"{iteration:064x}",
        "reference_set_sha256": reference,
        "evaluator": {"name": "bodyrig-perceptual-fidelity", "revision": evaluator_revision},
        "scores": {
            "face_appearance": overall if face is None else face,
            "body_silhouette": overall if body is None else body,
            "hair_appearance": overall if hair is None else hair,
            "skin_material": overall if skin is None else skin,
            "photorealism": overall if photorealism is None else photorealism,
            "overall": overall,
        },
        "semantics": "visual-fidelity-not-identity-verification",
    }


def test_below_target_means_iterate_not_fail() -> None:
    result = decide_convergence([measurement(1, overall=0.55)])
    assert result["state"] == "iterate"
    assert result["continue_automatically"] is True
    assert result["human_visual_authority_required"] is True
    assert "fail" not in result["state"]


def test_converges_only_when_every_required_visual_dimension_passes() -> None:
    result = decide_convergence([
        measurement(1, overall=0.90, face=0.90, body=0.92, hair=0.84, skin=0.82, photorealism=0.88)
    ])
    assert result["state"] == "converged"
    assert result["continue_automatically"] is False
    assert result["unmet"] == []


def test_high_overall_does_not_hide_bad_face_appearance() -> None:
    result = decide_convergence([
        measurement(1, overall=0.90, face=0.50, body=0.94, hair=0.90, skin=0.90, photorealism=0.90)
    ])
    assert result["state"] == "iterate"
    assert "face_appearance" in result["unmet"]
    assert result["next_focus"] == "face_appearance"


def test_high_likeness_does_not_hide_non_photorealistic_render() -> None:
    result = decide_convergence([
        measurement(1, overall=0.90, face=0.91, body=0.94, hair=0.89, skin=0.88, photorealism=0.45)
    ])
    assert result["state"] == "iterate"
    assert "photorealism" in result["unmet"]
    assert result["next_focus"] == "photorealism"
    assert result["strategy"] == "appearance-search"


def test_plateau_retunes_and_keeps_running_instead_of_stopping() -> None:
    policy = FidelityPolicy(min_improvement=0.02, plateau_window=3, max_iterations=10)
    result = decide_convergence(
        [measurement(1, overall=0.61), measurement(2, overall=0.615), measurement(3, overall=0.619)],
        policy=policy,
    )
    assert result["state"] == "plateau"
    assert result["continue_automatically"] is True
    assert result["strategy"] == "retune-search"
    assert "automatically retune" in result["reason"]


def test_max_iteration_budget_escalates_to_manual_review_not_failure() -> None:
    policy = FidelityPolicy(max_iterations=3, plateau_window=3, min_improvement=0.001)
    result = decide_convergence(
        [measurement(1, overall=0.40), measurement(2, overall=0.50), measurement(3, overall=0.60)],
        policy=policy,
    )
    assert result["state"] == "manual-review"
    assert result["continue_automatically"] is False
    assert result["best_iteration"] == 3
    assert "fail" not in result["state"]


def test_best_candidate_survives_a_worse_new_iteration() -> None:
    result = decide_convergence([measurement(1, overall=0.72), measurement(2, overall=0.65)])
    assert result["best_iteration"] == 1
    assert result["best_overall"] == pytest.approx(0.72)
    assert result["best_candidate_sha256"] == f"{1:064x}"
    assert result["best_scores"]["overall"] == pytest.approx(0.72)


def test_best_candidate_prioritizes_weakest_dimension_over_raw_average() -> None:
    result = decide_convergence([
        measurement(1, overall=0.90, face=0.50, body=0.95, hair=0.95, skin=0.95, photorealism=0.95),
        measurement(2, overall=0.82, face=0.82, body=0.86, hair=0.82, skin=0.82, photorealism=0.82),
    ])
    assert result["best_iteration"] == 2
    assert result["best_scores"]["face_appearance"] == pytest.approx(0.82)


def test_history_must_keep_exact_reference_and_evaluator_authority() -> None:
    with pytest.raises(FidelityConvergenceError, match="same reference set"):
        decide_convergence([measurement(1, overall=0.5), measurement(2, overall=0.6, reference="b" * 64)])
    with pytest.raises(FidelityConvergenceError, match="same evaluator revision"):
        decide_convergence([measurement(1, overall=0.5), measurement(2, overall=0.6, evaluator_revision="eval-r3")])


def test_history_must_be_contiguous() -> None:
    with pytest.raises(FidelityConvergenceError, match="contiguous"):
        decide_convergence([measurement(1, overall=0.5), measurement(3, overall=0.6)])


def test_measurement_rejects_wrong_visual_fidelity_semantics() -> None:
    value = measurement(1, overall=0.5)
    value["semantics"] = "unsupported-visual-semantics"
    with pytest.raises(FidelityConvergenceError, match="semantics"):
        validate_measurement(value)

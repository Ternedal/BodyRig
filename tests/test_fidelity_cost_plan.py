from __future__ import annotations

import pytest

from bodyrig.fidelity_cost_plan import (
    FidelityCostPlanError,
    FidelityCostPolicy,
    estimate_eta_seconds,
    next_action,
    progress_payload,
)


def test_scheduler_prefers_new_resume_refinement_before_another_full_rebuild() -> None:
    request = "a" * 64
    result = next_action(
        convergence_state="iterate",
        full_rebuilds_completed=1,
        refinements_on_current_rebuild=0,
        adjustment_request_sha256=request,
        used_adjustment_sha256=[],
    )
    assert result["action"] == "resume-refinement"
    assert result["adjustment_request_sha256"] == request


def test_scheduler_never_repeats_same_adjustment_and_caps_expensive_rebuilds() -> None:
    request = "a" * 64
    result = next_action(
        convergence_state="iterate",
        full_rebuilds_completed=1,
        refinements_on_current_rebuild=1,
        adjustment_request_sha256=request,
        used_adjustment_sha256=[request],
    )
    assert result["action"] == "full-rebuild"

    exhausted = next_action(
        convergence_state="plateau",
        full_rebuilds_completed=2,
        refinements_on_current_rebuild=1,
        adjustment_request_sha256=request,
        used_adjustment_sha256=[request],
    )
    assert exhausted["action"] == "stop-budget"
    assert "preserve best-so-far" in exhausted["reason"]


def test_converged_always_stops_without_spending_more_compute() -> None:
    result = next_action(
        convergence_state="converged",
        full_rebuilds_completed=1,
        refinements_on_current_rebuild=0,
        adjustment_request_sha256="b" * 64,
        used_adjustment_sha256=[],
    )
    assert result["action"] == "stop-converged"


def test_policy_defaults_bound_full_5_hour_reconstructions() -> None:
    policy = FidelityCostPolicy()
    assert policy.max_full_rebuilds == 2
    assert policy.max_refinements_per_rebuild == 3
    with pytest.raises(FidelityCostPlanError):
        FidelityCostPolicy(max_full_rebuilds=5)


def test_eta_uses_observed_timings_and_refuses_to_invent_first_run_duration() -> None:
    assert estimate_eta_seconds(
        full_rebuild_seconds=[],
        refinement_seconds=[600],
        planned_full_rebuilds_remaining=1,
        planned_refinements_remaining=0,
    ) is None

    assert estimate_eta_seconds(
        full_rebuild_seconds=[18_000, 21_600],
        refinement_seconds=[600, 900],
        planned_full_rebuilds_remaining=1,
        planned_refinements_remaining=2,
    ) == 21_300


def test_progress_payload_exposes_cost_and_quality_state() -> None:
    value = progress_payload(
        state="running",
        stage="resume-refinement",
        full_rebuilds_completed=1,
        max_full_rebuilds=2,
        refinements_completed=1,
        current_rebuild_refinements=1,
        max_refinements_per_rebuild=3,
        elapsed_seconds=20_000,
        eta_seconds=900,
        current_seed=1337,
        latest_scores={"photorealism": 0.84, "human_plausibility": 0.79},
        best_scores={"photorealism": 0.86, "human_plausibility": 0.81},
        best_candidate="rebuild-01/refinement-01",
        strategy="plausibility-search",
        next_focus="human_plausibility",
        phase_timings={"full-rebuild": [18_500.2], "resume-refinement": [700.5]},
    )
    assert value["format"] == "bodyrig-fidelity-progress"
    assert value["eta_seconds"] == 900
    assert value["best_candidate"] == "rebuild-01/refinement-01"
    assert value["latest_scores"]["human_plausibility"] == 0.79

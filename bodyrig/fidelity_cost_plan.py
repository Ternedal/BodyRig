from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class FidelityCostPlanError(ValueError):
    pass


@dataclass(frozen=True)
class FidelityCostPolicy:
    max_full_rebuilds: int = 2
    max_refinements_per_rebuild: int = 3

    def __post_init__(self) -> None:
        if isinstance(self.max_full_rebuilds, bool) or not 1 <= self.max_full_rebuilds <= 4:
            raise FidelityCostPlanError("max_full_rebuilds must be in 1..4")
        if isinstance(self.max_refinements_per_rebuild, bool) or not 0 <= self.max_refinements_per_rebuild <= 8:
            raise FidelityCostPlanError("max_refinements_per_rebuild must be in 0..8")


def next_action(
    *,
    convergence_state: str,
    full_rebuilds_completed: int,
    refinements_on_current_rebuild: int,
    adjustment_request_sha256: str | None,
    used_adjustment_sha256: Sequence[str],
    policy: FidelityCostPolicy = FidelityCostPolicy(),
) -> dict[str, Any]:
    """Choose the next expensive or cheap fidelity action.

    A cheap refinement is only useful when it applies a *new* bounded BodyPrint
    adjustment to an already-authoritative SiTH workspace. Re-running the same
    adjustment would reproduce the same package, so the scheduler escalates to a
    new reconstruction instead of burning time on duplicate work.
    """

    if convergence_state not in {"iterate", "plateau", "converged", "manual-review"}:
        raise FidelityCostPlanError("unsupported convergence state")
    if isinstance(full_rebuilds_completed, bool) or full_rebuilds_completed < 0:
        raise FidelityCostPlanError("full_rebuilds_completed is invalid")
    if isinstance(refinements_on_current_rebuild, bool) or refinements_on_current_rebuild < 0:
        raise FidelityCostPlanError("refinements_on_current_rebuild is invalid")
    if full_rebuilds_completed > policy.max_full_rebuilds:
        raise FidelityCostPlanError("full rebuild count exceeds policy")
    if refinements_on_current_rebuild > policy.max_refinements_per_rebuild:
        raise FidelityCostPlanError("refinement count exceeds policy")

    if convergence_state == "converged":
        return {"action": "stop-converged", "reason": "all fidelity thresholds reached"}
    if convergence_state == "manual-review":
        return {
            "action": "stop-budget",
            "reason": "convergence candidate budget reached; preserve best-so-far for human strategy review",
        }

    used = {str(value).lower() for value in used_adjustment_sha256}
    adjustment = str(adjustment_request_sha256 or "").lower()
    has_new_adjustment = (
        len(adjustment) == 64
        and all(ch in "0123456789abcdef" for ch in adjustment)
        and adjustment not in used
    )
    if has_new_adjustment and refinements_on_current_rebuild < policy.max_refinements_per_rebuild:
        return {
            "action": "resume-refinement",
            "reason": "new bounded geometry adjustment can reuse the current SiTH reconstruction",
            "adjustment_request_sha256": adjustment,
        }

    if full_rebuilds_completed < policy.max_full_rebuilds:
        return {
            "action": "full-rebuild",
            "reason": (
                "no new cheap refinement remains on this reconstruction; "
                "use the next deterministic SiTH seed"
            ),
        }

    return {
        "action": "stop-budget",
        "reason": "full reconstruction budget exhausted; preserve best-so-far for human strategy review",
    }


def estimate_eta_seconds(
    *,
    full_rebuild_seconds: Sequence[float],
    refinement_seconds: Sequence[float],
    planned_full_rebuilds_remaining: int,
    planned_refinements_remaining: int,
) -> int | None:
    """Estimate remaining work only from timings observed in this run.

    Before a stage has completed once, BodyRig deliberately returns no estimate
    instead of inventing one. This is especially important for 5–6 hour SiTH
    runs where a fake ETA would be worse than an unknown ETA.
    """

    if planned_full_rebuilds_remaining < 0 or planned_refinements_remaining < 0:
        raise FidelityCostPlanError("remaining work counts cannot be negative")

    def average(values: Sequence[float]) -> float | None:
        cleaned = [float(value) for value in values if float(value) >= 0.0]
        if not cleaned:
            return None
        return sum(cleaned) / len(cleaned)

    full_average = average(full_rebuild_seconds)
    refinement_average = average(refinement_seconds)
    if planned_full_rebuilds_remaining and full_average is None:
        return None
    if planned_refinements_remaining and refinement_average is None:
        return None
    seconds = (full_average or 0.0) * planned_full_rebuilds_remaining
    seconds += (refinement_average or 0.0) * planned_refinements_remaining
    return max(0, int(round(seconds)))


def progress_payload(
    *,
    state: str,
    stage: str,
    full_rebuilds_completed: int,
    max_full_rebuilds: int,
    refinements_completed: int,
    current_rebuild_refinements: int,
    max_refinements_per_rebuild: int,
    elapsed_seconds: float,
    eta_seconds: int | None,
    current_seed: int | None,
    latest_scores: Mapping[str, Any] | None,
    best_scores: Mapping[str, Any] | None,
    best_candidate: str | None,
    strategy: str | None,
    next_focus: str | None,
    phase_timings: Mapping[str, Sequence[float]],
) -> dict[str, Any]:
    if state not in {"running", "completed", "error"}:
        raise FidelityCostPlanError("progress state is invalid")
    if not stage or len(stage) > 120:
        raise FidelityCostPlanError("progress stage is invalid")
    if elapsed_seconds < 0:
        raise FidelityCostPlanError("elapsed_seconds is invalid")
    return {
        "format": "bodyrig-fidelity-progress",
        "version": 1,
        "state": state,
        "stage": stage,
        "full_rebuilds_completed": full_rebuilds_completed,
        "max_full_rebuilds": max_full_rebuilds,
        "refinements_completed": refinements_completed,
        "current_rebuild_refinements": current_rebuild_refinements,
        "max_refinements_per_rebuild": max_refinements_per_rebuild,
        "elapsed_seconds": int(round(elapsed_seconds)),
        "eta_seconds": eta_seconds,
        "current_seed": current_seed,
        "latest_scores": dict(latest_scores) if latest_scores is not None else None,
        "best_scores": dict(best_scores) if best_scores is not None else None,
        "best_candidate": best_candidate,
        "strategy": strategy,
        "next_focus": next_focus,
        "phase_timings": {key: [round(float(item), 3) for item in values] for key, values in phase_timings.items()},
    }

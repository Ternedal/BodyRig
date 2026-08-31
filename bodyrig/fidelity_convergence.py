from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

MEASUREMENT_FORMAT = "bodyrig-fidelity-measurement"
MEASUREMENT_VERSION = 1
DECISION_FORMAT = "bodyrig-fidelity-convergence-decision"
DECISION_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

SCORE_FIELDS = (
    "face_appearance",
    "body_silhouette",
    "hair_appearance",
    "skin_material",
    "photorealism",
    "overall",
)


class FidelityConvergenceError(ValueError):
    pass


@dataclass(frozen=True)
class FidelityPolicy:
    face_appearance: float = 0.84
    body_silhouette: float = 0.88
    hair_appearance: float = 0.78
    skin_material: float = 0.78
    photorealism: float = 0.82
    overall: float = 0.84
    min_improvement: float = 0.01
    plateau_window: int = 3
    max_iterations: int = 10

    def __post_init__(self) -> None:
        for field in SCORE_FIELDS:
            _ratio(getattr(self, field), field=f"policy.{field}")
        _ratio(self.min_improvement, field="policy.min_improvement")
        if isinstance(self.plateau_window, bool) or not 2 <= self.plateau_window <= 10:
            raise FidelityConvergenceError("policy.plateau_window must be an integer in 2..10")
        if isinstance(self.max_iterations, bool) or not 1 <= self.max_iterations <= 50:
            raise FidelityConvergenceError("policy.max_iterations must be an integer in 1..50")

    def thresholds(self) -> dict[str, float]:
        return {field: float(getattr(self, field)) for field in SCORE_FIELDS}


DEFAULT_POLICY = FidelityPolicy()


def _ratio(value: Any, *, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise FidelityConvergenceError(f"{field} must be a finite number in 0..1")
    return float(value)


def _sha(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise FidelityConvergenceError(f"{field} must be lowercase SHA-256")
    return value


def _text(value: Any, *, field: str, maximum: int = 160) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise FidelityConvergenceError(f"{field} must contain 1..{maximum} characters")
    return value.strip()


def validate_measurement(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "iteration",
        "candidate_sha256",
        "reference_set_sha256",
        "evaluator",
        "scores",
        "semantics",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise FidelityConvergenceError("fidelity measurement fields must match v1 exactly")
    if value.get("format") != MEASUREMENT_FORMAT or value.get("version") != MEASUREMENT_VERSION:
        raise FidelityConvergenceError("unsupported fidelity measurement format/version")

    iteration = value.get("iteration")
    if isinstance(iteration, bool) or not isinstance(iteration, int) or not 1 <= iteration <= 50:
        raise FidelityConvergenceError("iteration must be an integer in 1..50")

    evaluator = value.get("evaluator")
    if not isinstance(evaluator, Mapping) or set(evaluator) != {"name", "revision"}:
        raise FidelityConvergenceError("evaluator fields must match v1 exactly")
    evaluator_name = _text(evaluator.get("name"), field="evaluator.name", maximum=80)
    evaluator_revision = _text(evaluator.get("revision"), field="evaluator.revision", maximum=160)

    scores = value.get("scores")
    if not isinstance(scores, Mapping) or set(scores) != set(SCORE_FIELDS):
        raise FidelityConvergenceError("scores fields must match v1 exactly")
    normalized_scores = {field: _ratio(scores[field], field=f"scores.{field}") for field in SCORE_FIELDS}

    if value.get("semantics") != "visual-fidelity-not-identity-verification":
        raise FidelityConvergenceError("fidelity measurement semantics are invalid")

    return {
        "format": MEASUREMENT_FORMAT,
        "version": MEASUREMENT_VERSION,
        "iteration": iteration,
        "candidate_sha256": _sha(value.get("candidate_sha256"), field="candidate_sha256"),
        "reference_set_sha256": _sha(value.get("reference_set_sha256"), field="reference_set_sha256"),
        "evaluator": {"name": evaluator_name, "revision": evaluator_revision},
        "scores": normalized_scores,
        "semantics": "visual-fidelity-not-identity-verification",
    }


def _normalized_gap(scores: Mapping[str, float], thresholds: Mapping[str, float], field: str) -> float:
    threshold = thresholds[field]
    if threshold <= 0:
        return 0.0
    return max(0.0, threshold - scores[field]) / threshold


def _plateau(history: Sequence[dict[str, Any]], *, policy: FidelityPolicy) -> bool:
    if len(history) < policy.plateau_window:
        return False
    window = history[-policy.plateau_window :]
    values = [item["scores"]["overall"] for item in window]
    return max(values) - min(values) < policy.min_improvement


def _best_rank(item: Mapping[str, Any], thresholds: Mapping[str, float]) -> tuple[float, float, float, int]:
    gaps = [_normalized_gap(item["scores"], thresholds, field) for field in SCORE_FIELDS]
    return (
        max(gaps),
        sum(gaps),
        -float(item["scores"]["overall"]),
        int(item["iteration"]),
    )


def decide_convergence(
    measurements: Sequence[Mapping[str, Any]],
    *,
    policy: FidelityPolicy = DEFAULT_POLICY,
) -> dict[str, Any]:
    if not measurements:
        raise FidelityConvergenceError("at least one fidelity measurement is required")
    history = [validate_measurement(item) for item in measurements]
    expected_iterations = list(range(1, len(history) + 1))
    actual_iterations = [item["iteration"] for item in history]
    if actual_iterations != expected_iterations:
        raise FidelityConvergenceError("fidelity measurements must be contiguous and ordered from iteration 1")

    reference_set = history[0]["reference_set_sha256"]
    evaluator = history[0]["evaluator"]
    for item in history[1:]:
        if item["reference_set_sha256"] != reference_set:
            raise FidelityConvergenceError("all iterations must use the same reference set")
        if item["evaluator"] != evaluator:
            raise FidelityConvergenceError("all iterations must use the same evaluator revision")

    latest = history[-1]
    thresholds = policy.thresholds()
    unmet = [field for field in SCORE_FIELDS if latest["scores"][field] < thresholds[field]]
    next_focus = None
    if unmet:
        next_focus = max(
            unmet,
            key=lambda field: (_normalized_gap(latest["scores"], thresholds, field), field),
        )

    if not unmet:
        state = "converged"
        reason = "all likeness and photorealism thresholds are satisfied"
        strategy = "human-review"
    elif len(history) >= policy.max_iterations:
        state = "manual-review"
        reason = "current automatic iteration budget is exhausted without convergence; review the best candidate and start a retuned batch if needed"
        strategy = "manual-retune"
    elif _plateau(history, policy=policy):
        state = "plateau"
        reason = "visual-fidelity improvement has plateaued; automatically retune the candidate search and continue"
        strategy = "retune-search"
    elif next_focus in {"photorealism", "skin_material", "hair_appearance"}:
        state = "iterate"
        reason = "appearance realism remains below target; refine appearance/material search"
        strategy = "appearance-search"
    else:
        state = "iterate"
        reason = "visual likeness remains below target; generate another candidate"
        strategy = "continue-search"

    best = min(history, key=lambda item: _best_rank(item, thresholds))
    improvement = 0.0
    if len(history) > 1:
        improvement = latest["scores"]["overall"] - history[-2]["scores"]["overall"]

    return {
        "format": DECISION_FORMAT,
        "version": DECISION_VERSION,
        "state": state,
        "reason": reason,
        "strategy": strategy,
        "iteration": latest["iteration"],
        "candidate_sha256": latest["candidate_sha256"],
        "reference_set_sha256": reference_set,
        "evaluator": deepcopy(evaluator),
        "scores": deepcopy(latest["scores"]),
        "thresholds": thresholds,
        "unmet": unmet,
        "next_focus": next_focus,
        "improvement_from_previous": improvement,
        "best_iteration": best["iteration"],
        "best_candidate_sha256": best["candidate_sha256"],
        "best_scores": deepcopy(best["scores"]),
        "best_overall": best["scores"]["overall"],
        "continue_automatically": state in {"iterate", "plateau"},
        "human_visual_authority_required": True,
        "semantics": "visual-fidelity-not-identity-verification",
    }

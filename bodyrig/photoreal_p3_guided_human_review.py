from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p3_device_distillation_plan import FIDELITY_DELTA_DIMENSIONS
from .photoreal_p3_device_runtime_review_plan import (
    PhotorealP3DeviceRuntimeReviewPlanError,
    validate_device_runtime_review_plan,
)
from .photoreal_p3_physical_runtime_review import (
    EVIDENCE_FORMAT,
    EVIDENCE_VERSION,
    PhotorealP3PhysicalRuntimeReviewError,
    validate_physical_runtime_evidence,
)

PREFILL_FIELDS = {
    "format",
    "version",
    "operator_supplied",
    "runtime_review_plan_sha256",
    "target_device_family",
    "target_device_model",
    "physical_device_observed",
    "installed_student_artifacts",
    "observed_refresh_hz",
    "p95_frame_time_ms",
    "stereo_rendering_observed",
    "vr_safe_frame_pacing_observed",
    "installed_student_hashes_verified_on_device",
    "visual_results",
    "reviewed_by",
    "review_notes",
    "confirm_physical_device_review_complete",
}


class PhotorealP3GuidedHumanReviewError(RuntimeError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP3GuidedHumanReviewError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP3GuidedHumanReviewError(f"{label} must be a JSON object")
    return value


def _strict_v1(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) == 1.0
    )


def _validate_machine_prefill(
    prefill: Mapping[str, Any],
    *,
    runtime_review_plan: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        plan = validate_device_runtime_review_plan(runtime_review_plan)
    except PhotorealP3DeviceRuntimeReviewPlanError as exc:
        raise PhotorealP3GuidedHumanReviewError(
            f"runtime review plan strict readback failed: {exc}"
        ) from exc

    if set(prefill) != PREFILL_FIELDS:
        raise PhotorealP3GuidedHumanReviewError(
            "machine prefill fields do not match the v1 physical-evidence contract"
        )
    if prefill.get("format") != EVIDENCE_FORMAT or not _strict_v1(
        prefill.get("version")
    ):
        raise PhotorealP3GuidedHumanReviewError(
            "machine prefill format/version mismatch"
        )
    if prefill.get("operator_supplied") is not False:
        raise PhotorealP3GuidedHumanReviewError(
            "guided human review requires the untouched machine-safe prefill "
            "with operator_supplied=false"
        )
    if prefill.get("confirm_physical_device_review_complete") is not False:
        raise PhotorealP3GuidedHumanReviewError(
            "guided human review requires the untouched machine-safe prefill "
            "with confirmation=false"
        )
    if prefill.get("physical_device_observed") is not True:
        raise PhotorealP3GuidedHumanReviewError(
            "machine prefill does not prove a physically observed Quest device"
        )
    for field in (
        "stereo_rendering_observed",
        "vr_safe_frame_pacing_observed",
        "installed_student_hashes_verified_on_device",
    ):
        if prefill.get(field) is not True:
            raise PhotorealP3GuidedHumanReviewError(
                f"machine prefill does not contain safe machine authority: {field}"
            )
    if prefill.get("runtime_review_plan_sha256") != plan.get(
        "p3_device_runtime_review_plan_sha256"
    ):
        raise PhotorealP3GuidedHumanReviewError(
            "machine prefill belongs to a different runtime review plan"
        )
    if (
        prefill.get("target_device_family") != plan.get("target_device_family")
        or prefill.get("target_device_model") != plan.get("target_device_model")
    ):
        raise PhotorealP3GuidedHumanReviewError(
            "machine prefill targets a different device class"
        )

    visual = prefill.get("visual_results")
    if not isinstance(visual, list) or len(visual) != len(FIDELITY_DELTA_DIMENSIONS):
        raise PhotorealP3GuidedHumanReviewError(
            "machine prefill does not expose every required human fidelity criterion"
        )
    for index, criterion in enumerate(FIDELITY_DELTA_DIMENSIONS):
        item = visual[index]
        if (
            not isinstance(item, Mapping)
            or set(item) != {"criterion", "decision"}
            or item.get("criterion") != criterion
            or item.get("decision") != "REVIEW_REQUIRED"
        ):
            raise PhotorealP3GuidedHumanReviewError(
                "machine prefill visual criteria were already edited or reordered"
            )
    if prefill.get("reviewed_by") != "REVIEW_REQUIRED":
        raise PhotorealP3GuidedHumanReviewError(
            "machine prefill reviewer field was already edited"
        )
    return plan


def _parse_decisions(raw: list[str]) -> dict[str, str]:
    decisions: dict[str, str] = {}
    universe = set(FIDELITY_DELTA_DIMENSIONS)
    for token in raw:
        if "=" not in token:
            raise PhotorealP3GuidedHumanReviewError(
                "human decision must use criterion=pass or criterion=fail"
            )
        criterion, decision = token.split("=", 1)
        criterion = criterion.strip()
        decision = decision.strip().lower()
        if criterion not in universe:
            raise PhotorealP3GuidedHumanReviewError(
                f"unknown human fidelity criterion: {criterion}"
            )
        if criterion in decisions:
            raise PhotorealP3GuidedHumanReviewError(
                f"human fidelity criterion was supplied more than once: {criterion}"
            )
        if decision not in {"pass", "fail"}:
            raise PhotorealP3GuidedHumanReviewError(
                f"human fidelity decision must be pass/fail: {criterion}"
            )
        decisions[criterion] = decision

    missing = [
        criterion
        for criterion in FIDELITY_DELTA_DIMENSIONS
        if criterion not in decisions
    ]
    if missing:
        raise PhotorealP3GuidedHumanReviewError(
            "explicit human decisions are missing: " + ", ".join(missing)
        )
    return decisions


def build_reviewed_physical_evidence(
    runtime_review_plan: Mapping[str, Any],
    machine_prefill: Mapping[str, Any],
    *,
    decisions: Mapping[str, str],
    reviewed_by: str,
    review_notes: str,
    confirm_physical_device_review_complete: bool,
) -> dict[str, Any]:
    plan = _validate_machine_prefill(
        machine_prefill,
        runtime_review_plan=runtime_review_plan,
    )
    if confirm_physical_device_review_complete is not True:
        raise PhotorealP3GuidedHumanReviewError(
            "explicit physical-device review completion confirmation is required"
        )
    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise PhotorealP3GuidedHumanReviewError("reviewer identity is required")
    if not isinstance(review_notes, str) or not review_notes.strip():
        raise PhotorealP3GuidedHumanReviewError("review notes are required")

    decision_map = dict(decisions)
    if set(decision_map) != set(FIDELITY_DELTA_DIMENSIONS):
        raise PhotorealP3GuidedHumanReviewError(
            "human decisions must cover every canonical fidelity criterion exactly once"
        )
    for criterion, decision in decision_map.items():
        if decision not in {"pass", "fail"}:
            raise PhotorealP3GuidedHumanReviewError(
                f"human fidelity decision must be pass/fail: {criterion}"
            )

    candidate = copy.deepcopy(dict(machine_prefill))
    candidate["operator_supplied"] = True
    candidate["visual_results"] = [
        {
            "criterion": criterion,
            "decision": decision_map[criterion],
        }
        for criterion in FIDELITY_DELTA_DIMENSIONS
    ]
    candidate["reviewed_by"] = reviewed_by.strip()
    candidate["review_notes"] = review_notes.strip()
    candidate["confirm_physical_device_review_complete"] = True

    try:
        return validate_physical_runtime_evidence(
            candidate,
            runtime_review_plan=plan,
        )
    except PhotorealP3PhysicalRuntimeReviewError as exc:
        raise PhotorealP3GuidedHumanReviewError(
            f"completed human review evidence is invalid: {exc}"
        ) from exc


def write_reviewed_physical_evidence(
    runtime_review_plan_path: str | Path,
    machine_prefill_path: str | Path,
    *,
    output_path: str | Path,
    decisions: Mapping[str, str],
    reviewed_by: str,
    review_notes: str,
    confirm_physical_device_review_complete: bool,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    plan = _read_json(runtime_review_plan_path, label="P3 runtime review plan")
    prefill = _read_json(machine_prefill_path, label="P3 machine-safe physical prefill")
    expected = build_reviewed_physical_evidence(
        plan,
        prefill,
        decisions=decisions,
        reviewed_by=reviewed_by,
        review_notes=review_notes,
        confirm_physical_device_review_complete=confirm_physical_device_review_complete,
    )

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        if not reuse_existing:
            raise PhotorealP3GuidedHumanReviewError(
                f"reviewed physical evidence already exists: {output}"
            )
        existing = _read_json(output, label="existing reviewed physical evidence")
        try:
            normalized = validate_physical_runtime_evidence(
                existing,
                runtime_review_plan=plan,
            )
        except PhotorealP3PhysicalRuntimeReviewError as exc:
            raise PhotorealP3GuidedHumanReviewError(
                f"existing reviewed physical evidence is invalid: {exc}"
            ) from exc
        if normalized != expected:
            raise PhotorealP3GuidedHumanReviewError(
                "existing reviewed physical evidence differs from the exact current "
                "machine prefill and explicit human decisions"
            )
        return normalized

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(
                expected,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            stream.write("\n")
    except OSError as exc:
        raise PhotorealP3GuidedHumanReviewError(
            f"could not write reviewed physical evidence: {output}"
        ) from exc
    return expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Turn one exact machine-safe Quest 2 physical evidence prefill into "
            "operator-supplied human PASS/FAIL evidence without editing JSON by hand."
        )
    )
    parser.add_argument("--runtime-review-plan", type=Path, required=True)
    parser.add_argument("--machine-prefill", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--review-notes", required=True)
    parser.add_argument(
        "--decision",
        action="append",
        default=[],
        metavar="CRITERION=PASS|FAIL",
    )
    parser.add_argument(
        "--confirm-physical-device-review-complete",
        action="store_true",
    )
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)

    try:
        decisions = _parse_decisions(args.decision)
        evidence = write_reviewed_physical_evidence(
            args.runtime_review_plan,
            args.machine_prefill,
            output_path=args.out,
            decisions=decisions,
            reviewed_by=args.reviewed_by,
            review_notes=args.review_notes,
            confirm_physical_device_review_complete=(
                args.confirm_physical_device_review_complete
            ),
            reuse_existing=args.reuse_existing,
        )
    except PhotorealP3GuidedHumanReviewError as exc:
        print(f"BodyRig P3 guided human review: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "operator_supplied": evidence["operator_supplied"],
                "physical_device_observed": evidence["physical_device_observed"],
                "human_visual_decisions": len(evidence["visual_results"]),
                "confirm_physical_device_review_complete": evidence[
                    "confirm_physical_device_review_complete"
                ],
                "production_activation": False,
                "output": str(args.out.expanduser().resolve()),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

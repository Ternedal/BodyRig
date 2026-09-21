from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoreal_p3_device_distillation_plan import FIDELITY_DELTA_DIMENSIONS
from .photoreal_p3_device_distillation_runner import (
    BASE_STUDENT_REPRESENTATIONS,
    REQUIRED_STUDENT_COMPONENTS,
)
from .photoreal_p3_device_runtime_review_plan import (
    PhotorealP3DeviceRuntimeReviewPlanError,
    validate_device_runtime_review_plan,
)


EVIDENCE_FORMAT = "bodyrig-photoreal-p3-physical-runtime-evidence"
EVIDENCE_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-p3-physical-runtime-review"
RECEIPT_VERSION = 1

PERFORMANCE_CHECKS = (
    "target_refresh_achieved",
    "p95_frame_time_within_budget",
    "stereo_rendering_observed",
    "vr_safe_frame_pacing_observed",
    "installed_student_hashes_verified_on_device",
)


class PhotorealP3PhysicalRuntimeReviewError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP3PhysicalRuntimeReviewError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP3PhysicalRuntimeReviewError(
            f"{label} must be a JSON object"
        )
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP3PhysicalRuntimeReviewError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealP3PhysicalRuntimeReviewError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    clean = _text(value, label=label, maximum=64).lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealP3PhysicalRuntimeReviewError(f"{label} is invalid")
    return clean


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP3PhysicalRuntimeReviewError(
            f"{label} format/version mismatch"
        )
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP3PhysicalRuntimeReviewError(
            f"{label} format/version mismatch"
        )


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP3PhysicalRuntimeReviewError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise PhotorealP3PhysicalRuntimeReviewError(f"{label} is invalid")
    return result


def _digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical runtime artifact cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _decision_map(
    raw: Any,
    universe: Sequence[str],
    *,
    label: str,
) -> list[dict[str, str]]:
    if not isinstance(raw, list) or len(raw) != len(universe):
        raise PhotorealP3PhysicalRuntimeReviewError(
            f"{label} must cover every required criterion exactly once"
        )
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping) or set(item) != {"criterion", "decision"}:
            raise PhotorealP3PhysicalRuntimeReviewError(
                f"{label} fields must match v1 exactly"
            )
        criterion = _text(
            item.get("criterion"),
            label=f"{label} criterion",
            maximum=96,
        )
        if criterion != universe[index] or criterion in seen:
            raise PhotorealP3PhysicalRuntimeReviewError(
                f"{label} order/universe mismatch"
            )
        seen.add(criterion)
        decision = _text(
            item.get("decision"),
            label=f"{label} decision",
            maximum=16,
        ).lower()
        if decision not in {"pass", "fail"}:
            raise PhotorealP3PhysicalRuntimeReviewError(
                f"{label} decision must be pass/fail"
            )
        result.append({"criterion": criterion, "decision": decision})
    return result


def _installed_artifacts(
    evidence: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> list[dict[str, str]]:
    expected = plan.get("student_artifacts")
    raw = evidence.get("installed_student_artifacts")
    if not isinstance(expected, list) or not expected:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 runtime review plan contains no student artifacts"
        )
    if not isinstance(raw, list) or len(raw) != len(expected):
        raise PhotorealP3PhysicalRuntimeReviewError(
            "physical runtime evidence installed artifact count mismatch"
        )

    expected_map: dict[str, str] = {}
    for item in expected:
        if not isinstance(item, Mapping):
            raise PhotorealP3PhysicalRuntimeReviewError(
                "P3 runtime review plan student artifact is invalid"
            )
        relative = _text(
            item.get("relative_path"),
            label="P3 runtime review plan student artifact path",
        ).replace("\\", "/")
        expected_map[relative] = _sha(
            item.get("sha256"),
            label="P3 runtime review plan student artifact SHA-256",
        )

    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"relative_path", "sha256"}:
            raise PhotorealP3PhysicalRuntimeReviewError(
                "physical runtime evidence installed artifact fields must match v1 exactly"
            )
        relative = _text(
            item.get("relative_path"),
            label="physical runtime installed artifact path",
        ).replace("\\", "/")
        if relative in seen:
            raise PhotorealP3PhysicalRuntimeReviewError(
                "physical runtime evidence repeats installed student artifact"
            )
        seen.add(relative)
        observed = _sha(
            item.get("sha256"),
            label="physical runtime installed artifact SHA-256",
        )
        if expected_map.get(relative) != observed:
            raise PhotorealP3PhysicalRuntimeReviewError(
                "physical runtime evidence installed student bytes differ from runtime review plan"
            )
        normalized.append({"relative_path": relative, "sha256": observed})
    if seen != set(expected_map):
        raise PhotorealP3PhysicalRuntimeReviewError(
            "physical runtime evidence omitted planned student artifacts"
        )
    normalized.sort(key=lambda item: item["relative_path"])
    return normalized


def validate_physical_runtime_evidence(
    evidence: Mapping[str, Any],
    *,
    runtime_review_plan: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        plan = validate_device_runtime_review_plan(runtime_review_plan)
    except PhotorealP3DeviceRuntimeReviewPlanError as exc:
        raise PhotorealP3PhysicalRuntimeReviewError(
            f"P3 runtime review plan strict readback failed: {exc}"
        ) from exc

    expected_fields = {
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
    if set(evidence) != expected_fields or evidence.get("format") != EVIDENCE_FORMAT:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical runtime evidence fields/format mismatch"
        )
    _strict_v1(evidence.get("version"), label="P3 physical runtime evidence")
    if evidence.get("operator_supplied") is not True:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical runtime evidence must be operator supplied"
        )
    if evidence.get("physical_device_observed") is not True:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical runtime evidence must come from a physically observed device"
        )
    if evidence.get("confirm_physical_device_review_complete") is not True:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "explicit physical-device review completion confirmation is required"
        )
    if evidence.get("runtime_review_plan_sha256") != plan.get(
        "p3_device_runtime_review_plan_sha256"
    ):
        raise PhotorealP3PhysicalRuntimeReviewError(
            "physical runtime evidence targets a different runtime review plan"
        )
    if (
        evidence.get("target_device_family") != plan.get("target_device_family")
        or evidence.get("target_device_model") != plan.get("target_device_model")
    ):
        raise PhotorealP3PhysicalRuntimeReviewError(
            "physical runtime evidence targets a different device class"
        )

    installed = _installed_artifacts(evidence, plan)
    refresh = _finite(
        evidence.get("observed_refresh_hz"),
        label="physical runtime observed refresh rate",
    )
    p95 = _finite(
        evidence.get("p95_frame_time_ms"),
        label="physical runtime p95 frame time",
    )
    if refresh <= 0 or p95 <= 0:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "physical runtime performance measurements must be positive"
        )
    for field in (
        "stereo_rendering_observed",
        "vr_safe_frame_pacing_observed",
        "installed_student_hashes_verified_on_device",
    ):
        if not isinstance(evidence.get(field), bool):
            raise PhotorealP3PhysicalRuntimeReviewError(
                f"physical runtime evidence {field} must be boolean"
            )

    visual = _decision_map(
        evidence.get("visual_results"),
        FIDELITY_DELTA_DIMENSIONS,
        label="physical runtime visual result",
    )
    reviewer = _text(
        evidence.get("reviewed_by"),
        label="physical runtime reviewer",
        maximum=256,
    )
    notes = evidence.get("review_notes")
    if not isinstance(notes, str) or not notes.strip() or len(notes) > 8192:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "physical runtime review notes are invalid"
        )

    normalized: dict[str, Any] = {
        "format": EVIDENCE_FORMAT,
        "version": EVIDENCE_VERSION,
        "operator_supplied": True,
        "runtime_review_plan_sha256": plan[
            "p3_device_runtime_review_plan_sha256"
        ],
        "target_device_family": plan["target_device_family"],
        "target_device_model": plan["target_device_model"],
        "physical_device_observed": True,
        "installed_student_artifacts": installed,
        "observed_refresh_hz": refresh,
        "p95_frame_time_ms": p95,
        "stereo_rendering_observed": evidence["stereo_rendering_observed"],
        "vr_safe_frame_pacing_observed": evidence[
            "vr_safe_frame_pacing_observed"
        ],
        "installed_student_hashes_verified_on_device": evidence[
            "installed_student_hashes_verified_on_device"
        ],
        "visual_results": visual,
        "reviewed_by": reviewer,
        "review_notes": notes.strip(),
        "confirm_physical_device_review_complete": True,
    }
    return normalized


def record_physical_runtime_review(
    runtime_review_plan: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        plan = validate_device_runtime_review_plan(runtime_review_plan)
    except PhotorealP3DeviceRuntimeReviewPlanError as exc:
        raise PhotorealP3PhysicalRuntimeReviewError(str(exc)) from exc
    normalized = validate_physical_runtime_evidence(
        evidence,
        runtime_review_plan=plan,
    )

    target_refresh = _finite(
        plan["target_profile"]["target_refresh_hz"],
        label="P3 target refresh rate",
    )
    target_frame_time = _finite(
        plan["target_profile"]["max_frame_time_ms"],
        label="P3 target frame time",
    )

    performance_results = [
        {
            "criterion": "target_refresh_achieved",
            "decision": (
                "pass"
                if normalized["observed_refresh_hz"] >= target_refresh
                else "fail"
            ),
        },
        {
            "criterion": "p95_frame_time_within_budget",
            "decision": (
                "pass"
                if normalized["p95_frame_time_ms"] <= target_frame_time
                else "fail"
            ),
        },
        {
            "criterion": "stereo_rendering_observed",
            "decision": (
                "pass"
                if normalized["stereo_rendering_observed"]
                else "fail"
            ),
        },
        {
            "criterion": "vr_safe_frame_pacing_observed",
            "decision": (
                "pass"
                if normalized["vr_safe_frame_pacing_observed"]
                else "fail"
            ),
        },
        {
            "criterion": "installed_student_hashes_verified_on_device",
            "decision": (
                "pass"
                if normalized["installed_student_hashes_verified_on_device"]
                else "fail"
            ),
        },
    ]

    visual_results = list(normalized["visual_results"])
    all_pass = all(
        item["decision"] == "pass"
        for item in visual_results + performance_results
    )

    result: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "version": RECEIPT_VERSION,
        "performer_id": plan["performer_id"],
        "selected_epoch_id": plan["selected_epoch_id"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "p2_animation_plan_sha256": plan["p2_animation_plan_sha256"],
        "p2_exavatar_animation_execution_input_sha256": plan[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "p2_animated_human_review_sha256": plan[
            "p2_animated_human_review_sha256"
        ],
        "p3_device_distillation_plan_sha256": plan[
            "p3_device_distillation_plan_sha256"
        ],
        "p3_device_distillation_execution_receipt_sha256": plan[
            "p3_device_distillation_execution_receipt_sha256"
        ],
        "p3_device_runtime_review_plan_sha256": plan[
            "p3_device_runtime_review_plan_sha256"
        ],
        "target_profile_sha256": plan["target_profile_sha256"],
        "target_device_family": plan["target_device_family"],
        "target_device_model": plan["target_device_model"],
        "executed_adapter": plan["executed_adapter"],
        "executed_adapter_revision": plan["executed_adapter_revision"],
        "target_refresh_hz": target_refresh,
        "max_frame_time_ms": target_frame_time,
        "student_representation": plan["student_representation"],
        "student_components": list(plan["student_components"]),
        "installed_student_artifacts": list(
            normalized["installed_student_artifacts"]
        ),
        "observed_refresh_hz": normalized["observed_refresh_hz"],
        "p95_frame_time_ms": normalized["p95_frame_time_ms"],
        "stereo_rendering_observed": normalized["stereo_rendering_observed"],
        "vr_safe_frame_pacing_observed": normalized[
            "vr_safe_frame_pacing_observed"
        ],
        "installed_student_hashes_verified_on_device": normalized[
            "installed_student_hashes_verified_on_device"
        ],
        "visual_results": visual_results,
        "performance_results": performance_results,
        "reviewed_by": normalized["reviewed_by"],
        "review_notes": normalized["review_notes"],
        "physical_device_evidence_present": True,
        "physical_device_review_complete": True,
        "runtime_review_status": "pass" if all_pass else "fail",
        "runtime_acceptance_authority": all_pass,
        "photoreal_acceptance_authority": all_pass,
        "production_activation": False,
    }
    result["p3_physical_runtime_review_sha256"] = _digest(
        result,
        omit="p3_physical_runtime_review_sha256",
    )
    return validate_physical_runtime_review_receipt(result)


def validate_physical_runtime_review_receipt(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_animated_human_review_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_execution_receipt_sha256",
        "p3_device_runtime_review_plan_sha256",
        "target_profile_sha256",
        "target_device_family",
        "target_device_model",
        "executed_adapter",
        "executed_adapter_revision",
        "target_refresh_hz",
        "max_frame_time_ms",
        "student_representation",
        "student_components",
        "installed_student_artifacts",
        "observed_refresh_hz",
        "p95_frame_time_ms",
        "stereo_rendering_observed",
        "vr_safe_frame_pacing_observed",
        "installed_student_hashes_verified_on_device",
        "visual_results",
        "performance_results",
        "reviewed_by",
        "review_notes",
        "physical_device_evidence_present",
        "physical_device_review_complete",
        "runtime_review_status",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_physical_runtime_review_sha256",
    }
    if set(value) != expected_fields or value.get("format") != RECEIPT_FORMAT:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical runtime review receipt fields/format mismatch"
        )
    _strict_v1(value.get("version"), label="P3 physical runtime review receipt")
    _text(value.get("performer_id"), label="P3 physical review performer", maximum=256)
    _text(value.get("selected_epoch_id"), label="P3 physical review epoch", maximum=256)
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_animated_human_review_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_execution_receipt_sha256",
        "p3_device_runtime_review_plan_sha256",
        "target_profile_sha256",
    ):
        _sha(value.get(field), label=f"P3 physical review {field}")

    if value.get("target_device_family") != "meta-quest":
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical review target family is not canonical"
        )
    if value.get("target_device_model") not in {"quest-2", "quest-3", "quest-3s"}:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical review target model is not canonical"
        )
    _text(
        value.get("executed_adapter"),
        label="P3 physical review executed adapter",
        maximum=80,
    )
    _sha(
        value.get("executed_adapter_revision"),
        label="P3 physical review executed adapter revision",
    )
    if value.get("student_representation") not in BASE_STUDENT_REPRESENTATIONS:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical review student representation is not canonical"
        )
    components = value.get("student_components")
    if components != list(REQUIRED_STUDENT_COMPONENTS):
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical review required student components mismatch"
        )

    artifacts = value.get("installed_student_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical review installed student artifact evidence is missing"
        )
    seen: set[str] = set()
    for item in artifacts:
        if not isinstance(item, Mapping) or set(item) != {"relative_path", "sha256"}:
            raise PhotorealP3PhysicalRuntimeReviewError(
                "P3 physical review installed artifact fields must match v1 exactly"
            )
        relative = _text(
            item.get("relative_path"),
            label="P3 physical review installed artifact path",
        ).replace("\\", "/")
        if relative in seen:
            raise PhotorealP3PhysicalRuntimeReviewError(
                "P3 physical review repeats installed artifact"
            )
        seen.add(relative)
        _sha(
            item.get("sha256"),
            label="P3 physical review installed artifact SHA-256",
        )

    target_refresh = _finite(
        value.get("target_refresh_hz"),
        label="P3 physical review target refresh",
    )
    target_frame_time = _finite(
        value.get("max_frame_time_ms"),
        label="P3 physical review target frame time",
    )
    refresh = _finite(
        value.get("observed_refresh_hz"),
        label="P3 physical review observed refresh",
    )
    p95 = _finite(
        value.get("p95_frame_time_ms"),
        label="P3 physical review p95 frame time",
    )
    if min(target_refresh, target_frame_time, refresh, p95) <= 0:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical review performance values must be positive"
        )
    for field in (
        "stereo_rendering_observed",
        "vr_safe_frame_pacing_observed",
        "installed_student_hashes_verified_on_device",
    ):
        if not isinstance(value.get(field), bool):
            raise PhotorealP3PhysicalRuntimeReviewError(
                f"P3 physical review {field} must be boolean"
            )

    visual = _decision_map(
        value.get("visual_results"),
        FIDELITY_DELTA_DIMENSIONS,
        label="P3 physical review visual result",
    )
    performance = _decision_map(
        value.get("performance_results"),
        PERFORMANCE_CHECKS,
        label="P3 physical review performance result",
    )
    expected_performance = [
        {
            "criterion": "target_refresh_achieved",
            "decision": "pass" if refresh >= target_refresh else "fail",
        },
        {
            "criterion": "p95_frame_time_within_budget",
            "decision": "pass" if p95 <= target_frame_time else "fail",
        },
        {
            "criterion": "stereo_rendering_observed",
            "decision": "pass" if value["stereo_rendering_observed"] else "fail",
        },
        {
            "criterion": "vr_safe_frame_pacing_observed",
            "decision": "pass" if value["vr_safe_frame_pacing_observed"] else "fail",
        },
        {
            "criterion": "installed_student_hashes_verified_on_device",
            "decision": (
                "pass"
                if value["installed_student_hashes_verified_on_device"]
                else "fail"
            ),
        },
    ]
    if performance != expected_performance:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical review performance results do not match raw device evidence"
        )
    all_pass = all(
        item["decision"] == "pass"
        for item in visual + performance
    )
    status = _text(
        value.get("runtime_review_status"),
        label="P3 physical review status",
        maximum=16,
    ).lower()
    if status not in {"pass", "fail"} or (status == "pass") is not all_pass:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical review status does not match detailed results"
        )
    for field, expected in (
        ("physical_device_evidence_present", True),
        ("physical_device_review_complete", True),
        ("runtime_acceptance_authority", all_pass),
        ("photoreal_acceptance_authority", all_pass),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3PhysicalRuntimeReviewError(
                f"P3 physical review authority mismatch: {field}"
            )
    _text(value.get("reviewed_by"), label="P3 physical review reviewer", maximum=256)
    notes = value.get("review_notes")
    if not isinstance(notes, str) or not notes.strip() or len(notes) > 8192:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical review notes are invalid"
        )
    claimed = _sha(
        value.get("p3_physical_runtime_review_sha256"),
        label="P3 physical runtime review SHA-256",
    )
    if _digest(value, omit="p3_physical_runtime_review_sha256") != claimed:
        raise PhotorealP3PhysicalRuntimeReviewError(
            "P3 physical runtime review digest mismatch"
        )
    return dict(value)


def record_physical_runtime_review_files(
    runtime_review_plan_path: str | Path,
    evidence_path: str | Path,
    *,
    output_path: str | Path,
) -> dict[str, Any]:
    plan = _read_json(
        runtime_review_plan_path,
        label="P3 device runtime review plan",
    )
    evidence = _read_json(
        evidence_path,
        label="P3 physical runtime evidence",
    )
    result = record_physical_runtime_review(plan, evidence)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealP3PhysicalRuntimeReviewError(
            f"P3 physical runtime review receipt already exists: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(
            result,
            stream,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        stream.write("\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Record explicit physical Meta Quest runtime evidence and human "
            "photoreal PASS/FAIL for an exact BodyRig P3 student package."
        )
    )
    parser.add_argument("--runtime-review-plan", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = record_physical_runtime_review_files(
            args.runtime_review_plan,
            args.evidence,
            output_path=args.out,
        )
    except PhotorealP3PhysicalRuntimeReviewError as exc:
        print(f"BodyRig P3 physical runtime review: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": receipt["runtime_review_status"].upper(),
                "physical_device_evidence_present": True,
                "runtime_acceptance_authority": receipt[
                    "runtime_acceptance_authority"
                ],
                "photoreal_acceptance_authority": receipt[
                    "photoreal_acceptance_authority"
                ],
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

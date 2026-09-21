from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p3_device_distillation_plan import (
    FIDELITY_DELTA_DIMENSIONS,
    PhotorealP3DeviceDistillationPlanError,
    validate_device_target_profile,
    validate_p3_device_distillation_plan,
)
from .photoreal_p3_device_distillation_runner import (
    ARTIFACT_FIELDS,
    BASE_STUDENT_REPRESENTATIONS,
    MEASUREMENT_FIELDS,
    REQUIRED_STUDENT_COMPONENTS,
    PhotorealP3DeviceDistillationRunnerError,
    validate_execution_receipt,
)


FORMAT = "bodyrig-photoreal-p3-device-runtime-review-plan"
VERSION = 1


class PhotorealP3DeviceRuntimeReviewPlanError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            f"{label} must be a JSON object"
        )
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP3DeviceRuntimeReviewPlanError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealP3DeviceRuntimeReviewPlanError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    clean = _text(value, label=label, maximum=64).lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealP3DeviceRuntimeReviewPlanError(f"{label} is invalid")
    return clean


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            f"{label} format/version mismatch"
        )
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            f"{label} format/version mismatch"
        )


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP3DeviceRuntimeReviewPlanError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise PhotorealP3DeviceRuntimeReviewPlanError(f"{label} is invalid")
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
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review plan cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            f"required student artifact is missing/not regular: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(value: Any, *, label: str) -> str:
    clean = _text(value, label=label).replace("\\", "/")
    first = clean.split("/", 1)[0]
    if (
        clean.startswith("/")
        or clean.startswith("../")
        or "/../" in f"/{clean}/"
        or ":" in first
    ):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            f"{label} escapes its root"
        )
    return clean


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative_path(relative, label=label)
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            f"{label} escapes its root"
        ) from exc
    return clean, target


def _verify_student_artifacts(
    execution: Mapping[str, Any],
    *,
    student_output_root: str | Path,
) -> list[dict[str, Any]]:
    root = Path(student_output_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            f"P3 student output root is missing/not regular: {root}"
        )
    raw_artifacts = execution.get("student_artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 distillation receipt contains no student artifacts"
        )

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_artifacts:
        if not isinstance(raw, Mapping) or set(raw) != ARTIFACT_FIELDS:
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                "P3 runtime review student artifact fields must match v1 exactly"
            )
        kind = _text(
            raw.get("kind"),
            label="P3 runtime review student artifact kind",
            maximum=64,
        )
        relative, path = _safe_child(
            root,
            raw.get("relative_path"),
            label="P3 runtime review student artifact path",
        )
        if relative in seen or relative == "distillation-manifest.json":
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                "P3 runtime review student artifact path is repeated/reserved"
            )
        seen.add(relative)
        size = raw.get("size_bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != size
        ):
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                f"P3 runtime review student artifact size/path drifted: {relative}"
            )
        expected_sha = _sha(
            raw.get("sha256"),
            label="P3 runtime review student artifact SHA-256",
        )
        observed_sha = _file_sha(path)
        if observed_sha != expected_sha:
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                f"P3 runtime review student artifact bytes drifted: {relative}"
            )
        normalized.append(
            {
                "kind": kind,
                "relative_path": relative,
                "size_bytes": size,
                "sha256": observed_sha,
            }
        )

    root_manifest = (root / "distillation-manifest.json").resolve()
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.resolve() != root_manifest
    }
    if actual != seen:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 student output artifact universe drifted before runtime review"
        )
    normalized.sort(key=lambda item: item["relative_path"])
    return normalized


def _normalize_measurements(raw: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(raw, list)
        or len(raw) != len(FIDELITY_DELTA_DIMENSIONS)
    ):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review fidelity delta universe is incomplete"
        )
    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping) or set(item) != MEASUREMENT_FIELDS:
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                "P3 runtime review fidelity delta fields must match v1 exactly"
            )
        dimension = _text(
            item.get("dimension"),
            label="P3 runtime review fidelity dimension",
            maximum=80,
        )
        if dimension != FIDELITY_DELTA_DIMENSIONS[index]:
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                "P3 runtime review fidelity delta order/universe mismatch"
            )
        result.append(
            {
                "dimension": dimension,
                "metric": _text(
                    item.get("metric"),
                    label="P3 runtime review fidelity metric",
                    maximum=160,
                ),
                "value": _finite(
                    item.get("value"),
                    label="P3 runtime review fidelity delta value",
                ),
                "unit": _text(
                    item.get("unit"),
                    label="P3 runtime review fidelity unit",
                    maximum=80,
                ),
                "teacher_reference": _text(
                    item.get("teacher_reference"),
                    label="P3 runtime review teacher reference",
                    maximum=512,
                ),
                "student_reference": _text(
                    item.get("student_reference"),
                    label="P3 runtime review student reference",
                    maximum=512,
                ),
            }
        )
    return result


def build_device_runtime_review_plan(
    distillation_plan: Mapping[str, Any],
    execution_receipt: Mapping[str, Any],
    *,
    student_output_root: str | Path,
) -> dict[str, Any]:
    try:
        plan = validate_p3_device_distillation_plan(distillation_plan)
    except PhotorealP3DeviceDistillationPlanError as exc:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            f"P3 distillation plan strict readback failed: {exc}"
        ) from exc
    try:
        execution = validate_execution_receipt(execution_receipt)
    except PhotorealP3DeviceDistillationRunnerError as exc:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            f"P3 distillation execution receipt strict readback failed: {exc}"
        ) from exc

    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_animated_human_review_sha256",
        "target_profile_sha256",
    ):
        if execution.get(field) != plan.get(field):
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                f"P3 distillation execution/plan lineage mismatch: {field}"
            )
    if execution.get("p3_device_distillation_plan_sha256") != plan.get(
        "p3_device_distillation_plan_sha256"
    ):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 distillation execution targets a different plan"
        )
    if execution.get("artifact_bytes_verified_by_core") is not True:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 distillation execution lacks core artifact verification"
        )
    if execution.get("staged_teacher_only") is not True:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 distillation execution did not preserve staged-teacher-only boundary"
        )
    if execution.get("student_fidelity_claim_exceeds_teacher") is not False:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 student claims fidelity above accepted teacher"
        )
    for field in (
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        if execution.get(field) is not False:
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                f"P3 execution already crossed runtime authority: {field}"
            )
    if execution.get("human_runtime_visual_acceptance_required") is not True:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 execution removed human runtime visual review"
        )

    representation = execution.get("student_representation")
    if representation not in BASE_STUDENT_REPRESENTATIONS:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review base student representation is not canonical"
        )
    if execution.get("student_components") != list(REQUIRED_STUDENT_COMPONENTS):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review student lacks required eye/hair components"
        )

    profile = plan.get("target_profile")
    if not isinstance(profile, Mapping):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review target profile is invalid"
        )
    try:
        normalized_profile = validate_device_target_profile(profile)
    except PhotorealP3DeviceDistillationPlanError as exc:
        raise PhotorealP3DeviceRuntimeReviewPlanError(str(exc)) from exc
    if _digest(normalized_profile) != plan.get("target_profile_sha256"):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review target profile digest mismatch"
        )

    artifacts = _verify_student_artifacts(
        execution,
        student_output_root=student_output_root,
    )
    measurements = _normalize_measurements(
        execution.get("fidelity_delta_measurements")
    )

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
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
        "p3_device_distillation_request_sha256": execution[
            "p3_device_distillation_request_sha256"
        ],
        "p3_device_distillation_execution_receipt_sha256": execution[
            "p3_device_distillation_execution_receipt_sha256"
        ],
        "target_profile": normalized_profile,
        "target_profile_sha256": plan["target_profile_sha256"],
        "target_device_family": normalized_profile["target_family"],
        "target_device_model": normalized_profile["target_model"],
        "student_representation": representation,
        "student_components": list(REQUIRED_STUDENT_COMPONENTS),
        "student_artifact_count": len(artifacts),
        "student_artifacts": artifacts,
        "student_artifact_bytes_reverified": True,
        "fidelity_delta_measurements": measurements,
        "fidelity_delta_dimension_count": len(measurements),
        "teacher_remains_visual_authority": True,
        "student_fidelity_claim_exceeds_teacher": False,
        "physical_device_installation_required": True,
        "physical_device_evidence_required": True,
        "physical_device_evidence_present": False,
        "human_runtime_visual_acceptance_required": True,
        "runtime_review_ready": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p3_device_runtime_review_plan_sha256"] = _digest(
        result,
        omit="p3_device_runtime_review_plan_sha256",
    )
    return validate_device_runtime_review_plan(result)


def validate_device_runtime_review_plan(
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
        "p3_device_distillation_request_sha256",
        "p3_device_distillation_execution_receipt_sha256",
        "target_profile",
        "target_profile_sha256",
        "target_device_family",
        "target_device_model",
        "student_representation",
        "student_components",
        "student_artifact_count",
        "student_artifacts",
        "student_artifact_bytes_reverified",
        "fidelity_delta_measurements",
        "fidelity_delta_dimension_count",
        "teacher_remains_visual_authority",
        "student_fidelity_claim_exceeds_teacher",
        "physical_device_installation_required",
        "physical_device_evidence_required",
        "physical_device_evidence_present",
        "human_runtime_visual_acceptance_required",
        "runtime_review_ready",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_device_runtime_review_plan_sha256",
    }
    if set(value) != expected_fields or value.get("format") != FORMAT:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review plan fields/format mismatch"
        )
    _strict_v1(value.get("version"), label="P3 runtime review plan")
    _text(value.get("performer_id"), label="P3 runtime review performer", maximum=256)
    _text(value.get("selected_epoch_id"), label="P3 runtime review epoch", maximum=256)
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_animated_human_review_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "p3_device_distillation_execution_receipt_sha256",
        "target_profile_sha256",
    ):
        _sha(value.get(field), label=f"P3 runtime review plan {field}")

    profile = value.get("target_profile")
    if not isinstance(profile, Mapping):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review target profile is invalid"
        )
    try:
        normalized_profile = validate_device_target_profile(profile)
    except PhotorealP3DeviceDistillationPlanError as exc:
        raise PhotorealP3DeviceRuntimeReviewPlanError(str(exc)) from exc
    if _digest(normalized_profile) != value.get("target_profile_sha256"):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review target profile digest mismatch"
        )
    if (
        value.get("target_device_family") != normalized_profile["target_family"]
        or value.get("target_device_model") != normalized_profile["target_model"]
    ):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review target device binding mismatch"
        )

    if value.get("student_representation") not in BASE_STUDENT_REPRESENTATIONS:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review student representation is not canonical"
        )
    if value.get("student_components") != list(REQUIRED_STUDENT_COMPONENTS):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review required student components mismatch"
        )

    artifacts = value.get("student_artifacts")
    count = value.get("student_artifact_count")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count < 1
        or not isinstance(artifacts, list)
        or len(artifacts) != count
    ):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review student artifact count mismatch"
        )
    normalized_artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != ARTIFACT_FIELDS:
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                "P3 runtime review student artifact fields must match v1 exactly"
            )
        relative = _relative_path(
            raw.get("relative_path"),
            label="P3 runtime review student artifact path",
        )
        if relative in seen:
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                "P3 runtime review repeats student artifact"
            )
        seen.add(relative)
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                "P3 runtime review student artifact size is invalid"
            )
        normalized_artifacts.append(
            {
                "kind": _text(
                    raw.get("kind"),
                    label="P3 runtime review artifact kind",
                    maximum=64,
                ),
                "relative_path": relative,
                "size_bytes": size,
                "sha256": _sha(
                    raw.get("sha256"),
                    label="P3 runtime review artifact SHA-256",
                ),
            }
        )
    if artifacts != sorted(
        normalized_artifacts,
        key=lambda item: item["relative_path"],
    ):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review student artifact universe is not canonical"
        )
    if value.get("student_artifact_bytes_reverified") is not True:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review student artifact bytes were not reverified"
        )

    measurements = _normalize_measurements(
        value.get("fidelity_delta_measurements")
    )
    delta_count = value.get("fidelity_delta_dimension_count")
    if (
        isinstance(delta_count, bool)
        or not isinstance(delta_count, int)
        or delta_count != len(FIDELITY_DELTA_DIMENSIONS)
        or delta_count != len(measurements)
    ):
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review fidelity delta count mismatch"
        )

    for field, expected in (
        ("teacher_remains_visual_authority", True),
        ("student_fidelity_claim_exceeds_teacher", False),
        ("physical_device_installation_required", True),
        ("physical_device_evidence_required", True),
        ("physical_device_evidence_present", False),
        ("human_runtime_visual_acceptance_required", True),
        ("runtime_review_ready", True),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                f"P3 runtime review authority mismatch: {field}"
            )

    claimed = _sha(
        value.get("p3_device_runtime_review_plan_sha256"),
        label="P3 runtime review plan SHA-256",
    )
    if _digest(value, omit="p3_device_runtime_review_plan_sha256") != claimed:
        raise PhotorealP3DeviceRuntimeReviewPlanError(
            "P3 runtime review plan digest mismatch"
        )
    return dict(value)


def build_device_runtime_review_plan_files(
    distillation_plan_path: str | Path,
    execution_receipt_path: str | Path,
    *,
    student_output_root: str | Path,
    output_path: str | Path,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    result = build_device_runtime_review_plan(
        _read_json(distillation_plan_path, label="P3 distillation plan"),
        _read_json(
            execution_receipt_path,
            label="P3 distillation execution receipt",
        ),
        student_output_root=student_output_root,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        if not reuse_existing:
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                f"P3 runtime review plan already exists: {output}"
            )
        existing = _read_json(
            output,
            label="existing P3 runtime review plan",
        )
        if validate_device_runtime_review_plan(existing) != result:
            raise PhotorealP3DeviceRuntimeReviewPlanError(
                "existing P3 runtime review plan differs from current student bytes"
            )
        return existing
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
            "Prepare an exact physical Quest runtime review plan from the "
            "core-owned P3 execution receipt and current student bytes."
        )
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--execution-receipt", type=Path, required=True)
    parser.add_argument("--student-output-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = build_device_runtime_review_plan_files(
            args.plan,
            args.execution_receipt,
            student_output_root=args.student_output_root,
            output_path=args.out,
            reuse_existing=args.reuse_existing,
        )
    except PhotorealP3DeviceRuntimeReviewPlanError as exc:
        print(
            f"BodyRig P3 device runtime review plan: FAIL: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": "P3_PHYSICAL_RUNTIME_REVIEW_READY",
                "target_device_model": result["target_device_model"],
                "student_representation": result["student_representation"],
                "student_components": result["student_components"],
                "student_artifact_count": result["student_artifact_count"],
                "physical_device_evidence_present": False,
                "runtime_acceptance_authority": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .photoreal_device_distillation_authority import (
    PhotorealDeviceDistillationAuthorityError,
    validate_device_distillation_plan,
)
from .photoreal_device_distillation_execution_receipt import (
    PhotorealDeviceDistillationExecutionReceiptError,
    validate_device_distillation_execution_receipt,
)

FORMAT = "bodyrig-photoreal-device-runtime-review-plan"
VERSION = 1


class PhotorealDeviceRuntimeReviewPlanError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealDeviceRuntimeReviewPlanError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealDeviceRuntimeReviewPlanError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealDeviceRuntimeReviewPlanError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealDeviceRuntimeReviewPlanError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealDeviceRuntimeReviewPlanError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealDeviceRuntimeReviewPlanError(f"{label} is invalid")
    return clean


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_without(value: Mapping[str, Any], key: str) -> str:
    payload = {name: item for name, item in value.items() if name != key}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _safe_child(root: Path, relative: Any) -> tuple[str, Path]:
    clean = _text(relative, label="student artifact relative path").replace("\\", "/")
    first = clean.split("/", 1)[0]
    if clean.startswith("/") or clean.startswith("../") or "/../" in f"/{clean}/" or ":" in first:
        raise PhotorealDeviceRuntimeReviewPlanError("student artifact path escapes output root")
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealDeviceRuntimeReviewPlanError("student artifact path escapes output root") from exc
    return clean, target


def build_device_runtime_review_plan(
    distillation_plan: Mapping[str, Any],
    distillation_execution_receipt: Mapping[str, Any],
    *,
    student_output_root: str | Path,
) -> dict[str, Any]:
    try:
        plan = validate_device_distillation_plan(distillation_plan)
    except PhotorealDeviceDistillationAuthorityError as exc:
        raise PhotorealDeviceRuntimeReviewPlanError(str(exc)) from exc
    try:
        execution = validate_device_distillation_execution_receipt(distillation_execution_receipt)
    except PhotorealDeviceDistillationExecutionReceiptError as exc:
        raise PhotorealDeviceRuntimeReviewPlanError(str(exc)) from exc

    for key in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "teacher_manifest_sha256",
        "static_teacher_review_sha256",
        "animation_plan_sha256",
        "animation_execution_receipt_sha256",
        "animated_teacher_review_sha256",
        "target_profile_sha256",
    ):
        if execution.get(key) != plan.get(key):
            raise PhotorealDeviceRuntimeReviewPlanError(f"distillation execution/plan lineage mismatch: {key}")
    if execution.get("device_distillation_plan_sha256") != plan.get("device_distillation_plan_sha256"):
        raise PhotorealDeviceRuntimeReviewPlanError("distillation execution targets a different P3 plan")
    if execution.get("runtime_acceptance_authority") is not False:
        raise PhotorealDeviceRuntimeReviewPlanError("distillation execution already claims runtime acceptance")
    if execution.get("human_runtime_visual_acceptance_required") is not True:
        raise PhotorealDeviceRuntimeReviewPlanError("distillation execution removed human runtime review")

    root = Path(student_output_root).expanduser().resolve()
    if not root.is_dir():
        raise PhotorealDeviceRuntimeReviewPlanError(f"student output root not found: {root}")
    artifacts = execution.get("student_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealDeviceRuntimeReviewPlanError("distillation execution receipt has no student artifacts")
    normalized_artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping):
            raise PhotorealDeviceRuntimeReviewPlanError("student artifact entry is invalid")
        relative, path = _safe_child(root, raw.get("relative_path"))
        if relative in seen:
            raise PhotorealDeviceRuntimeReviewPlanError("distillation execution repeats student artifact")
        seen.add(relative)
        if not path.is_file():
            raise PhotorealDeviceRuntimeReviewPlanError(f"student artifact is missing: {relative}")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1 or path.stat().st_size != size:
            raise PhotorealDeviceRuntimeReviewPlanError(f"student artifact size drifted: {relative}")
        observed_sha = _hash_file(path)
        declared_sha = _sha(raw.get("sha256"), label="student artifact SHA-256")
        if observed_sha != declared_sha:
            raise PhotorealDeviceRuntimeReviewPlanError(f"student artifact bytes drifted: {relative}")
        normalized_artifacts.append(
            {
                "kind": _text(raw.get("kind"), label="student artifact kind", maximum=64),
                "relative_path": relative,
                "size_bytes": size,
                "sha256": observed_sha,
            }
        )
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "distillation-manifest.json"
    }
    if actual != seen:
        raise PhotorealDeviceRuntimeReviewPlanError("student output artifact universe drifted before runtime review planning")

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": plan["performer_id"],
        "selected_epoch_id": plan["selected_epoch_id"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "teacher_manifest_sha256": plan["teacher_manifest_sha256"],
        "static_teacher_review_sha256": plan["static_teacher_review_sha256"],
        "animation_plan_sha256": plan["animation_plan_sha256"],
        "animation_execution_receipt_sha256": plan["animation_execution_receipt_sha256"],
        "animated_teacher_review_sha256": plan["animated_teacher_review_sha256"],
        "device_distillation_plan_sha256": plan["device_distillation_plan_sha256"],
        "device_distillation_execution_receipt_sha256": execution["device_distillation_execution_receipt_sha256"],
        "target_profile": plan["target_profile"],
        "target_profile_sha256": plan["target_profile_sha256"],
        "student_representation": execution["student_representation"],
        "student_artifact_count": len(normalized_artifacts),
        "student_artifacts": sorted(normalized_artifacts, key=lambda item: item["relative_path"]),
        "student_artifact_bytes_reverified": True,
        "fidelity_delta_measurements": execution["fidelity_delta_measurements"],
        "teacher_remains_visual_authority": True,
        "student_fidelity_claim_exceeds_teacher": False,
        "physical_device_evidence_required": True,
        "physical_device_evidence_present": False,
        "human_runtime_visual_acceptance_required": True,
        "runtime_review_ready": True,
        "runtime_acceptance_authority": False,
        "production_activation": False,
    }
    result["device_runtime_review_plan_sha256"] = _digest_without(result, "device_runtime_review_plan_sha256")
    return result


def build_device_runtime_review_plan_files(
    distillation_plan_path: str | Path,
    distillation_execution_receipt_path: str | Path,
    student_output_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan = _read_json(distillation_plan_path, label="device distillation plan")
    execution = _read_json(distillation_execution_receipt_path, label="device distillation execution receipt")
    result = build_device_runtime_review_plan(plan, execution, student_output_root=student_output_root)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealDeviceRuntimeReviewPlanError(f"device runtime review plan already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result

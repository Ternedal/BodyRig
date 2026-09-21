from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from .logged_process import LoggedProcessError, run_logged_process
from .photoreal_p2_animation_plan import REQUIRED_CAMERA_FIELDS, REQUIRED_SMPLX_FIELDS
from .photoreal_p2_motion_evidence import (
    PhotorealP2MotionEvidenceError,
    validate_motion_evidence_handoff,
    validate_private_motion_index,
)
from .photoreal_p2_motion_input_plan import (
    PhotorealP2MotionInputPlanError,
    validate_motion_input_plan,
)
from .photoreal_p2_motion_selection import (
    PhotorealP2MotionSelectionError,
    validate_motion_source_selection,
)
from .photoreal_scan_plan import FORMAT as SCAN_PLAN_FORMAT, VERSION as SCAN_PLAN_VERSION


CONFIG_FORMAT = "bodyrig-photoreal-p2-motion-preparation-config"
CONFIG_VERSION = 1
REQUEST_FORMAT = "bodyrig-photoreal-p2-motion-preparation-request"
REQUEST_VERSION = 1
MANIFEST_FORMAT = "bodyrig-photoreal-p2-motion-preparation-manifest"
MANIFEST_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-p2-motion-preparation-receipt"
RECEIPT_VERSION = 1
MAX_TIMEOUT_SECONDS = 604800
PINNED_ADAPTER = "bodyrig-exavatar-motion-preparation-v1"
PINNED_FITTING_BACKEND = "pinned-exavatar-fitting-v1"
PINNED_CAMERA_MODE = "virtual"
SUPPORTED_NORMALIZATION_ACTIONS = (
    "preserve-flat-mono-video",
    "exact-authorized-deprojection",
)
PROJECTION_AUTHORITY_FORMATS = {
    "bodyrig-spherical-v2-projection-authority",
    "bodyrig-explicit-projection-authority",
}


class PhotorealP2MotionPreparationRunnerError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2MotionPreparationRunnerError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealP2MotionPreparationRunnerError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise PhotorealP2MotionPreparationRunnerError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2MotionPreparationRunnerError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealP2MotionPreparationRunnerError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2MotionPreparationRunnerError(f"{label} format/version mismatch")
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2MotionPreparationRunnerError(f"{label} format/version mismatch")


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP2MotionPreparationRunnerError(f"required file is missing/not regular: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    try:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealP2MotionPreparationRunnerError(
            "P2 motion preparation artifact cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(raw).hexdigest()


def _relative_path(value: Any, *, label: str) -> str:
    clean = _text(value, label=label).replace("\\", "/")
    first = clean.split("/", 1)[0]
    if clean.startswith("/") or clean.startswith("../") or "/../" in f"/{clean}/" or ":" in first:
        raise PhotorealP2MotionPreparationRunnerError(f"{label} escapes its root")
    return clean


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative_path(relative, label=label)
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealP2MotionPreparationRunnerError(f"{label} escapes its root") from exc
    return clean, target


def validate_motion_preparation_config(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "format",
        "version",
        "adapter",
        "revision",
        "command",
        "timeout_seconds",
        "motion_fitting_backend",
        "motion_fitting_camera_mode",
        "supported_normalization_actions",
        "reports_exact_motion_path_contract",
    }
    if set(value) != expected:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation config fields must match v1 exactly")
    if value.get("format") != CONFIG_FORMAT:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation config format/version mismatch")
    _strict_v1(value.get("version"), label="P2 motion preparation config")
    if value.get("adapter") != PINNED_ADAPTER:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation adapter mismatch")
    revision = _text(value.get("revision"), label="P2 motion preparation adapter revision", maximum=160)
    command = value.get("command")
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 64
        or any(not isinstance(item, str) or not item or len(item) > 4096 for item in command)
    ):
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation command must be a non-empty argv list")
    timeout = value.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise PhotorealP2MotionPreparationRunnerError(
            f"P2 motion preparation timeout must be an integer in 1..{MAX_TIMEOUT_SECONDS}"
        )
    if value.get("motion_fitting_backend") != PINNED_FITTING_BACKEND:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation fitting backend mismatch")
    if value.get("motion_fitting_camera_mode") != PINNED_CAMERA_MODE:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation camera mode mismatch")
    if value.get("supported_normalization_actions") != list(SUPPORTED_NORMALIZATION_ACTIONS):
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation normalization universe mismatch")
    if value.get("reports_exact_motion_path_contract") is not True:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation adapter does not report exact motion-path contract")
    return {
        "format": CONFIG_FORMAT,
        "version": CONFIG_VERSION,
        "adapter": PINNED_ADAPTER,
        "revision": revision,
        "command": list(command),
        "timeout_seconds": timeout,
        "motion_fitting_backend": PINNED_FITTING_BACKEND,
        "motion_fitting_camera_mode": PINNED_CAMERA_MODE,
        "supported_normalization_actions": list(SUPPORTED_NORMALIZATION_ACTIONS),
        "reports_exact_motion_path_contract": True,
    }


def _scan_sources(scan_plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if scan_plan.get("format") != SCAN_PLAN_FORMAT:
        raise PhotorealP2MotionPreparationRunnerError("P0 scan plan format/version mismatch")
    _strict_v1(scan_plan.get("version"), label="P0 scan plan")
    if SCAN_PLAN_VERSION != 1:
        raise PhotorealP2MotionPreparationRunnerError("unsupported compiled scan-plan version")
    if scan_plan.get("all_sources_sha256_bound") is not True:
        raise PhotorealP2MotionPreparationRunnerError("P0 scan plan is not source-SHA bound")
    if scan_plan.get("train_evaluation_assignment_inherited") is not True:
        raise PhotorealP2MotionPreparationRunnerError("P0 scan plan lost train/evaluation assignment")
    if scan_plan.get("build_only") is not True or scan_plan.get("runtime_dependency") is not False:
        raise PhotorealP2MotionPreparationRunnerError("P0 scan plan build/runtime boundary is invalid")
    if scan_plan.get("production_activation") is not False:
        raise PhotorealP2MotionPreparationRunnerError("P0 scan plan crossed production authority")
    values = scan_plan.get("sources")
    if not isinstance(values, list) or not values:
        raise PhotorealP2MotionPreparationRunnerError("P0 scan plan has no sources")
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionPreparationRunnerError("P0 scan plan source is invalid")
        key = _text(raw.get("source_key"), label="P0 scan-plan source key")
        if key in result:
            raise PhotorealP2MotionPreparationRunnerError("P0 scan plan repeats source key")
        result[key] = dict(raw)
    return result


def _task_request(task: Mapping[str, Any], scan_source: Mapping[str, Any]) -> dict[str, Any]:
    for field in ("source_key", "group_id", "split", "source_sha256"):
        expected = task.get(field)
        observed = scan_source.get(
            "source_sha256" if field == "source_sha256" else field
        )
        if observed != expected:
            raise PhotorealP2MotionPreparationRunnerError(
                f"P2 motion task/P0 scan-plan binding mismatch: {field}"
            )
    if scan_source.get("kind") != "video":
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation requires video source")
    projection = _text(scan_source.get("projection"), label="P0 motion projection", maximum=128)
    stereo = _text(scan_source.get("stereo_layout"), label="P0 motion stereo layout", maximum=128)
    action = task.get("normalization_action")
    authority = scan_source.get("projection_authority")

    if action == "preserve-flat-mono-video":
        if projection != "flat" or stereo != "mono":
            raise PhotorealP2MotionPreparationRunnerError("direct P2 motion source is not flat mono in P0 authority")
        if authority is not None:
            raise PhotorealP2MotionPreparationRunnerError("flat mono P2 source unexpectedly carries projection authority")
    elif action == "exact-authorized-deprojection":
        if not isinstance(authority, Mapping):
            raise PhotorealP2MotionPreparationRunnerError("spatial P2 motion source lacks P0 projection authority")
        version = authority.get("version")
        if (
            authority.get("format") not in PROJECTION_AUTHORITY_FORMATS
            or isinstance(version, bool)
            or version != 1
            or authority.get("deprojection_authority") is not False
        ):
            raise PhotorealP2MotionPreparationRunnerError("spatial P2 motion projection authority is invalid")
        if authority.get("projection_type") != projection:
            raise PhotorealP2MotionPreparationRunnerError("spatial P2 motion projection authority type mismatch")
    else:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion normalization action is unsupported")

    size = task.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion task source size is invalid")
    source_path = Path(_text(task.get("resolved_path"), label="P2 motion source path")).expanduser().resolve()
    if not source_path.is_file() or source_path.is_symlink():
        raise PhotorealP2MotionPreparationRunnerError(f"P2 motion source is missing/not regular: {source_path}")
    if source_path.stat().st_size != size:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion source size drifted before preparation")

    return {
        "source_ref": _text(task.get("source_ref"), label="P2 motion source ref", maximum=64),
        "group_ref": _text(task.get("group_ref"), label="P2 motion group ref", maximum=64),
        "split": _text(task.get("split"), label="P2 motion split", maximum=32),
        "role": _text(task.get("role"), label="P2 motion role", maximum=64),
        "source_key": _text(task.get("source_key"), label="P2 motion source key"),
        "group_id": _text(task.get("group_id"), label="P2 motion group id"),
        "resolved_path": str(source_path),
        "source_sha256": _sha(task.get("source_sha256"), label="P2 motion source SHA-256"),
        "size_bytes": size,
        "projection": projection,
        "stereo_layout": stereo,
        "projection_authority": dict(authority) if isinstance(authority, Mapping) else None,
        "normalization_action": action,
        "motion_fitting_backend": PINNED_FITTING_BACKEND,
        "motion_fitting_camera_mode": PINNED_CAMERA_MODE,
        "source_media_rehash_required": False,
    }


def build_motion_preparation_request(
    config: Mapping[str, Any],
    handoff: Mapping[str, Any],
    private_index: Mapping[str, Any],
    selection: Mapping[str, Any],
    input_plan: Mapping[str, Any],
    scan_plan: Mapping[str, Any],
    *,
    scan_plan_file_sha256: str,
) -> dict[str, Any]:
    cfg = validate_motion_preparation_config(config)
    try:
        h = validate_motion_evidence_handoff(handoff)
        p = validate_private_motion_index(private_index, handoff=h)
        s = validate_motion_source_selection(selection, handoff=h, private_index=p)
        plan = validate_motion_input_plan(
            input_plan,
            handoff=h,
            private_index=p,
            selection=s,
        )
    except (
        PhotorealP2MotionEvidenceError,
        PhotorealP2MotionSelectionError,
        PhotorealP2MotionInputPlanError,
    ) as exc:
        raise PhotorealP2MotionPreparationRunnerError(
            f"P2 motion preparation authority readback failed: {exc}"
        ) from exc

    if _text(scan_plan.get("performer_id"), label="P0 scan-plan performer", maximum=256) != plan["performer_id"]:
        raise PhotorealP2MotionPreparationRunnerError("P0 scan plan performer differs from P2 motion plan")
    scan_sources = _scan_sources(scan_plan)
    tasks: list[dict[str, Any]] = []
    for raw in list(plan["motion_driver_tasks"]) + list(plan["held_out_motion_validation_tasks"]):
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionPreparationRunnerError("P2 motion input task is invalid")
        source_key = _text(raw.get("source_key"), label="P2 motion source key")
        scan_source = scan_sources.get(source_key)
        if scan_source is None:
            raise PhotorealP2MotionPreparationRunnerError("P2 selected motion source is absent from P0 scan plan")
        tasks.append(_task_request(raw, scan_source))
    tasks.sort(key=lambda item: (item["split"], item["source_ref"]))

    return {
        "format": REQUEST_FORMAT,
        "version": REQUEST_VERSION,
        "performer_id": plan["performer_id"],
        "selected_epoch_id": plan["selected_epoch_id"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "p2_animation_plan_sha256": plan["p2_animation_plan_sha256"],
        "p2_motion_evidence_handoff_sha256": plan["p2_motion_evidence_handoff_sha256"],
        "p2_motion_private_index_sha256": plan["p2_motion_private_index_sha256"],
        "p2_motion_source_selection_sha256": plan["p2_motion_source_selection_sha256"],
        "p2_motion_input_plan_sha256": plan["p2_motion_input_plan_sha256"],
        "p0_scan_plan_file_sha256": _sha(
            scan_plan_file_sha256,
            label="P0 scan-plan file SHA-256",
        ),
        "adapter": cfg["adapter"],
        "adapter_revision": cfg["revision"],
        "motion_fitting_backend": PINNED_FITTING_BACKEND,
        "motion_fitting_camera_mode": PINNED_CAMERA_MODE,
        "tasks": tasks,
        "task_count": len(tasks),
        "source_media_rehash_required": False,
        "source_media_rehash_performed": False,
        "evaluation_appearance_training_authorized": False,
        "motion_input_preparation_execution_authorized": True,
        "p2_animation_execution_authorized": False,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def _artifact_records(
    values: Any,
    *,
    output_root: Path,
    task_root: Path,
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(values, list) or not values:
        raise PhotorealP2MotionPreparationRunnerError(f"{label} has no output artifacts")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, Mapping) or set(raw) != {"relative_path", "size_bytes", "sha256"}:
            raise PhotorealP2MotionPreparationRunnerError(f"{label} artifact fields must match v1 exactly")
        relative, path = _safe_child(output_root, raw.get("relative_path"), label=f"{label} artifact path")
        try:
            path.relative_to(task_root.resolve())
        except ValueError as exc:
            raise PhotorealP2MotionPreparationRunnerError(f"{label} artifact escapes task root") from exc
        if relative in seen:
            raise PhotorealP2MotionPreparationRunnerError(f"{label} repeats output artifact")
        seen.add(relative)
        if not path.is_file() or path.is_symlink():
            raise PhotorealP2MotionPreparationRunnerError(f"{label} artifact is missing/not regular: {relative}")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1 or path.stat().st_size != size:
            raise PhotorealP2MotionPreparationRunnerError(f"{label} artifact size mismatch: {relative}")
        observed = _file_sha(path)
        if observed != _sha(raw.get("sha256"), label=f"{label} artifact SHA-256"):
            raise PhotorealP2MotionPreparationRunnerError(f"{label} artifact SHA-256 mismatch: {relative}")
        result.append({"relative_path": relative, "size_bytes": size, "sha256": observed})
    return sorted(result, key=lambda item: item["relative_path"])


def _motion_contract(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    task_prefix: str,
) -> tuple[int, list[int]]:
    prefix = task_prefix.rstrip("/") + "/"
    frame_ids: set[int] = set()
    camera_ids: set[int] = set()
    smplx_ids: set[int] = set()
    by_path = {str(item["relative_path"]): item for item in artifacts}
    for relative in by_path:
        if not relative.startswith(prefix):
            continue
        local = relative[len(prefix):]
        if local.startswith("frames/") and local.endswith(".png"):
            stem = local[len("frames/") : -4]
            if stem.isdigit():
                frame_ids.add(int(stem))
        elif local.startswith("cam_params/") and local.endswith(".json"):
            stem = local[len("cam_params/") : -5]
            if stem.isdigit():
                camera_ids.add(int(stem))
        elif local.startswith("smplx_optimized/smplx_params_smoothed/") and local.endswith(".json"):
            stem = local[len("smplx_optimized/smplx_params_smoothed/") : -5]
            if stem.isdigit():
                smplx_ids.add(int(stem))
    if not frame_ids or frame_ids != camera_ids or frame_ids != smplx_ids:
        raise PhotorealP2MotionPreparationRunnerError(
            "prepared P2 motion path does not have aligned frame/camera/SMPL-X ids"
        )
    return len(frame_ids), sorted(frame_ids)


def _validate_parameter_jsons(
    output_root: Path,
    *,
    task_prefix: str,
    frame_ids: Sequence[int],
) -> None:
    prefix = Path(task_prefix)
    for frame_id in frame_ids:
        camera_path = output_root / prefix / "cam_params" / f"{frame_id}.json"
        smplx_path = (
            output_root
            / prefix
            / "smplx_optimized"
            / "smplx_params_smoothed"
            / f"{frame_id}.json"
        )
        camera = _read_json(camera_path, label="prepared P2 camera parameters")
        smplx = _read_json(smplx_path, label="prepared P2 SMPL-X parameters")
        if not set(REQUIRED_CAMERA_FIELDS).issubset(camera):
            raise PhotorealP2MotionPreparationRunnerError("prepared P2 camera parameters omit required fields")
        if not set(REQUIRED_SMPLX_FIELDS).issubset(smplx):
            raise PhotorealP2MotionPreparationRunnerError("prepared P2 SMPL-X parameters omit required fields")


def validate_motion_preparation_manifest(
    value: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_motion_input_plan_sha256",
        "p0_scan_plan_file_sha256",
        "adapter",
        "adapter_revision",
        "motion_fitting_backend",
        "motion_fitting_camera_mode",
        "task_results",
        "task_count",
        "source_media_rehash_performed",
        "evaluation_appearance_training_authorized",
        "motion_input_preparation_complete",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    }
    if set(value) != expected_fields:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation manifest fields must match v1 exactly")
    if value.get("format") != MANIFEST_FORMAT:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation manifest format/version mismatch")
    _strict_v1(value.get("version"), label="P2 motion preparation manifest")
    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_motion_input_plan_sha256",
        "p0_scan_plan_file_sha256",
        "adapter",
        "adapter_revision",
        "motion_fitting_backend",
        "motion_fitting_camera_mode",
    ):
        if value.get(field) != request.get(field):
            raise PhotorealP2MotionPreparationRunnerError(f"P2 motion preparation manifest provenance mismatch: {field}")
    for field, expected in (
        ("source_media_rehash_performed", False),
        ("evaluation_appearance_training_authorized", False),
        ("motion_input_preparation_complete", True),
        ("p2_animation_execution_authorized", False),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP2MotionPreparationRunnerError(f"P2 motion preparation manifest authority mismatch: {field}")

    request_by_ref = {item["source_ref"]: item for item in request["tasks"]}
    results = value.get("task_results")
    task_count = value.get("task_count")
    if (
        not isinstance(results, list)
        or isinstance(task_count, bool)
        or not isinstance(task_count, int)
        or task_count != len(results)
        or len(results) != len(request_by_ref)
    ):
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation task result count mismatch")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    listed_artifacts: set[str] = {"motion-preparation-manifest.json"}
    for raw in results:
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation task result is invalid")
        expected_task_fields = {
            "source_ref",
            "split",
            "role",
            "normalization_action",
            "motion_path_relative",
            "frame_count",
            "source_media_rehash_performed",
            "artifacts",
        }
        if set(raw) != expected_task_fields:
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation task result fields must match v1 exactly")
        source_ref = _text(raw.get("source_ref"), label="prepared P2 source ref", maximum=64)
        if source_ref in seen or source_ref not in request_by_ref:
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation task result source universe mismatch")
        seen.add(source_ref)
        task = request_by_ref[source_ref]
        for field in ("split", "role", "normalization_action"):
            if raw.get(field) != task.get(field):
                raise PhotorealP2MotionPreparationRunnerError(f"P2 motion preparation task provenance mismatch: {field}")
        if raw.get("source_media_rehash_performed") is not False:
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation unexpectedly rehashed source media")
        motion_path = _relative_path(raw.get("motion_path_relative"), label="prepared P2 motion path")
        if motion_path != f"tasks/{source_ref}/motion":
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation task motion path is not canonical")
        _, task_root = _safe_child(output_root, f"tasks/{source_ref}", label="prepared P2 task root")
        artifacts = _artifact_records(
            raw.get("artifacts"),
            output_root=output_root,
            task_root=task_root,
            label="P2 motion preparation task",
        )
        frame_count, frame_ids = _motion_contract(artifacts, task_prefix=motion_path)
        if raw.get("frame_count") != frame_count:
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation frame count mismatch")
        _validate_parameter_jsons(output_root, task_prefix=motion_path, frame_ids=frame_ids)
        listed_artifacts.update(item["relative_path"] for item in artifacts)
        normalized.append(
            {
                "source_ref": source_ref,
                "split": task["split"],
                "role": task["role"],
                "normalization_action": task["normalization_action"],
                "motion_path_relative": motion_path,
                "frame_count": frame_count,
                "source_media_rehash_performed": False,
                "artifacts": artifacts,
            }
        )
    if seen != set(request_by_ref):
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation omitted selected source task")

    actual_files = {
        path.relative_to(output_root).as_posix()
        for path in output_root.rglob("*")
        if path.is_file()
    }
    if actual_files != listed_artifacts:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation output artifact universe mismatch")

    result = dict(value)
    result["task_results"] = sorted(normalized, key=lambda item: item["source_ref"])
    return result


def build_motion_preparation_receipt(
    manifest: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "version": RECEIPT_VERSION,
        "performer_id": manifest["performer_id"],
        "selected_epoch_id": manifest["selected_epoch_id"],
        "teacher_input_sha256": manifest["teacher_input_sha256"],
        "p2_animation_plan_sha256": manifest["p2_animation_plan_sha256"],
        "p2_motion_evidence_handoff_sha256": request["p2_motion_evidence_handoff_sha256"],
        "p2_motion_private_index_sha256": request["p2_motion_private_index_sha256"],
        "p2_motion_source_selection_sha256": request["p2_motion_source_selection_sha256"],
        "p2_motion_input_plan_sha256": manifest["p2_motion_input_plan_sha256"],
        "p0_scan_plan_file_sha256": manifest["p0_scan_plan_file_sha256"],
        "adapter": manifest["adapter"],
        "adapter_revision": manifest["adapter_revision"],
        "motion_fitting_backend": manifest["motion_fitting_backend"],
        "motion_fitting_camera_mode": manifest["motion_fitting_camera_mode"],
        "task_results": manifest["task_results"],
        "task_count": manifest["task_count"],
        "generated_artifact_bytes_verified_by_core": True,
        "source_media_rehash_performed": False,
        "evaluation_appearance_training_authorized": False,
        "motion_input_preparation_complete": True,
        "p2_animation_execution_authorized": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p2_motion_preparation_receipt_sha256"] = _digest(
        result,
        omit="p2_motion_preparation_receipt_sha256",
    )
    return result


def validate_motion_preparation_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_motion_evidence_handoff_sha256",
        "p2_motion_private_index_sha256",
        "p2_motion_source_selection_sha256",
        "p2_motion_input_plan_sha256",
        "p0_scan_plan_file_sha256",
        "adapter",
        "adapter_revision",
        "motion_fitting_backend",
        "motion_fitting_camera_mode",
        "task_results",
        "task_count",
        "generated_artifact_bytes_verified_by_core",
        "source_media_rehash_performed",
        "evaluation_appearance_training_authorized",
        "motion_input_preparation_complete",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_motion_preparation_receipt_sha256",
    }
    if set(value) != expected:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt fields must match v1 exactly")
    if value.get("format") != RECEIPT_FORMAT:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt format/version mismatch")
    _strict_v1(value.get("version"), label="P2 motion preparation receipt")
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_motion_evidence_handoff_sha256",
        "p2_motion_private_index_sha256",
        "p2_motion_source_selection_sha256",
        "p2_motion_input_plan_sha256",
        "p0_scan_plan_file_sha256",
    ):
        _sha(value.get(field), label=f"P2 motion preparation receipt {field}")
    if value.get("motion_fitting_backend") != PINNED_FITTING_BACKEND:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt fitting backend mismatch")
    if value.get("motion_fitting_camera_mode") != PINNED_CAMERA_MODE:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt camera mode mismatch")
    tasks = value.get("task_results")
    count = value.get("task_count")
    if (
        not isinstance(tasks, list)
        or not tasks
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(tasks)
    ):
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt task count mismatch")
    seen_refs: set[str] = set()
    for raw in tasks:
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt task result is invalid")
        expected_task_fields = {
            "source_ref",
            "split",
            "role",
            "normalization_action",
            "motion_path_relative",
            "frame_count",
            "source_media_rehash_performed",
            "artifacts",
        }
        if set(raw) != expected_task_fields:
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt task fields must match v1 exactly")
        source_ref = _text(raw.get("source_ref"), label="P2 motion preparation receipt source ref", maximum=64)
        if source_ref in seen_refs:
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt repeats source ref")
        seen_refs.add(source_ref)
        if raw.get("split") not in {"train", "evaluation"}:
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt split is invalid")
        if raw.get("role") not in {"motion-driver", "held-out-motion-validation"}:
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt role is invalid")
        if raw.get("normalization_action") not in SUPPORTED_NORMALIZATION_ACTIONS:
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt normalization action is invalid")
        if raw.get("motion_path_relative") != f"tasks/{source_ref}/motion":
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt motion path is not canonical")
        frame_count = raw.get("frame_count")
        if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count < 1:
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt frame count is invalid")
        if raw.get("source_media_rehash_performed") is not False:
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt unexpectedly claims source rehash")
        artifacts = raw.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt has no task artifacts")
        seen_paths: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, Mapping) or set(artifact) != {"relative_path", "size_bytes", "sha256"}:
                raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt artifact fields must match v1 exactly")
            relative = _relative_path(artifact.get("relative_path"), label="P2 motion preparation receipt artifact path")
            if relative in seen_paths or not relative.startswith(f"tasks/{source_ref}/"):
                raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt artifact universe mismatch")
            seen_paths.add(relative)
            size = artifact.get("size_bytes")
            if isinstance(size, bool) or not isinstance(size, int) or size < 1:
                raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt artifact size is invalid")
            _sha(artifact.get("sha256"), label="P2 motion preparation receipt artifact SHA-256")
    for field, expected_value in (
        ("generated_artifact_bytes_verified_by_core", True),
        ("source_media_rehash_performed", False),
        ("evaluation_appearance_training_authorized", False),
        ("motion_input_preparation_complete", True),
        ("p2_animation_execution_authorized", True),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected_value:
            raise PhotorealP2MotionPreparationRunnerError(f"P2 motion preparation receipt authority mismatch: {field}")
    declared = _sha(
        value.get("p2_motion_preparation_receipt_sha256"),
        label="P2 motion preparation receipt SHA-256",
    )
    if _digest(value, omit="p2_motion_preparation_receipt_sha256") != declared:
        raise PhotorealP2MotionPreparationRunnerError("P2 motion preparation receipt digest mismatch")
    return dict(value)


def run_motion_preparation(
    config: Mapping[str, Any],
    handoff: Mapping[str, Any],
    private_index: Mapping[str, Any],
    selection: Mapping[str, Any],
    input_plan: Mapping[str, Any],
    scan_plan: Mapping[str, Any],
    *,
    scan_plan_file_sha256: str,
    workspace: str | Path,
) -> dict[str, Any]:
    cfg = validate_motion_preparation_config(config)
    request = build_motion_preparation_request(
        cfg,
        handoff,
        private_index,
        selection,
        input_plan,
        scan_plan,
        scan_plan_file_sha256=scan_plan_file_sha256,
    )
    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealP2MotionPreparationRunnerError(f"P2 motion preparation workspace already exists: {root}")
    root.mkdir(parents=True)
    output_root = root / "output"
    output_root.mkdir()
    request_path = root / "request.json"
    log_path = root / "adapter.log"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    invocation = [
        *list(cfg["command"]),
        "--bodyrig-request",
        str(request_path),
        "--bodyrig-output",
        str(output_root),
        "--bodyrig-adapter",
        cfg["adapter"],
        "--bodyrig-revision",
        cfg["revision"],
    ]
    try:
        completed = run_logged_process(
            invocation,
            log_path=log_path,
            timeout_seconds=cfg["timeout_seconds"],
        )
    except subprocess.TimeoutExpired as exc:
        raise PhotorealP2MotionPreparationRunnerError(
            f"P2 motion preparation adapter timed out after {cfg['timeout_seconds']} seconds"
        ) from exc
    except (OSError, LoggedProcessError) as exc:
        raise PhotorealP2MotionPreparationRunnerError(
            f"P2 motion preparation adapter process could not complete: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise PhotorealP2MotionPreparationRunnerError(
            f"P2 motion preparation adapter failed with exit code {completed.returncode}"
        )

    manifest_path = output_root / "motion-preparation-manifest.json"
    if not manifest_path.is_file():
        raise PhotorealP2MotionPreparationRunnerError(
            "P2 motion preparation adapter did not create motion-preparation-manifest.json"
        )
    manifest = validate_motion_preparation_manifest(
        _read_json(manifest_path, label="P2 motion preparation manifest"),
        request=request,
        output_root=output_root,
    )
    receipt = build_motion_preparation_receipt(manifest, request=request)
    receipt_path = root / "motion-preparation-receipt.json"
    with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return validate_motion_preparation_receipt(receipt)


def run_motion_preparation_files(
    config_path: str | Path,
    handoff_path: str | Path,
    private_index_path: str | Path,
    selection_path: str | Path,
    input_plan_path: str | Path,
    scan_plan_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    scan_path = Path(scan_plan_path).expanduser().resolve()
    return run_motion_preparation(
        _read_json(config_path, label="P2 motion preparation config"),
        _read_json(handoff_path, label="P2 motion evidence handoff"),
        _read_json(private_index_path, label="private P2 motion source index"),
        _read_json(selection_path, label="P2 motion source selection"),
        _read_json(input_plan_path, label="P2 motion input plan"),
        _read_json(scan_path, label="P0 scan plan"),
        scan_plan_file_sha256=_file_sha(scan_path),
        workspace=workspace,
    )

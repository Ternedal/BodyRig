from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from .logged_process import LoggedProcessError, run_logged_process
from .photoreal_animation_authority import (
    PhotorealAnimationAuthorityError,
    require_animation_execution_authority,
)
from .photoreal_animation_plan import ANIMATION_REQUIREMENTS

CONFIG_FORMAT = "bodyrig-photoreal-animation-config"
CONFIG_VERSION = 1
REQUEST_FORMAT = "bodyrig-photoreal-animation-request"
REQUEST_VERSION = 1
RESULT_FORMAT = "bodyrig-photoreal-animation-manifest"
RESULT_VERSION = 1
MAX_TIMEOUT_SECONDS = 604800

CONFIG_FIELDS = {
    "format",
    "version",
    "adapter",
    "revision",
    "representation",
    "command",
    "timeout_seconds",
    "supported_validation_dimensions",
    "body_correspondence_policy",
    "face_control_policy",
}
RESULT_FIELDS = {
    "format",
    "version",
    "performer_id",
    "selected_epoch_id",
    "teacher_input_sha256",
    "teacher_manifest_sha256",
    "static_teacher_review_sha256",
    "animation_plan_sha256",
    "adapter",
    "adapter_revision",
    "representation",
    "animation_complete",
    "consumed_teacher_artifacts",
    "implemented_validation_dimensions",
    "animation_artifacts",
    "animated_teacher_acceptance_authority",
    "human_animated_visual_acceptance_required",
    "p3_device_distillation_authorized",
    "production_activation",
}
ARTIFACT_FIELDS = {"kind", "relative_path", "size_bytes", "sha256"}
CONSUMED_FIELDS = {"relative_path", "sha256"}


class PhotorealAnimationRunnerError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealAnimationRunnerError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAnimationRunnerError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimationRunnerError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealAnimationRunnerError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimationRunnerError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealAnimationRunnerError(f"{label} is invalid")
    return clean


def _numeric_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealAnimationRunnerError(f"{label} version must be numeric v1")
    if not math.isfinite(float(value)) or value != 1:
        raise PhotorealAnimationRunnerError(f"{label} version must be numeric v1")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(value: Any, *, label: str) -> str:
    clean = _text(value, label=label).replace("\\", "/")
    first = clean.split("/", 1)[0]
    if clean.startswith("/") or clean.startswith("../") or "/../" in f"/{clean}/" or ":" in first:
        raise PhotorealAnimationRunnerError(f"{label} escapes its root")
    return clean


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative_path(relative, label=label)
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealAnimationRunnerError(f"{label} escapes its root") from exc
    return clean, target


def validate_animation_config(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != CONFIG_FIELDS:
        raise PhotorealAnimationRunnerError("animation config fields must match v1 exactly")
    if value.get("format") != CONFIG_FORMAT:
        raise PhotorealAnimationRunnerError("animation config format mismatch")
    _numeric_v1(value.get("version"), label="animation config")
    adapter = _text(value.get("adapter"), label="animation adapter", maximum=80)
    if any(not (ch.isalnum() or ch in "._-") for ch in adapter):
        raise PhotorealAnimationRunnerError("animation adapter name is invalid")
    revision = _text(value.get("revision"), label="animation adapter revision", maximum=160)
    representation = _text(value.get("representation"), label="animation representation", maximum=160)
    command = value.get("command")
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 64
        or any(not isinstance(item, str) or not item or len(item) > 4096 for item in command)
    ):
        raise PhotorealAnimationRunnerError("animation config command must be a non-empty argv list")
    timeout = value.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise PhotorealAnimationRunnerError(
            f"animation config timeout_seconds must be an integer in 1..{MAX_TIMEOUT_SECONDS}"
        )
    dimensions = value.get("supported_validation_dimensions")
    if dimensions != list(ANIMATION_REQUIREMENTS):
        raise PhotorealAnimationRunnerError("animation adapter does not support the canonical P2 validation universe")
    if value.get("body_correspondence_policy") != "canonical-skeleton-smplx-correspondence-v1":
        raise PhotorealAnimationRunnerError("animation config body correspondence policy mismatch")
    if value.get("face_control_policy") != "explicit-facial-expression-representation-v1":
        raise PhotorealAnimationRunnerError("animation config face control policy mismatch")
    return {
        "format": CONFIG_FORMAT,
        "version": CONFIG_VERSION,
        "adapter": adapter,
        "revision": revision,
        "representation": representation,
        "command": list(command),
        "timeout_seconds": timeout,
        "supported_validation_dimensions": list(dimensions),
        "body_correspondence_policy": value["body_correspondence_policy"],
        "face_control_policy": value["face_control_policy"],
    }


def load_animation_config(path: str | Path) -> dict[str, Any]:
    return validate_animation_config(_read_json(path, label="photoreal animation config"))


def _validate_teacher_root(plan: Mapping[str, Any], root: Path) -> None:
    if not root.is_dir():
        raise PhotorealAnimationRunnerError(f"teacher output root not found: {root}")
    expected: set[str] = set()
    for raw in plan["teacher_artifacts"]:
        relative, path = _safe_child(root, raw.get("relative_path"), label="teacher artifact relative path")
        if relative in expected:
            raise PhotorealAnimationRunnerError("animation plan repeats teacher artifact path")
        expected.add(relative)
        if not path.is_file():
            raise PhotorealAnimationRunnerError(f"teacher artifact is missing before animation: {relative}")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or path.stat().st_size != size:
            raise PhotorealAnimationRunnerError(f"teacher artifact size drifted before animation: {relative}")
        if _hash_file(path) != _sha(raw.get("sha256"), label="teacher artifact SHA-256"):
            raise PhotorealAnimationRunnerError(f"teacher artifact bytes drifted before animation: {relative}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "teacher-manifest.json"
    }
    if actual != expected:
        raise PhotorealAnimationRunnerError("teacher artifact universe drifted before animation")


def build_animation_request(
    config: Mapping[str, Any],
    animation_plan: Mapping[str, Any],
    *,
    teacher_output_root: str | Path,
) -> dict[str, Any]:
    config = validate_animation_config(config)
    try:
        plan = require_animation_execution_authority(animation_plan)
    except PhotorealAnimationAuthorityError as exc:
        raise PhotorealAnimationRunnerError(str(exc)) from exc
    root = Path(teacher_output_root).expanduser().resolve()
    _validate_teacher_root(plan, root)
    return {
        "format": REQUEST_FORMAT,
        "version": REQUEST_VERSION,
        "performer_id": plan["performer_id"],
        "selected_epoch_id": plan["selected_epoch_id"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "teacher_manifest_sha256": plan["teacher_manifest_sha256"],
        "static_teacher_review_sha256": plan["static_teacher_review_sha256"],
        "animation_plan_sha256": plan["animation_plan_sha256"],
        "adapter": config["adapter"],
        "adapter_revision": config["revision"],
        "representation": config["representation"],
        "teacher_artifacts": plan["teacher_artifacts"],
        "required_validation_dimensions": list(ANIMATION_REQUIREMENTS),
        "body_correspondence_policy": plan["body_correspondence_policy"],
        "face_control_policy": plan["face_control_policy"],
        "static_teacher_photoreal_accepted": True,
        "p2_animation_execution_authorized": True,
        "animated_teacher_acceptance_authority": False,
        "human_animated_visual_acceptance_required": True,
        "p3_device_distillation_authorized": False,
        "production_activation": False,
    }


def _consumed_teacher_universe(request: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in request["teacher_artifacts"]:
        relative = _relative_path(raw.get("relative_path"), label="request teacher artifact relative path")
        if relative in result:
            raise PhotorealAnimationRunnerError("animation request repeats teacher artifact")
        result[relative] = _sha(raw.get("sha256"), label="request teacher artifact SHA-256")
    return result


def validate_animation_result(
    value: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    if set(value) != RESULT_FIELDS:
        raise PhotorealAnimationRunnerError("animation manifest fields must match v1 exactly")
    if value.get("format") != RESULT_FORMAT:
        raise PhotorealAnimationRunnerError("animation manifest format mismatch")
    _numeric_v1(value.get("version"), label="animation manifest")
    for key in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "teacher_manifest_sha256",
        "static_teacher_review_sha256",
        "animation_plan_sha256",
        "adapter",
        "adapter_revision",
        "representation",
    ):
        if value.get(key) != request.get(key):
            raise PhotorealAnimationRunnerError(f"animation manifest provenance mismatch: {key}")
    if value.get("animation_complete") is not True:
        raise PhotorealAnimationRunnerError("animation adapter did not report complete execution")
    if value.get("implemented_validation_dimensions") != list(ANIMATION_REQUIREMENTS):
        raise PhotorealAnimationRunnerError("animation adapter did not implement the canonical P2 validation universe")
    if value.get("animated_teacher_acceptance_authority") is not False:
        raise PhotorealAnimationRunnerError("animation adapter crossed animated-teacher acceptance authority")
    if value.get("human_animated_visual_acceptance_required") is not True:
        raise PhotorealAnimationRunnerError("animation adapter removed human animated visual acceptance")
    if value.get("p3_device_distillation_authorized") is not False:
        raise PhotorealAnimationRunnerError("animation adapter prematurely authorized P3 distillation")
    if value.get("production_activation") is not False:
        raise PhotorealAnimationRunnerError("animation adapter crossed production authority")

    teacher_universe = _consumed_teacher_universe(request)
    consumed = value.get("consumed_teacher_artifacts")
    if not isinstance(consumed, list) or not consumed:
        raise PhotorealAnimationRunnerError("animation manifest contains no consumed teacher artifacts")
    normalized_consumed: list[dict[str, str]] = []
    seen_consumed: set[str] = set()
    for raw in consumed:
        if not isinstance(raw, Mapping) or set(raw) != CONSUMED_FIELDS:
            raise PhotorealAnimationRunnerError("consumed teacher artifact fields must match v1 exactly")
        relative = _relative_path(raw.get("relative_path"), label="consumed teacher artifact relative path")
        if relative in seen_consumed:
            raise PhotorealAnimationRunnerError("animation manifest repeats consumed teacher artifact")
        seen_consumed.add(relative)
        observed_sha = _sha(raw.get("sha256"), label="consumed teacher artifact SHA-256")
        expected_sha = teacher_universe.get(relative)
        if expected_sha is None or observed_sha != expected_sha:
            raise PhotorealAnimationRunnerError("animation manifest consumed unauthorized teacher artifact bytes")
        normalized_consumed.append({"relative_path": relative, "sha256": observed_sha})

    artifacts = value.get("animation_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealAnimationRunnerError("animation manifest contains no animation artifacts")
    normalized_artifacts: list[dict[str, Any]] = []
    listed: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != ARTIFACT_FIELDS:
            raise PhotorealAnimationRunnerError("animation artifact fields must match v1 exactly")
        kind = _text(raw.get("kind"), label="animation artifact kind", maximum=64)
        relative, path = _safe_child(output_dir, raw.get("relative_path"), label="animation artifact relative path")
        if relative == "animation-manifest.json" or relative in listed:
            raise PhotorealAnimationRunnerError("animation artifact path is repeated or reserved")
        listed.add(relative)
        if not path.is_file():
            raise PhotorealAnimationRunnerError(f"animation artifact is missing: {relative}")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1 or size != path.stat().st_size:
            raise PhotorealAnimationRunnerError(f"animation artifact size mismatch: {relative}")
        observed_sha = _hash_file(path)
        if observed_sha != _sha(raw.get("sha256"), label="animation artifact SHA-256"):
            raise PhotorealAnimationRunnerError(f"animation artifact SHA-256 mismatch: {relative}")
        normalized_artifacts.append(
            {
                "kind": kind,
                "relative_path": relative,
                "size_bytes": size,
                "sha256": observed_sha,
            }
        )
    actual = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != "animation-manifest.json"
    }
    if actual != listed:
        raise PhotorealAnimationRunnerError("animation output artifact universe differs from animation manifest")

    result = dict(value)
    result["consumed_teacher_artifacts"] = sorted(normalized_consumed, key=lambda item: item["relative_path"])
    result["animation_artifacts"] = sorted(normalized_artifacts, key=lambda item: item["relative_path"])
    return result


def _log_tail(path: Path, limit: int = 8000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[-limit:].decode("utf-8", errors="replace").strip()


def run_external_animation(
    config: Mapping[str, Any],
    animation_plan: Mapping[str, Any],
    *,
    teacher_output_root: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = validate_animation_config(config)
    teacher_root = Path(teacher_output_root).expanduser().resolve()
    request = build_animation_request(config, animation_plan, teacher_output_root=teacher_root)
    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealAnimationRunnerError(f"animation workspace already exists: {root}")
    root.mkdir(parents=True)
    request_path = root / "request.json"
    output_dir = root / "output"
    log_path = root / "adapter.log"
    output_dir.mkdir()
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    invoke = [
        *list(config["command"]),
        "--bodyrig-request",
        str(request_path),
        "--bodyrig-teacher-root",
        str(teacher_root),
        "--bodyrig-output",
        str(output_dir),
        "--bodyrig-adapter",
        config["adapter"],
        "--bodyrig-revision",
        config["revision"],
        "--bodyrig-representation",
        config["representation"],
    ]
    try:
        completed = run_logged_process(invoke, log_path=log_path, timeout_seconds=config["timeout_seconds"])
    except subprocess.TimeoutExpired as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealAnimationRunnerError(
            f"animation adapter timed out after {config['timeout_seconds']} seconds{suffix}"
        ) from exc
    except (OSError, LoggedProcessError) as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealAnimationRunnerError(f"animation adapter process could not complete: {exc}{suffix}") from exc
    if completed.returncode != 0:
        detail = _log_tail(log_path)
        suffix = f": {detail}" if detail else ""
        raise PhotorealAnimationRunnerError(
            f"animation adapter failed with exit code {completed.returncode}{suffix}"
        )
    manifest_path = output_dir / "animation-manifest.json"
    if not manifest_path.is_file():
        raise PhotorealAnimationRunnerError("animation adapter did not create animation-manifest.json")
    manifest = _read_json(manifest_path, label="animation manifest")
    return validate_animation_result(manifest, request=request, output_dir=output_dir)


def run_external_animation_files(
    config_path: str | Path,
    animation_plan_path: str | Path,
    teacher_output_root: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = load_animation_config(config_path)
    animation_plan = _read_json(animation_plan_path, label="photoreal animation plan")
    return run_external_animation(
        config,
        animation_plan,
        teacher_output_root=teacher_output_root,
        workspace=workspace,
    )

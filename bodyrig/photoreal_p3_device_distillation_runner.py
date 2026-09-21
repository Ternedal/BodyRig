from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .logged_process import LoggedProcessError, run_logged_process
from .photoreal_p3_device_distillation_plan import (
    CANDIDATE_STUDENT_REPRESENTATIONS,
    FIDELITY_DELTA_DIMENSIONS,
    PhotorealP3DeviceDistillationPlanError,
    require_p3_distillation_execution_authority,
)


CONFIG_FORMAT = "bodyrig-photoreal-p3-device-distillation-config"
CONFIG_VERSION = 1
REQUEST_FORMAT = "bodyrig-photoreal-p3-device-distillation-request"
REQUEST_VERSION = 1
RESULT_FORMAT = "bodyrig-photoreal-p3-device-distillation-manifest"
RESULT_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-p3-device-distillation-execution-receipt"
RECEIPT_VERSION = 1
MAX_TIMEOUT_SECONDS = 604800

BASE_STUDENT_REPRESENTATIONS = (
    "skinned-mesh-pbr",
    "skinned-mesh-neural-texture",
    "hybrid-mesh-neural-residual",
    "gaussian-splat-optional",
)
REQUIRED_STUDENT_COMPONENTS = (
    "specialized-eye-component",
    "teacher-derived-hair-component",
)

CONFIG_FIELDS = {
    "format",
    "version",
    "adapter",
    "revision",
    "entrypoint",
    "student_representation",
    "student_components",
    "command",
    "timeout_seconds",
    "supported_target_models",
    "supported_fidelity_delta_dimensions",
    "reports_teacher_student_delta",
    "gaussian_splat_target_support",
    "consumes_staged_teacher_only",
}
SOURCE_FIELDS = {"kind", "root_kind", "relative_path", "size_bytes", "sha256"}
CONSUMED_SOURCE_FIELDS = {"kind", "root_kind", "relative_path", "sha256"}
MEASUREMENT_FIELDS = {
    "dimension",
    "metric",
    "value",
    "unit",
    "teacher_reference",
    "student_reference",
}
ARTIFACT_FIELDS = {"kind", "relative_path", "size_bytes", "sha256"}


class PhotorealP3DeviceDistillationRunnerError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP3DeviceDistillationRunnerError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP3DeviceDistillationRunnerError(
            f"{label} must be a JSON object"
        )
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP3DeviceDistillationRunnerError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealP3DeviceDistillationRunnerError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    clean = _text(value, label=label, maximum=64).lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealP3DeviceDistillationRunnerError(f"{label} is invalid")
    return clean


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP3DeviceDistillationRunnerError(
            f"{label} format/version mismatch"
        )
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP3DeviceDistillationRunnerError(
            f"{label} format/version mismatch"
        )


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP3DeviceDistillationRunnerError(f"{label} is invalid")
    number = float(value)
    if not math.isfinite(number):
        raise PhotorealP3DeviceDistillationRunnerError(f"{label} is invalid")
    return number


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
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 distillation artifact cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP3DeviceDistillationRunnerError(
            f"required file is missing/not regular: {path}"
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
        raise PhotorealP3DeviceDistillationRunnerError(
            f"{label} escapes its root"
        )
    return clean


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative_path(relative, label=label)
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealP3DeviceDistillationRunnerError(
            f"{label} escapes its root"
        ) from exc
    return clean, target


def validate_distillation_config(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != CONFIG_FIELDS or value.get("format") != CONFIG_FORMAT:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 distillation config fields/format mismatch"
        )
    _strict_v1(value.get("version"), label="P3 distillation config")
    adapter = _text(
        value.get("adapter"),
        label="P3 distillation adapter",
        maximum=80,
    )
    if any(not (ch.isalnum() or ch in "._-") for ch in adapter):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 distillation adapter name is invalid"
        )
    revision = _sha(
        value.get("revision"),
        label="P3 distillation adapter revision",
    )
    entrypoint = _text(
        value.get("entrypoint"),
        label="P3 distillation adapter entrypoint",
        maximum=4096,
    )
    representation = value.get("student_representation")
    if representation not in BASE_STUDENT_REPRESENTATIONS:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 distillation base student representation is not canonical"
        )
    components = value.get("student_components")
    if components != list(REQUIRED_STUDENT_COMPONENTS):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 distillation must explicitly include specialized eyes and teacher-derived hair"
        )
    command = value.get("command")
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 64
        or any(
            not isinstance(item, str) or not item or len(item) > 4096
            for item in command
        )
    ):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 distillation command must be a non-empty argv list"
        )
    timeout = value.get("timeout_seconds")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or not 1 <= timeout <= MAX_TIMEOUT_SECONDS
    ):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 distillation timeout_seconds is invalid"
        )
    supported = value.get("supported_target_models")
    if not isinstance(supported, list) or not supported:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 distillation adapter has no supported target models"
        )
    normalized_models: list[str] = []
    seen_models: set[str] = set()
    for model in supported:
        if model not in {"quest-2", "quest-3", "quest-3s"} or model in seen_models:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 distillation supported target models are invalid"
            )
        seen_models.add(str(model))
        normalized_models.append(str(model))
    normalized_models.sort()
    if supported != normalized_models:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 supported target models must be canonical sorted unique values"
        )
    if value.get("supported_fidelity_delta_dimensions") != list(
        FIDELITY_DELTA_DIMENSIONS
    ):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 adapter does not report the canonical fidelity delta universe"
        )
    if value.get("reports_teacher_student_delta") is not True:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 adapter does not report teacher-to-student deltas"
        )
    gaussian_support = value.get("gaussian_splat_target_support")
    if not isinstance(gaussian_support, bool):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 gaussian_splat_target_support must be boolean"
        )
    if (
        representation == "gaussian-splat-optional"
        and gaussian_support is not True
    ):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 Gaussian/splat representation requires explicit target support"
        )
    if value.get("consumes_staged_teacher_only") is not True:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 adapter must consume staged teacher copies only"
        )
    return {
        "format": CONFIG_FORMAT,
        "version": CONFIG_VERSION,
        "adapter": adapter,
        "revision": revision,
        "entrypoint": entrypoint,
        "student_representation": str(representation),
        "student_components": list(REQUIRED_STUDENT_COMPONENTS),
        "command": list(command),
        "timeout_seconds": timeout,
        "supported_target_models": normalized_models,
        "supported_fidelity_delta_dimensions": list(
            FIDELITY_DELTA_DIMENSIONS
        ),
        "reports_teacher_student_delta": True,
        "gaussian_splat_target_support": gaussian_support,
        "consumes_staged_teacher_only": True,
    }


def _verify_adapter_entrypoint(
    config: Mapping[str, Any],
    *,
    config_root: str | Path,
) -> Path:
    root = Path(config_root).expanduser().resolve()
    raw = Path(str(config["entrypoint"])).expanduser()
    entrypoint = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if not entrypoint.is_file() or entrypoint.is_symlink():
        raise PhotorealP3DeviceDistillationRunnerError(
            f"P3 distillation adapter entrypoint is missing/not regular: {entrypoint}"
        )
    observed = _file_sha(entrypoint)
    if observed != config["revision"]:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 distillation adapter entrypoint SHA-256 does not match revision"
        )

    invoked = False
    for token in config["command"]:
        candidate_raw = Path(token).expanduser()
        candidate = (
            candidate_raw.resolve()
            if candidate_raw.is_absolute()
            else (root / candidate_raw).resolve()
        )
        if candidate == entrypoint:
            invoked = True
            break
    if not invoked:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 distillation command does not invoke the pinned adapter entrypoint"
        )
    return entrypoint


def _materialize_verified_adapter_command(
    config: Mapping[str, Any],
    *,
    config_root: str | Path,
    entrypoint: Path,
) -> list[str]:
    root = Path(config_root).expanduser().resolve()
    command: list[str] = []
    replaced = 0
    for token in config["command"]:
        candidate_raw = Path(token).expanduser()
        candidate = (
            candidate_raw.resolve()
            if candidate_raw.is_absolute()
            else (root / candidate_raw).resolve()
        )
        if candidate == entrypoint:
            command.append(str(entrypoint))
            replaced += 1
        else:
            command.append(token)
    if replaced != 1:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 distillation command must reference the pinned adapter entrypoint exactly once"
        )
    return command


def _source_root(
    root_kind: str,
    *,
    teacher_output_root: Path,
    identity_root: Path,
) -> Path:
    if root_kind == "teacher-output":
        return teacher_output_root
    if root_kind == "identity-export":
        return identity_root
    raise PhotorealP3DeviceDistillationRunnerError(
        f"P3 teacher source root kind is unsupported: {root_kind}"
    )


def stage_teacher_sources(
    plan: Mapping[str, Any],
    *,
    teacher_output_root: str | Path,
    identity_root: str | Path,
    staged_root: str | Path,
) -> list[dict[str, Any]]:
    try:
        authority = require_p3_distillation_execution_authority(plan)
    except PhotorealP3DeviceDistillationPlanError as exc:
        raise PhotorealP3DeviceDistillationRunnerError(str(exc)) from exc

    teacher_root = Path(teacher_output_root).expanduser().resolve()
    identity_dir = Path(identity_root).expanduser().resolve()
    stage = Path(staged_root).expanduser().resolve()
    for root, label in (
        (teacher_root, "teacher output root"),
        (identity_dir, "identity root"),
    ):
        if not root.is_dir() or root.is_symlink():
            raise PhotorealP3DeviceDistillationRunnerError(
                f"P3 {label} is missing/not regular: {root}"
            )
    if stage.exists():
        raise PhotorealP3DeviceDistillationRunnerError(
            f"P3 staged teacher root already exists: {stage}"
        )
    stage.mkdir(parents=True)

    staged: list[dict[str, Any]] = []
    try:
        for raw in authority["teacher_source_artifacts"]:
            if not isinstance(raw, Mapping) or set(raw) != SOURCE_FIELDS:
                raise PhotorealP3DeviceDistillationRunnerError(
                    "P3 teacher source fields must match v1 exactly"
                )
            kind = _text(
                raw.get("kind"),
                label="P3 teacher source kind",
                maximum=64,
            )
            root_kind = _text(
                raw.get("root_kind"),
                label="P3 teacher source root kind",
                maximum=64,
            )
            relative = _relative_path(
                raw.get("relative_path"),
                label="P3 teacher source relative path",
            )
            source_root = _source_root(
                root_kind,
                teacher_output_root=teacher_root,
                identity_root=identity_dir,
            )
            _, source = _safe_child(
                source_root,
                relative,
                label=f"P3 {kind} source path",
            )
            size = raw.get("size_bytes")
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or size < 1
                or not source.is_file()
                or source.is_symlink()
                or source.stat().st_size != size
            ):
                raise PhotorealP3DeviceDistillationRunnerError(
                    f"P3 {kind} source size/path drifted before staging"
                )
            expected_sha = _sha(
                raw.get("sha256"),
                label=f"P3 {kind} source SHA-256",
            )
            if _file_sha(source) != expected_sha:
                raise PhotorealP3DeviceDistillationRunnerError(
                    f"P3 {kind} source bytes drifted before staging"
                )

            staged_relative = f"{root_kind}/{relative}"
            _, target = _safe_child(
                stage,
                staged_relative,
                label=f"P3 {kind} staged path",
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise PhotorealP3DeviceDistillationRunnerError(
                    f"P3 staged teacher path already exists: {staged_relative}"
                )
            shutil.copy2(source, target)
            if (
                target.stat().st_size != size
                or _file_sha(target) != expected_sha
            ):
                raise PhotorealP3DeviceDistillationRunnerError(
                    f"P3 {kind} staged copy differs from accepted teacher bytes"
                )
            staged.append(
                {
                    "kind": kind,
                    "root_kind": root_kind,
                    "relative_path": staged_relative,
                    "size_bytes": size,
                    "sha256": expected_sha,
                }
            )
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    staged.sort(
        key=lambda item: (
            item["root_kind"],
            item["kind"],
            item["relative_path"],
        )
    )
    expected = {
        item["relative_path"] for item in staged
    }
    actual = {
        path.relative_to(stage).as_posix()
        for path in stage.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        shutil.rmtree(stage, ignore_errors=True)
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 staged teacher artifact universe mismatch"
        )
    return staged


def build_distillation_request(
    config: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    staged_teacher_sources: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    config = validate_distillation_config(config)
    try:
        authority = require_p3_distillation_execution_authority(plan)
    except PhotorealP3DeviceDistillationPlanError as exc:
        raise PhotorealP3DeviceDistillationRunnerError(str(exc)) from exc

    target_model = authority["target_profile"]["target_model"]
    if target_model not in config["supported_target_models"]:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 adapter does not support planned target model"
        )
    if (
        target_model == "quest-2"
        and config["student_representation"] == "gaussian-splat-optional"
    ):
        raise PhotorealP3DeviceDistillationRunnerError(
            "Quest 2 P3 distillation cannot depend on native Gaussian splats"
        )
    if config["student_representation"] not in authority[
        "candidate_student_representations"
    ]:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 adapter selected representation outside plan authority"
        )
    for component in REQUIRED_STUDENT_COMPONENTS:
        if component not in authority["candidate_student_representations"]:
            raise PhotorealP3DeviceDistillationRunnerError(
                f"P3 required student component is outside plan authority: {component}"
            )

    expected_sources = [
        {
            "kind": raw["kind"],
            "root_kind": raw["root_kind"],
            "relative_path": f"{raw['root_kind']}/{raw['relative_path']}",
            "size_bytes": raw["size_bytes"],
            "sha256": raw["sha256"],
        }
        for raw in authority["teacher_source_artifacts"]
    ]
    expected_sources.sort(
        key=lambda item: (
            item["root_kind"],
            item["kind"],
            item["relative_path"],
        )
    )
    staged = [dict(item) for item in staged_teacher_sources]
    if staged != expected_sources:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 staged teacher sources differ from plan authority"
        )

    request: dict[str, Any] = {
        "format": REQUEST_FORMAT,
        "version": REQUEST_VERSION,
        "performer_id": authority["performer_id"],
        "selected_epoch_id": authority["selected_epoch_id"],
        "teacher_input_sha256": authority["teacher_input_sha256"],
        "p2_animation_plan_sha256": authority["p2_animation_plan_sha256"],
        "p2_exavatar_animation_execution_input_sha256": authority[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "p2_animated_human_review_sha256": authority[
            "p2_animated_human_review_sha256"
        ],
        "p3_device_distillation_plan_sha256": authority[
            "p3_device_distillation_plan_sha256"
        ],
        "target_profile": authority["target_profile"],
        "target_profile_sha256": authority["target_profile_sha256"],
        "target_model": target_model,
        "adapter": config["adapter"],
        "adapter_revision": config["revision"],
        "student_representation": config["student_representation"],
        "student_components": list(config["student_components"]),
        "staged_teacher_sources": staged,
        "required_fidelity_delta_dimensions": list(
            FIDELITY_DELTA_DIMENSIONS
        ),
        "teacher_remains_visual_authority": True,
        "student_may_not_claim_fidelity_above_teacher": True,
        "staged_teacher_only": True,
        "p3_distillation_execution_authorized": True,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    request["p3_device_distillation_request_sha256"] = _digest(
        request,
        omit="p3_device_distillation_request_sha256",
    )
    return request


def _source_universe(
    request: Mapping[str, Any],
) -> dict[str, tuple[str, str, str]]:
    result: dict[str, tuple[str, str, str]] = {}
    raw_sources = request.get("staged_teacher_sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 request contains no staged teacher sources"
        )
    for raw in raw_sources:
        if not isinstance(raw, Mapping) or set(raw) != SOURCE_FIELDS:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 staged teacher source fields must match v1 exactly"
            )
        relative = _relative_path(
            raw.get("relative_path"),
            label="P3 staged teacher source path",
        )
        if relative in result:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 request repeats staged teacher source"
            )
        result[relative] = (
            _text(raw.get("kind"), label="P3 staged source kind", maximum=64),
            _text(
                raw.get("root_kind"),
                label="P3 staged source root kind",
                maximum=64,
            ),
            _sha(
                raw.get("sha256"),
                label="P3 staged teacher source SHA-256",
            ),
        )
    return result


def validate_distillation_result(
    value: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    output_dir: Path,
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
        "target_profile_sha256",
        "target_model",
        "adapter",
        "adapter_revision",
        "student_representation",
        "student_components",
        "distillation_complete",
        "consumed_teacher_sources",
        "fidelity_delta_measurements",
        "student_artifacts",
        "student_fidelity_claim_exceeds_teacher",
        "human_runtime_visual_acceptance_required",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
    }
    if set(value) != expected_fields or value.get("format") != RESULT_FORMAT:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 distillation manifest fields/format mismatch"
        )
    _strict_v1(value.get("version"), label="P3 distillation manifest")
    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_animated_human_review_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "target_profile_sha256",
        "target_model",
        "adapter",
        "adapter_revision",
        "student_representation",
        "student_components",
    ):
        if value.get(field) != request.get(field):
            raise PhotorealP3DeviceDistillationRunnerError(
                f"P3 distillation manifest provenance mismatch: {field}"
            )
    if value.get("distillation_complete") is not True:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 adapter did not report complete distillation"
        )
    if value.get("student_fidelity_claim_exceeds_teacher") is not False:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 adapter claimed student fidelity above teacher"
        )
    if value.get("human_runtime_visual_acceptance_required") is not True:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 adapter removed human runtime visual acceptance"
        )
    for field in (
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        if value.get(field) is not False:
            raise PhotorealP3DeviceDistillationRunnerError(
                f"P3 adapter crossed authority boundary: {field}"
            )

    source_universe = _source_universe(request)
    consumed = value.get("consumed_teacher_sources")
    if not isinstance(consumed, list) or len(consumed) != len(source_universe):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 manifest did not consume the exact staged teacher universe"
        )
    normalized_consumed: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    for raw in consumed:
        if not isinstance(raw, Mapping) or set(raw) != CONSUMED_SOURCE_FIELDS:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 consumed teacher-source fields must match v1 exactly"
            )
        relative = _relative_path(
            raw.get("relative_path"),
            label="P3 consumed staged teacher path",
        )
        if relative in seen_sources:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 manifest repeats consumed teacher source"
            )
        seen_sources.add(relative)
        expected = source_universe.get(relative)
        observed = (
            _text(raw.get("kind"), label="P3 consumed source kind", maximum=64),
            _text(
                raw.get("root_kind"),
                label="P3 consumed source root kind",
                maximum=64,
            ),
            _sha(
                raw.get("sha256"),
                label="P3 consumed source SHA-256",
            ),
        )
        if expected != observed:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 manifest consumed unauthorized teacher source bytes"
            )
        normalized_consumed.append(
            {
                "kind": observed[0],
                "root_kind": observed[1],
                "relative_path": relative,
                "sha256": observed[2],
            }
        )
    if seen_sources != set(source_universe):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 manifest omitted staged teacher sources"
        )

    measurements = value.get("fidelity_delta_measurements")
    if (
        not isinstance(measurements, list)
        or len(measurements) != len(FIDELITY_DELTA_DIMENSIONS)
    ):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 fidelity delta universe is incomplete"
        )
    by_dimension: dict[str, dict[str, Any]] = {}
    for raw in measurements:
        if not isinstance(raw, Mapping) or set(raw) != MEASUREMENT_FIELDS:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 fidelity delta fields must match v1 exactly"
            )
        dimension = _text(
            raw.get("dimension"),
            label="P3 fidelity delta dimension",
            maximum=80,
        )
        if (
            dimension not in FIDELITY_DELTA_DIMENSIONS
            or dimension in by_dimension
        ):
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 fidelity delta dimension is unsupported/repeated"
            )
        by_dimension[dimension] = {
            "dimension": dimension,
            "metric": _text(
                raw.get("metric"),
                label="P3 fidelity delta metric",
                maximum=160,
            ),
            "value": _finite(
                raw.get("value"),
                label="P3 fidelity delta value",
            ),
            "unit": _text(
                raw.get("unit"),
                label="P3 fidelity delta unit",
                maximum=80,
            ),
            "teacher_reference": _text(
                raw.get("teacher_reference"),
                label="P3 teacher fidelity reference",
                maximum=512,
            ),
            "student_reference": _text(
                raw.get("student_reference"),
                label="P3 student fidelity reference",
                maximum=512,
            ),
        }
    if set(by_dimension) != set(FIDELITY_DELTA_DIMENSIONS):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 fidelity delta dimensions are incomplete"
        )

    artifacts = value.get("student_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 manifest contains no student artifacts"
        )
    normalized_artifacts: list[dict[str, Any]] = []
    listed: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != ARTIFACT_FIELDS:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 student artifact fields must match v1 exactly"
            )
        kind = _text(
            raw.get("kind"),
            label="P3 student artifact kind",
            maximum=64,
        )
        relative, path = _safe_child(
            output_dir,
            raw.get("relative_path"),
            label="P3 student artifact path",
        )
        if relative == "distillation-manifest.json" or relative in listed:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 student artifact path is repeated/reserved"
            )
        listed.add(relative)
        size = raw.get("size_bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != size
        ):
            raise PhotorealP3DeviceDistillationRunnerError(
                f"P3 student artifact size/path mismatch: {relative}"
            )
        observed_sha = _file_sha(path)
        expected_sha = _sha(
            raw.get("sha256"),
            label="P3 student artifact SHA-256",
        )
        if observed_sha != expected_sha:
            raise PhotorealP3DeviceDistillationRunnerError(
                f"P3 student artifact SHA-256 mismatch: {relative}"
            )
        normalized_artifacts.append(
            {
                "kind": kind,
                "relative_path": relative,
                "size_bytes": size,
                "sha256": observed_sha,
            }
        )
    root_manifest = (output_dir / "distillation-manifest.json").resolve()
    actual = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file() and path.resolve() != root_manifest
    }
    if actual != listed:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 student output artifact universe differs from manifest"
        )

    result = dict(value)
    result["consumed_teacher_sources"] = sorted(
        normalized_consumed,
        key=lambda item: (
            item["root_kind"],
            item["kind"],
            item["relative_path"],
        ),
    )
    result["fidelity_delta_measurements"] = [
        by_dimension[item] for item in FIDELITY_DELTA_DIMENSIONS
    ]
    result["student_artifacts"] = sorted(
        normalized_artifacts,
        key=lambda item: item["relative_path"],
    )
    return result


def build_execution_receipt(
    validated_result: Mapping[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "version": RECEIPT_VERSION,
        "performer_id": validated_result["performer_id"],
        "selected_epoch_id": validated_result["selected_epoch_id"],
        "teacher_input_sha256": validated_result["teacher_input_sha256"],
        "p2_animation_plan_sha256": validated_result[
            "p2_animation_plan_sha256"
        ],
        "p2_exavatar_animation_execution_input_sha256": validated_result[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "p2_animated_human_review_sha256": validated_result[
            "p2_animated_human_review_sha256"
        ],
        "p3_device_distillation_plan_sha256": validated_result[
            "p3_device_distillation_plan_sha256"
        ],
        "p3_device_distillation_request_sha256": validated_result[
            "p3_device_distillation_request_sha256"
        ],
        "target_profile_sha256": validated_result["target_profile_sha256"],
        "target_model": validated_result["target_model"],
        "adapter": validated_result["adapter"],
        "adapter_revision": validated_result["adapter_revision"],
        "student_representation": validated_result["student_representation"],
        "student_components": list(validated_result["student_components"]),
        "distillation_complete": True,
        "consumed_teacher_sources": list(
            validated_result["consumed_teacher_sources"]
        ),
        "fidelity_delta_measurements": list(
            validated_result["fidelity_delta_measurements"]
        ),
        "student_artifacts": list(validated_result["student_artifacts"]),
        "artifact_bytes_verified_by_core": True,
        "staged_teacher_only": True,
        "student_fidelity_claim_exceeds_teacher": False,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p3_device_distillation_execution_receipt_sha256"] = _digest(
        result,
        omit="p3_device_distillation_execution_receipt_sha256",
    )
    return validate_execution_receipt(result)


def validate_execution_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
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
        "target_profile_sha256",
        "target_model",
        "adapter",
        "adapter_revision",
        "student_representation",
        "student_components",
        "distillation_complete",
        "consumed_teacher_sources",
        "fidelity_delta_measurements",
        "student_artifacts",
        "artifact_bytes_verified_by_core",
        "staged_teacher_only",
        "student_fidelity_claim_exceeds_teacher",
        "human_runtime_visual_acceptance_required",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_device_distillation_execution_receipt_sha256",
    }
    if set(value) != expected_fields or value.get("format") != RECEIPT_FORMAT:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 execution receipt fields/format mismatch"
        )
    _strict_v1(value.get("version"), label="P3 execution receipt")
    _text(value.get("performer_id"), label="P3 receipt performer", maximum=256)
    _text(value.get("selected_epoch_id"), label="P3 receipt epoch", maximum=256)
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_animated_human_review_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_request_sha256",
        "target_profile_sha256",
    ):
        _sha(value.get(field), label=f"P3 execution receipt {field}")
    _text(value.get("adapter"), label="P3 receipt adapter", maximum=80)
    _sha(
        value.get("adapter_revision"),
        label="P3 receipt adapter revision",
    )
    target_model = _text(
        value.get("target_model"),
        label="P3 receipt target model",
        maximum=64,
    )
    if target_model not in {"quest-2", "quest-3", "quest-3s"}:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 receipt target model is unsupported"
        )
    if value.get("student_representation") not in BASE_STUDENT_REPRESENTATIONS:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 receipt base student representation is not canonical"
        )
    if (
        target_model == "quest-2"
        and value.get("student_representation") == "gaussian-splat-optional"
    ):
        raise PhotorealP3DeviceDistillationRunnerError(
            "Quest 2 P3 receipt cannot claim a native Gaussian student"
        )
    if value.get("student_components") != list(REQUIRED_STUDENT_COMPONENTS):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 receipt is missing required eye/hair components"
        )
    consumed = value.get("consumed_teacher_sources")
    if not isinstance(consumed, list) or len(consumed) != 5:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 receipt teacher source universe is incomplete"
        )
    seen_sources: set[str] = set()
    for raw in consumed:
        if not isinstance(raw, Mapping) or set(raw) != CONSUMED_SOURCE_FIELDS:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 receipt consumed source fields must match v1 exactly"
            )
        relative = _relative_path(
            raw.get("relative_path"),
            label="P3 receipt consumed source path",
        )
        if relative in seen_sources:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 receipt repeats consumed teacher source"
            )
        seen_sources.add(relative)
        _text(raw.get("kind"), label="P3 receipt source kind", maximum=64)
        _text(
            raw.get("root_kind"),
            label="P3 receipt source root kind",
            maximum=64,
        )
        _sha(raw.get("sha256"), label="P3 receipt source SHA-256")

    expected_source_kinds = {
        "teacher-checkpoint": "teacher-output",
        "shape-param": "identity-export",
        "face-offset": "identity-export",
        "joint-offset": "identity-export",
        "locator-offset": "identity-export",
    }
    observed_source_kinds = {
        raw["kind"]: raw["root_kind"] for raw in consumed
    }
    if observed_source_kinds != expected_source_kinds:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 receipt teacher source kind/root universe mismatch"
        )

    measurements = value.get("fidelity_delta_measurements")
    if (
        not isinstance(measurements, list)
        or len(measurements) != len(FIDELITY_DELTA_DIMENSIONS)
    ):
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 receipt fidelity delta universe is incomplete"
        )
    for index, raw in enumerate(measurements):
        if not isinstance(raw, Mapping) or set(raw) != MEASUREMENT_FIELDS:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 receipt fidelity delta fields must match v1 exactly"
            )
        if raw.get("dimension") != FIDELITY_DELTA_DIMENSIONS[index]:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 receipt fidelity delta order/universe mismatch"
            )
        _text(raw.get("metric"), label="P3 receipt metric", maximum=160)
        _finite(raw.get("value"), label="P3 receipt delta value")
        _text(raw.get("unit"), label="P3 receipt delta unit", maximum=80)
        _text(
            raw.get("teacher_reference"),
            label="P3 receipt teacher reference",
            maximum=512,
        )
        _text(
            raw.get("student_reference"),
            label="P3 receipt student reference",
            maximum=512,
        )

    artifacts = value.get("student_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 execution receipt has no student artifacts"
        )
    seen_artifacts: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != ARTIFACT_FIELDS:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 receipt student artifact fields must match v1 exactly"
            )
        relative = _relative_path(
            raw.get("relative_path"),
            label="P3 receipt student artifact path",
        )
        if relative in seen_artifacts:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 receipt repeats student artifact"
            )
        seen_artifacts.add(relative)
        _text(
            raw.get("kind"),
            label="P3 receipt student artifact kind",
            maximum=64,
        )
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 receipt student artifact size is invalid"
            )
        _sha(raw.get("sha256"), label="P3 receipt student artifact SHA-256")

    for field, expected in (
        ("distillation_complete", True),
        ("artifact_bytes_verified_by_core", True),
        ("staged_teacher_only", True),
        ("student_fidelity_claim_exceeds_teacher", False),
        ("human_runtime_visual_acceptance_required", True),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP3DeviceDistillationRunnerError(
                f"P3 execution receipt authority mismatch: {field}"
            )
    claimed = _sha(
        value.get("p3_device_distillation_execution_receipt_sha256"),
        label="P3 execution receipt SHA-256",
    )
    if _digest(
        value,
        omit="p3_device_distillation_execution_receipt_sha256",
    ) != claimed:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 execution receipt digest mismatch"
        )
    return dict(value)


def _log_tail(path: Path, limit: int = 8000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[-limit:].decode("utf-8", errors="replace").strip()


def run_external_distillation(
    config: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    teacher_output_root: str | Path,
    identity_root: str | Path,
    workspace: str | Path,
    config_root: str | Path | None = None,
) -> dict[str, Any]:
    config = validate_distillation_config(config)
    resolved_config_root = (
        Path.cwd().resolve()
        if config_root is None
        else Path(config_root).expanduser().resolve()
    )
    entrypoint = _verify_adapter_entrypoint(
        config,
        config_root=resolved_config_root,
    )
    verified_command = _materialize_verified_adapter_command(
        config,
        config_root=resolved_config_root,
        entrypoint=entrypoint,
    )
    try:
        authority = require_p3_distillation_execution_authority(plan)
    except PhotorealP3DeviceDistillationPlanError as exc:
        raise PhotorealP3DeviceDistillationRunnerError(str(exc)) from exc

    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealP3DeviceDistillationRunnerError(
            f"P3 distillation workspace already exists: {root}"
        )
    root.mkdir(parents=True)
    staged_root = root / "staged-teacher"
    output_dir = root / "output"
    output_dir.mkdir()
    request_path = root / "request.json"
    log_path = root / "adapter.log"

    staged_sources = stage_teacher_sources(
        authority,
        teacher_output_root=teacher_output_root,
        identity_root=identity_root,
        staged_root=staged_root,
    )
    request = build_distillation_request(
        config,
        authority,
        staged_teacher_sources=staged_sources,
    )
    request_path.write_text(
        json.dumps(
            request,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )

    invoke = [
        *verified_command,
        "--bodyrig-request",
        str(request_path),
        "--bodyrig-teacher-root",
        str(staged_root),
        "--bodyrig-output",
        str(output_dir),
        "--bodyrig-adapter",
        config["adapter"],
        "--bodyrig-revision",
        config["revision"],
        "--bodyrig-student-representation",
        config["student_representation"],
        "--bodyrig-student-components",
        ",".join(config["student_components"]),
    ]
    try:
        completed = run_logged_process(
            invoke,
            log_path=log_path,
            timeout_seconds=config["timeout_seconds"],
        )
    except subprocess.TimeoutExpired as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealP3DeviceDistillationRunnerError(
            f"P3 distillation adapter timed out after "
            f"{config['timeout_seconds']} seconds{suffix}"
        ) from exc
    except (OSError, LoggedProcessError) as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealP3DeviceDistillationRunnerError(
            f"P3 distillation adapter could not complete: {exc}{suffix}"
        ) from exc
    if completed.returncode != 0:
        detail = _log_tail(log_path)
        suffix = f": {detail}" if detail else ""
        raise PhotorealP3DeviceDistillationRunnerError(
            f"P3 distillation adapter failed with exit code "
            f"{completed.returncode}{suffix}"
        )

    manifest_path = output_dir / "distillation-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 adapter did not create distillation-manifest.json"
        )
    raw = _read_json(manifest_path, label="P3 distillation manifest")
    validated = validate_distillation_result(
        raw,
        request=request,
        output_dir=output_dir,
    )

    # Re-check the staged teacher copies after adapter execution. The adapter
    # never receives original teacher roots, and it may not mutate its copies.
    for raw_source in staged_sources:
        _, path = _safe_child(
            staged_root,
            raw_source["relative_path"],
            label="P3 staged teacher post-run path",
        )
        if (
            path.stat().st_size != raw_source["size_bytes"]
            or _file_sha(path) != raw_source["sha256"]
        ):
            raise PhotorealP3DeviceDistillationRunnerError(
                "P3 adapter mutated staged teacher source bytes"
            )
    actual_staged = {
        path.relative_to(staged_root).as_posix()
        for path in staged_root.rglob("*")
        if path.is_file()
    }
    if actual_staged != {item["relative_path"] for item in staged_sources}:
        raise PhotorealP3DeviceDistillationRunnerError(
            "P3 adapter changed staged teacher artifact universe"
        )

    receipt = build_execution_receipt(validated)
    receipt_path = root / "p3-device-distillation-execution-receipt.json"
    with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(
            receipt,
            stream,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        stream.write("\n")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run one external P3 distillation adapter against staged copies of "
            "the accepted ExAvatar teacher, then core-verify student artifacts."
        )
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--teacher-output-root", type=Path, required=True)
    parser.add_argument("--identity-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config_path = args.config.expanduser().resolve()
        receipt = run_external_distillation(
            _read_json(config_path, label="P3 distillation config"),
            _read_json(args.plan, label="P3 distillation plan"),
            teacher_output_root=args.teacher_output_root,
            identity_root=args.identity_root,
            workspace=args.workspace,
            config_root=config_path.parent,
        )
    except PhotorealP3DeviceDistillationRunnerError as exc:
        print(f"BodyRig P3 device distillation runner: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P3_DISTILLATION_COMPLETE_RUNTIME_REVIEW_REQUIRED",
                "student_representation": receipt["student_representation"],
                "student_components": receipt["student_components"],
                "student_artifact_count": len(receipt["student_artifacts"]),
                "fidelity_delta_dimension_count": len(
                    receipt["fidelity_delta_measurements"]
                ),
                "artifact_bytes_verified_by_core": True,
                "staged_teacher_only": True,
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

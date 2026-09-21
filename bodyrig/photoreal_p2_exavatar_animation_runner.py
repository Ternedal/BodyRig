from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from .logged_process import LoggedProcessError, run_logged_process
from .photoreal_p2_exavatar_animation_execution_input import (
    PhotorealP2ExAvatarAnimationExecutionInputError,
    validate_exavatar_animation_execution_input,
)
from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter


REQUEST_FORMAT = "bodyrig-photoreal-p2-exavatar-animation-request"
REQUEST_VERSION = 1
MANIFEST_FORMAT = "bodyrig-photoreal-p2-exavatar-animation-manifest"
MANIFEST_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-p2-exavatar-animation-execution-receipt"
RECEIPT_VERSION = 1
TEACHER_CONFIG_FORMAT = "bodyrig-photoreal-teacher-config"
PINNED_UPSTREAM_REPOSITORY = "https://github.com/mks0601/ExAvatar_RELEASE"
PINNED_UPSTREAM_COMMIT = "d45268730c779fae4118f1a361cf9ff639bc4d1e"
PINNED_TEST_EPOCH = 4
MAX_TIMEOUT_SECONDS = 604800


class PhotorealP2ExAvatarAnimationRunnerError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"{label} must be a JSON object"
        )
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise PhotorealP2ExAvatarAnimationRunnerError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2ExAvatarAnimationRunnerError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealP2ExAvatarAnimationRunnerError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"{label} format/version mismatch"
        )
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"{label} format/version mismatch"
        )


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
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation artifact cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP2ExAvatarAnimationRunnerError(
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
    if clean.startswith("/") or clean.startswith("../") or "/../" in f"/{clean}/" or ":" in first:
        raise PhotorealP2ExAvatarAnimationRunnerError(f"{label} escapes its root")
    return clean


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative_path(relative, label=label)
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"{label} escapes its root"
        ) from exc
    return clean, target


def _linux_join(root: str, relative: str) -> str:
    clean_root = _text(root, label="Linux root").rstrip("/")
    clean_relative = _relative_path(relative, label="Linux relative path")
    return f"{clean_root}/{clean_relative}"


def _config_arg(command: list[Any], name: str) -> str:
    positions = [index for index, item in enumerate(command) if item == name]
    if len(positions) != 1:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"teacher config must contain exactly one {name}"
        )
    index = positions[0]
    if index + 1 >= len(command):
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"teacher config {name} has no value"
        )
    return _text(command[index + 1], label=f"teacher config {name}")


def _runtime_from_teacher_config(config: Mapping[str, Any]) -> dict[str, str | int]:
    expected = {
        "format",
        "version",
        "adapter",
        "revision",
        "upstream_repository",
        "upstream_commit",
        "command",
        "timeout_seconds",
    }
    if set(config) != expected:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "ExAvatar teacher config fields must match v1 exactly"
        )
    if config.get("format") != TEACHER_CONFIG_FORMAT:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "ExAvatar teacher config format/version mismatch"
        )
    _strict_v1(config.get("version"), label="ExAvatar teacher config")
    if config.get("adapter") != "exavatar-benchmark":
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "ExAvatar teacher config adapter mismatch"
        )
    if config.get("upstream_repository") != PINNED_UPSTREAM_REPOSITORY:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "ExAvatar teacher config upstream repository mismatch"
        )
    if config.get("upstream_commit") != PINNED_UPSTREAM_COMMIT:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "ExAvatar teacher config upstream commit mismatch"
        )
    command = config.get("command")
    if not isinstance(command, list) or not command:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "ExAvatar teacher config command is invalid"
        )
    timeout = config.get("timeout_seconds")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or not 1 <= timeout <= MAX_TIMEOUT_SECONDS
    ):
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "ExAvatar teacher config timeout is invalid"
        )
    distribution = _config_arg(command, "--distribution")
    wsl_exe = _config_arg(command, "--wsl-exe")
    linux_python = _config_arg(command, "--linux-python")
    linux_workspace_root = _config_arg(command, "--workspace-root")
    runtime_preflight = _config_arg(command, "--runtime-preflight")
    if not linux_python.startswith("/") or not linux_workspace_root.startswith("/") or not runtime_preflight.startswith("/"):
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "ExAvatar teacher config Linux paths must be absolute"
        )
    return {
        "distribution": distribution,
        "wsl_exe": wsl_exe,
        "linux_python": linux_python,
        "linux_workspace_root": linux_workspace_root.rstrip("/"),
        "runtime_preflight": runtime_preflight,
        "timeout_seconds": timeout,
    }


def _verify_file_record(
    root: Path,
    record: Mapping[str, Any],
    *,
    path_field: str,
    label: str,
) -> dict[str, Any]:
    relative, path = _safe_child(root, record.get(path_field), label=f"{label} path")
    size = record.get("size_bytes")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
        or not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != size
    ):
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"{label} size/path drifted: {relative}"
        )
    observed = _file_sha(path)
    expected = _sha(record.get("sha256"), label=f"{label} SHA-256")
    if observed != expected:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"{label} bytes drifted: {relative}"
        )
    return {
        "relative_path": relative,
        "size_bytes": size,
        "sha256": observed,
    }


def build_animation_request(
    execution_input: Mapping[str, Any],
    teacher_config: Mapping[str, Any],
    *,
    identity_root: str | Path,
    motion_output_root: str | Path,
    teacher_output_root: str | Path,
    bodyrig_repo_root: str | Path,
    adapter_script: str | Path,
) -> tuple[dict[str, Any], dict[str, str | int]]:
    try:
        authority = validate_exavatar_animation_execution_input(execution_input)
    except PhotorealP2ExAvatarAnimationExecutionInputError as exc:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"P2 ExAvatar execution-input readback failed: {exc}"
        ) from exc
    runtime = _runtime_from_teacher_config(teacher_config)

    identity_dir = Path(identity_root).expanduser().resolve()
    motion_dir = Path(motion_output_root).expanduser().resolve()
    teacher_dir = Path(teacher_output_root).expanduser().resolve()
    repo_dir = Path(bodyrig_repo_root).expanduser().resolve()
    adapter = Path(adapter_script).expanduser().resolve()
    for root, label in (
        (identity_dir, "identity root"),
        (motion_dir, "motion output root"),
        (teacher_dir, "teacher output root"),
        (repo_dir, "BodyRig repository root"),
    ):
        if not root.is_dir() or root.is_symlink():
            raise PhotorealP2ExAvatarAnimationRunnerError(
                f"P2 ExAvatar {label} is missing/not regular: {root}"
            )
    if not adapter.is_file() or adapter.is_symlink():
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"P2 ExAvatar animation adapter script is missing/not regular: {adapter}"
        )

    converter = make_wsl_path_converter(
        str(runtime["wsl_exe"]),
        str(runtime["distribution"]),
    )
    try:
        linux_identity_root = converter(str(identity_dir))
        linux_motion_root = converter(str(motion_dir))
        linux_teacher_root = converter(str(teacher_dir))
        linux_repo_root = converter(str(repo_dir))
        linux_adapter = converter(str(adapter))
    except (OSError, WslBridgeError) as exc:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"P2 ExAvatar Windows->WSL path conversion failed: {exc}"
        ) from exc

    checkpoint = authority["teacher_checkpoint"]
    verified_checkpoint = _verify_file_record(
        teacher_dir,
        checkpoint,
        path_field="relative_path",
        label="accepted teacher checkpoint",
    )
    verified_checkpoint["linux_source_path"] = _linux_join(
        linux_teacher_root,
        verified_checkpoint["relative_path"],
    )

    verified_identity: list[dict[str, Any]] = []
    for raw in authority["identity_artifacts"]:
        verified = _verify_file_record(
            identity_dir,
            raw,
            path_field="export_relative_path",
            label="accepted ExAvatar identity artifact",
        )
        verified.update(
            {
                "kind": raw["kind"],
                "export_relative_path": verified.pop("relative_path"),
            }
        )
        verified["linux_source_path"] = _linux_join(
            linux_identity_root,
            verified["export_relative_path"],
        )
        verified_identity.append(verified)

    driver = authority["motion_driver"]
    verified_motion: list[dict[str, Any]] = []
    for raw in driver["artifacts"]:
        verified = _verify_file_record(
            motion_dir,
            raw,
            path_field="relative_path",
            label="accepted P2 motion artifact",
        )
        verified["linux_source_path"] = _linux_join(
            linux_motion_root,
            verified["relative_path"],
        )
        verified_motion.append(verified)

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
        "exavatar_workspace_sha256": authority["exavatar_workspace_sha256"],
        "exavatar_preprocess_state_sha256": authority[
            "exavatar_preprocess_state_sha256"
        ],
        "exavatar_upstream_repository": PINNED_UPSTREAM_REPOSITORY,
        "exavatar_upstream_commit": PINNED_UPSTREAM_COMMIT,
        "exavatar_subject_id": authority["exavatar_subject_id"],
        "test_epoch": PINNED_TEST_EPOCH,
        "adapter_revision": _file_sha(adapter),
        "bodyrig_linux_repo_root": linux_repo_root,
        "adapter_linux_path": linux_adapter,
        "teacher_checkpoint": verified_checkpoint,
        "identity_artifacts": sorted(verified_identity, key=lambda item: item["kind"]),
        "motion_driver": {
            "source_ref": driver["source_ref"],
            "split": "train",
            "role": "motion-driver",
            "selected_eye": driver["selected_eye"],
            "selected_viewport_id": driver["selected_viewport_id"],
            "anchor_observation_ref": driver["anchor_observation_ref"],
            "anchor_frame_sha256": driver["anchor_frame_sha256"],
            "window_start_seconds": driver["window_start_seconds"],
            "window_end_seconds": driver["window_end_seconds"],
            "window_duration_seconds": driver["window_duration_seconds"],
            "motion_path_relative": driver["motion_path_relative"],
            "frame_count": driver["frame_count"],
            "frame_ids": list(driver["frame_ids"]),
            "artifacts": sorted(verified_motion, key=lambda item: item["relative_path"]),
        },
        "source_media_rehash_performed": False,
        "held_out_evaluation_disclosed": False,
        "train_motion_driver_only": True,
        "human_animated_visual_acceptance_required": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    request["p2_exavatar_animation_request_sha256"] = _digest(
        request,
        omit="p2_exavatar_animation_request_sha256",
    )
    return request, runtime


def _validate_manifest(
    manifest: Mapping[str, Any],
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
        "p2_exavatar_animation_execution_input_sha256",
        "p2_exavatar_animation_request_sha256",
        "exavatar_upstream_commit",
        "exavatar_subject_id",
        "test_epoch",
        "adapter_revision",
        "motion_driver_source_ref",
        "motion_frame_count",
        "motion_frame_ids",
        "consumed_checkpoint_sha256",
        "consumed_identity_artifacts",
        "consumed_motion_artifacts",
        "animation_artifacts",
        "animation_complete",
        "source_media_rehash_performed",
        "held_out_evaluation_disclosed",
        "human_animated_visual_acceptance_required",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    }
    if set(manifest) != expected_fields:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation manifest fields must match v1 exactly"
        )
    if manifest.get("format") != MANIFEST_FORMAT:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation manifest format/version mismatch"
        )
    _strict_v1(manifest.get("version"), label="P2 ExAvatar animation manifest")
    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_exavatar_animation_request_sha256",
        "exavatar_subject_id",
        "test_epoch",
        "adapter_revision",
    ):
        expected = (
            request["test_epoch"]
            if field == "test_epoch"
            else request.get(field)
        )
        if manifest.get(field) != expected:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                f"P2 ExAvatar animation manifest provenance mismatch: {field}"
            )
    if manifest.get("exavatar_upstream_commit") != PINNED_UPSTREAM_COMMIT:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation manifest upstream commit mismatch"
        )
    driver = request["motion_driver"]
    if manifest.get("motion_driver_source_ref") != driver["source_ref"]:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation manifest motion driver mismatch"
        )
    if manifest.get("motion_frame_count") != driver["frame_count"]:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation manifest frame count mismatch"
        )
    if manifest.get("motion_frame_ids") != driver["frame_ids"]:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation manifest frame-id universe mismatch"
        )
    if manifest.get("consumed_checkpoint_sha256") != request["teacher_checkpoint"]["sha256"]:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation consumed different checkpoint bytes"
        )

    identity_expected = {
        item["kind"]: item["sha256"] for item in request["identity_artifacts"]
    }
    consumed_identity = manifest.get("consumed_identity_artifacts")
    if not isinstance(consumed_identity, list) or len(consumed_identity) != len(identity_expected):
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation consumed identity universe mismatch"
        )
    observed_identity: dict[str, str] = {}
    for raw in consumed_identity:
        if not isinstance(raw, Mapping) or set(raw) != {"kind", "sha256"}:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar consumed identity fields must match v1 exactly"
            )
        kind = _text(raw.get("kind"), label="P2 ExAvatar consumed identity kind", maximum=64)
        if kind in observed_identity:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar animation repeats consumed identity kind"
            )
        observed_identity[kind] = _sha(
            raw.get("sha256"),
            label="P2 ExAvatar consumed identity SHA-256",
        )
    if observed_identity != identity_expected:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation consumed different identity bytes"
        )

    motion_expected = {
        item["relative_path"]: item["sha256"]
        for item in request["motion_driver"]["artifacts"]
    }
    consumed_motion = manifest.get("consumed_motion_artifacts")
    if not isinstance(consumed_motion, list) or len(consumed_motion) != len(motion_expected):
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation consumed motion universe mismatch"
        )
    observed_motion: dict[str, str] = {}
    for raw in consumed_motion:
        if not isinstance(raw, Mapping) or set(raw) != {"relative_path", "sha256"}:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar consumed motion fields must match v1 exactly"
            )
        relative = _relative_path(
            raw.get("relative_path"),
            label="P2 ExAvatar consumed motion relative path",
        )
        if relative in observed_motion:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar animation repeats consumed motion artifact"
            )
        observed_motion[relative] = _sha(
            raw.get("sha256"),
            label="P2 ExAvatar consumed motion SHA-256",
        )
    if observed_motion != motion_expected:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation consumed different motion bytes"
        )

    artifacts = manifest.get("animation_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation manifest has no output artifacts"
        )
    normalized_artifacts: list[dict[str, Any]] = []
    listed: set[str] = {"animation-manifest.json"}
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != {
            "kind",
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar animation artifact fields must match v1 exactly"
            )
        kind = _text(raw.get("kind"), label="P2 ExAvatar animation artifact kind", maximum=64)
        relative, path = _safe_child(
            output_root,
            raw.get("relative_path"),
            label="P2 ExAvatar animation artifact path",
        )
        if relative in listed:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar animation artifact path is repeated/reserved"
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
            raise PhotorealP2ExAvatarAnimationRunnerError(
                f"P2 ExAvatar animation artifact size/path mismatch: {relative}"
            )
        observed = _file_sha(path)
        if observed != _sha(raw.get("sha256"), label="P2 ExAvatar animation artifact SHA-256"):
            raise PhotorealP2ExAvatarAnimationRunnerError(
                f"P2 ExAvatar animation artifact bytes drifted: {relative}"
            )
        normalized_artifacts.append(
            {
                "kind": kind,
                "relative_path": relative,
                "size_bytes": size,
                "sha256": observed,
            }
        )
    actual = {
        path.relative_to(output_root).as_posix()
        for path in output_root.rglob("*")
        if path.is_file()
    }
    if actual != listed:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation output artifact universe mismatch"
        )

    for field, expected in (
        ("animation_complete", True),
        ("source_media_rehash_performed", False),
        ("held_out_evaluation_disclosed", False),
        ("human_animated_visual_acceptance_required", True),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if manifest.get(field) is not expected:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                f"P2 ExAvatar animation manifest authority mismatch: {field}"
            )
    result = dict(manifest)
    result["animation_artifacts"] = sorted(
        normalized_artifacts,
        key=lambda item: item["relative_path"],
    )
    return result


def build_animation_execution_receipt(
    manifest: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "version": RECEIPT_VERSION,
        "performer_id": manifest["performer_id"],
        "selected_epoch_id": manifest["selected_epoch_id"],
        "teacher_input_sha256": manifest["teacher_input_sha256"],
        "p2_animation_plan_sha256": manifest["p2_animation_plan_sha256"],
        "p2_exavatar_animation_execution_input_sha256": manifest[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "p2_exavatar_animation_request_sha256": request[
            "p2_exavatar_animation_request_sha256"
        ],
        "exavatar_upstream_commit": PINNED_UPSTREAM_COMMIT,
        "exavatar_subject_id": manifest["exavatar_subject_id"],
        "test_epoch": PINNED_TEST_EPOCH,
        "adapter_revision": manifest["adapter_revision"],
        "motion_driver_source_ref": manifest["motion_driver_source_ref"],
        "motion_frame_count": manifest["motion_frame_count"],
        "motion_frame_ids": manifest["motion_frame_ids"],
        "consumed_checkpoint_sha256": manifest["consumed_checkpoint_sha256"],
        "consumed_identity_artifacts": manifest["consumed_identity_artifacts"],
        "consumed_motion_artifacts": manifest["consumed_motion_artifacts"],
        "animation_artifacts": manifest["animation_artifacts"],
        "artifact_bytes_verified_by_core": True,
        "animation_complete": True,
        "source_media_rehash_performed": False,
        "held_out_evaluation_disclosed": False,
        "human_animated_visual_acceptance_required": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    receipt["p2_exavatar_animation_execution_receipt_sha256"] = _digest(
        receipt,
        omit="p2_exavatar_animation_execution_receipt_sha256",
    )
    return validate_animation_execution_receipt(receipt)


def validate_animation_execution_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_exavatar_animation_request_sha256",
        "exavatar_upstream_commit",
        "exavatar_subject_id",
        "test_epoch",
        "adapter_revision",
        "motion_driver_source_ref",
        "motion_frame_count",
        "motion_frame_ids",
        "consumed_checkpoint_sha256",
        "consumed_identity_artifacts",
        "consumed_motion_artifacts",
        "animation_artifacts",
        "artifact_bytes_verified_by_core",
        "animation_complete",
        "source_media_rehash_performed",
        "held_out_evaluation_disclosed",
        "human_animated_visual_acceptance_required",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_exavatar_animation_execution_receipt_sha256",
    }
    if set(value) != expected_fields:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation execution receipt fields must match v1 exactly"
        )
    if value.get("format") != RECEIPT_FORMAT:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation execution receipt format/version mismatch"
        )
    _strict_v1(value.get("version"), label="P2 ExAvatar animation execution receipt")
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_exavatar_animation_request_sha256",
        "adapter_revision",
        "consumed_checkpoint_sha256",
    ):
        _sha(value.get(field), label=f"P2 ExAvatar animation receipt {field}")
    if value.get("exavatar_upstream_commit") != PINNED_UPSTREAM_COMMIT:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation receipt upstream commit mismatch"
        )
    if value.get("test_epoch") != PINNED_TEST_EPOCH:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation receipt epoch mismatch"
        )
    _text(value.get("performer_id"), label="P2 ExAvatar animation receipt performer", maximum=256)
    _text(value.get("selected_epoch_id"), label="P2 ExAvatar animation receipt epoch id", maximum=256)
    _text(value.get("exavatar_subject_id"), label="P2 ExAvatar animation receipt subject", maximum=160)
    _text(value.get("motion_driver_source_ref"), label="P2 ExAvatar animation receipt driver ref", maximum=64)
    frame_count = value.get("motion_frame_count")
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count < 1:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation receipt frame count is invalid"
        )
    frame_ids = value.get("motion_frame_ids")
    if (
        not isinstance(frame_ids, list)
        or not frame_ids
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in frame_ids)
        or frame_ids != sorted(set(frame_ids))
        or len(frame_ids) != frame_count
    ):
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation receipt frame-id universe is invalid"
        )
    identity = value.get("consumed_identity_artifacts")
    if not isinstance(identity, list) or len(identity) != 4:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation receipt identity universe is invalid"
        )
    seen_identity: set[str] = set()
    for raw in identity:
        if not isinstance(raw, Mapping) or set(raw) != {"kind", "sha256"}:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar animation receipt identity fields must match v1 exactly"
            )
        kind = _text(raw.get("kind"), label="P2 ExAvatar animation receipt identity kind", maximum=64)
        if kind in seen_identity:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar animation receipt repeats identity kind"
            )
        seen_identity.add(kind)
        _sha(raw.get("sha256"), label="P2 ExAvatar animation receipt identity SHA-256")
    if seen_identity != {"shape-param", "face-offset", "joint-offset", "locator-offset"}:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation receipt identity kind universe mismatch"
        )
    motion = value.get("consumed_motion_artifacts")
    if not isinstance(motion, list) or not motion:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation receipt motion universe is invalid"
        )
    seen_motion: set[str] = set()
    for raw in motion:
        if not isinstance(raw, Mapping) or set(raw) != {"relative_path", "sha256"}:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar animation receipt motion fields must match v1 exactly"
            )
        relative = _relative_path(raw.get("relative_path"), label="P2 ExAvatar animation receipt motion path")
        if relative in seen_motion:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar animation receipt repeats motion artifact"
            )
        seen_motion.add(relative)
        _sha(raw.get("sha256"), label="P2 ExAvatar animation receipt motion SHA-256")
    source_ref = _text(
        value.get("motion_driver_source_ref"),
        label="P2 ExAvatar animation receipt driver ref",
        maximum=64,
    )
    required_motion_paths: set[str] = set()
    for frame_id in frame_ids:
        required_motion_paths.update(
            {
                f"tasks/{source_ref}/motion/frames/{frame_id}.png",
                f"tasks/{source_ref}/motion/cam_params/{frame_id}.json",
                f"tasks/{source_ref}/motion/smplx_optimized/smplx_params_smoothed/{frame_id}.json",
            }
        )
    if not required_motion_paths.issubset(seen_motion):
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation receipt omits consumed frame/camera/SMPL-X bytes"
        )
    artifacts = value.get("animation_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation receipt has no animation artifacts"
        )
    seen_artifacts: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != {
            "kind",
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar animation receipt artifact fields must match v1 exactly"
            )
        relative = _relative_path(raw.get("relative_path"), label="P2 ExAvatar animation receipt artifact path")
        if relative in seen_artifacts:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar animation receipt repeats artifact"
            )
        seen_artifacts.add(relative)
        _text(raw.get("kind"), label="P2 ExAvatar animation receipt artifact kind", maximum=64)
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                "P2 ExAvatar animation receipt artifact size is invalid"
            )
        _sha(raw.get("sha256"), label="P2 ExAvatar animation receipt artifact SHA-256")
    for field, expected in (
        ("artifact_bytes_verified_by_core", True),
        ("animation_complete", True),
        ("source_media_rehash_performed", False),
        ("held_out_evaluation_disclosed", False),
        ("human_animated_visual_acceptance_required", True),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP2ExAvatarAnimationRunnerError(
                f"P2 ExAvatar animation receipt authority mismatch: {field}"
            )
    declared = _sha(
        value.get("p2_exavatar_animation_execution_receipt_sha256"),
        label="P2 ExAvatar animation execution receipt SHA-256",
    )
    if _digest(value, omit="p2_exavatar_animation_execution_receipt_sha256") != declared:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation execution receipt digest mismatch"
        )
    return dict(value)


def run_exavatar_animation(
    execution_input: Mapping[str, Any],
    teacher_config: Mapping[str, Any],
    *,
    identity_root: str | Path,
    motion_output_root: str | Path,
    teacher_output_root: str | Path,
    bodyrig_repo_root: str | Path,
    adapter_script: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    request, runtime = build_animation_request(
        execution_input,
        teacher_config,
        identity_root=identity_root,
        motion_output_root=motion_output_root,
        teacher_output_root=teacher_output_root,
        bodyrig_repo_root=bodyrig_repo_root,
        adapter_script=adapter_script,
    )
    root = Path(workspace).expanduser().resolve()
    if root.exists() or root.is_symlink():
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"P2 ExAvatar animation workspace already exists: {root}"
        )
    root.mkdir(parents=True)
    output_root = root / "output"
    output_root.mkdir()
    request_path = root / "request.json"
    log_path = root / "adapter.log"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    converter = make_wsl_path_converter(
        str(runtime["wsl_exe"]),
        str(runtime["distribution"]),
    )
    try:
        linux_request = converter(str(request_path))
        linux_output = converter(str(output_root))
    except (OSError, WslBridgeError) as exc:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"P2 ExAvatar execution path conversion failed: {exc}"
        ) from exc

    invocation = [
        str(runtime["wsl_exe"]),
        "-d",
        str(runtime["distribution"]),
        "--",
        "/usr/bin/env",
        f"PYTHONPATH={request['bodyrig_linux_repo_root']}",
        "PYTHONNOUSERSITE=1",
        str(runtime["linux_python"]),
        request["adapter_linux_path"],
        "--workspace-root",
        str(runtime["linux_workspace_root"]),
        "--runtime-preflight",
        str(runtime["runtime_preflight"]),
        "--bodyrig-request",
        linux_request,
        "--bodyrig-output",
        linux_output,
    ]
    try:
        completed = run_logged_process(
            invocation,
            log_path=log_path,
            timeout_seconds=int(runtime["timeout_seconds"]),
        )
    except subprocess.TimeoutExpired as exc:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"P2 ExAvatar animation timed out after {runtime['timeout_seconds']} seconds"
        ) from exc
    except (OSError, LoggedProcessError) as exc:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"P2 ExAvatar animation process could not complete: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise PhotorealP2ExAvatarAnimationRunnerError(
            f"P2 ExAvatar animation adapter failed with exit code {completed.returncode}"
        )

    manifest_path = output_root / "animation-manifest.json"
    if not manifest_path.is_file():
        raise PhotorealP2ExAvatarAnimationRunnerError(
            "P2 ExAvatar animation adapter did not create animation-manifest.json"
        )
    manifest = _validate_manifest(
        _read_json(manifest_path, label="P2 ExAvatar animation manifest"),
        request=request,
        output_root=output_root,
    )
    receipt = build_animation_execution_receipt(manifest, request=request)
    receipt_path = root / "animation-execution-receipt.json"
    with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return receipt


def run_exavatar_animation_files(
    execution_input_path: str | Path,
    teacher_config_path: str | Path,
    *,
    identity_root: str | Path,
    motion_output_root: str | Path,
    teacher_output_root: str | Path,
    bodyrig_repo_root: str | Path,
    adapter_script: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    return run_exavatar_animation(
        _read_json(execution_input_path, label="P2 ExAvatar animation execution input"),
        _read_json(teacher_config_path, label="ExAvatar teacher config"),
        identity_root=identity_root,
        motion_output_root=motion_output_root,
        teacher_output_root=teacher_output_root,
        bodyrig_repo_root=bodyrig_repo_root,
        adapter_script=adapter_script,
        workspace=workspace,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the pinned ExAvatar P2 animation from accepted identity and TRAIN motion bytes."
    )
    parser.add_argument("--execution-input", type=Path, required=True)
    parser.add_argument("--teacher-config", type=Path, required=True)
    parser.add_argument("--identity-root", type=Path, required=True)
    parser.add_argument("--motion-output-root", type=Path, required=True)
    parser.add_argument("--teacher-output-root", type=Path, required=True)
    parser.add_argument("--bodyrig-repo-root", type=Path, required=True)
    parser.add_argument("--adapter-script", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = run_exavatar_animation_files(
            args.execution_input,
            args.teacher_config,
            identity_root=args.identity_root,
            motion_output_root=args.motion_output_root,
            teacher_output_root=args.teacher_output_root,
            bodyrig_repo_root=args.bodyrig_repo_root,
            adapter_script=args.adapter_script,
            workspace=args.workspace,
        )
    except PhotorealP2ExAvatarAnimationRunnerError as exc:
        print(f"BodyRig P2 ExAvatar animation: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "P2_EXAVATAR_ANIMATION_COMPLETE",
                "motion_driver_source_ref": receipt["motion_driver_source_ref"],
                "motion_frame_count": receipt["motion_frame_count"],
                "animation_artifact_count": len(receipt["animation_artifacts"]),
                "artifact_bytes_verified_by_core": True,
                "held_out_evaluation_disclosed": False,
                "human_animated_visual_acceptance_required": True,
                "p2_animated_teacher_acceptance_authority": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

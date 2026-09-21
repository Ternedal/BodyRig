from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from .logged_process import LoggedProcessError, run_logged_process
from .photoreal_p2_exavatar_animation_runner import (
    MAX_TIMEOUT_SECONDS,
    PINNED_TEST_EPOCH,
    PINNED_UPSTREAM_COMMIT,
    PINNED_UPSTREAM_REPOSITORY,
    PhotorealP2ExAvatarAnimationRunnerError,
    _digest,
    _file_sha,
    _linux_join,
    _read_json as _read_animation_json,
    _relative_path,
    _runtime_from_teacher_config,
    _safe_child,
    _sha,
    _strict_v1,
    _text,
    _verify_file_record,
)
from .photoreal_p2_exavatar_heldout_evaluation_input import (
    DISCLOSURE_PURPOSE,
    PhotorealP2ExAvatarHeldoutEvaluationInputError,
    validate_heldout_evaluation_input,
)
from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter


REQUEST_FORMAT = "bodyrig-photoreal-p2-exavatar-heldout-evaluation-request"
REQUEST_VERSION = 1
MANIFEST_FORMAT = "bodyrig-photoreal-p2-exavatar-heldout-evaluation-manifest"
MANIFEST_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-p2-exavatar-heldout-evaluation-execution-receipt"
RECEIPT_VERSION = 1


class PhotorealP2ExAvatarHeldoutEvaluationRunnerError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    try:
        return _read_animation_json(path, label=label)
    except PhotorealP2ExAvatarAnimationRunnerError as exc:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(str(exc)) from exc


def _core_error(exc: Exception) -> PhotorealP2ExAvatarHeldoutEvaluationRunnerError:
    return PhotorealP2ExAvatarHeldoutEvaluationRunnerError(str(exc))


def build_heldout_evaluation_request(
    evaluation_input: Mapping[str, Any],
    teacher_config: Mapping[str, Any],
    *,
    identity_root: str | Path,
    motion_output_root: str | Path,
    teacher_output_root: str | Path,
    bodyrig_repo_root: str | Path,
    adapter_script: str | Path,
) -> tuple[dict[str, Any], dict[str, str | int]]:
    try:
        authority = validate_heldout_evaluation_input(evaluation_input)
        runtime = _runtime_from_teacher_config(teacher_config)
    except (
        PhotorealP2ExAvatarHeldoutEvaluationInputError,
        PhotorealP2ExAvatarAnimationRunnerError,
    ) as exc:
        raise _core_error(exc) from exc

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
            raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
                f"P2 held-out evaluation {label} is missing/not regular: {root}"
            )
    if not adapter.is_file() or adapter.is_symlink():
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            f"P2 held-out evaluation adapter script is missing/not regular: {adapter}"
        )

    runtime_wsl = str(runtime["wsl_exe"])
    runtime_distribution = str(runtime["distribution"])
    converter = make_wsl_path_converter(runtime_wsl, runtime_distribution)
    try:
        linux_identity_root = converter(str(identity_dir))
        linux_motion_root = converter(str(motion_dir))
        linux_teacher_root = converter(str(teacher_dir))
        linux_repo_root = converter(str(repo_dir))
        linux_adapter = converter(str(adapter))
    except (OSError, WslBridgeError) as exc:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            f"P2 held-out evaluation Windows->WSL path conversion failed: {exc}"
        ) from exc

    try:
        checkpoint = _verify_file_record(
            teacher_dir,
            authority["teacher_checkpoint"],
            path_field="relative_path",
            label="frozen teacher checkpoint",
        )
    except PhotorealP2ExAvatarAnimationRunnerError as exc:
        raise _core_error(exc) from exc
    checkpoint["linux_source_path"] = _linux_join(
        linux_teacher_root,
        checkpoint["relative_path"],
    )

    verified_identity: list[dict[str, Any]] = []
    try:
        for raw in authority["identity_artifacts"]:
            verified = _verify_file_record(
                identity_dir,
                raw,
                path_field="export_relative_path",
                label="held-out evaluation identity artifact",
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
    except PhotorealP2ExAvatarAnimationRunnerError as exc:
        raise _core_error(exc) from exc

    motion = authority["held_out_motion"]
    verified_motion: list[dict[str, Any]] = []
    try:
        for raw in motion["artifacts"]:
            verified = _verify_file_record(
                motion_dir,
                raw,
                path_field="relative_path",
                label="held-out evaluation motion artifact",
            )
            verified["linux_source_path"] = _linux_join(
                linux_motion_root,
                verified["relative_path"],
            )
            verified_motion.append(verified)
    except PhotorealP2ExAvatarAnimationRunnerError as exc:
        raise _core_error(exc) from exc

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
        "train_animation_execution_receipt_sha256": authority[
            "train_animation_execution_receipt_sha256"
        ],
        "p2_exavatar_heldout_evaluation_input_sha256": authority[
            "p2_exavatar_heldout_evaluation_input_sha256"
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
        "teacher_checkpoint": checkpoint,
        "identity_artifacts": sorted(
            verified_identity,
            key=lambda item: item["kind"],
        ),
        "held_out_motion": {
            "source_ref": motion["source_ref"],
            "split": "evaluation",
            "role": "held-out-motion-validation",
            "selected_eye": motion["selected_eye"],
            "selected_viewport_id": motion["selected_viewport_id"],
            "anchor_observation_ref": motion["anchor_observation_ref"],
            "anchor_frame_sha256": motion["anchor_frame_sha256"],
            "window_start_seconds": motion["window_start_seconds"],
            "window_end_seconds": motion["window_end_seconds"],
            "window_duration_seconds": motion["window_duration_seconds"],
            "motion_path_relative": motion["motion_path_relative"],
            "frame_count": motion["frame_count"],
            "frame_ids": list(motion["frame_ids"]),
            "artifacts": sorted(
                verified_motion,
                key=lambda item: item["relative_path"],
            ),
        },
        "evaluation_mode": "inference-only-held-out",
        "held_out_disclosure_purpose": DISCLOSURE_PURPOSE,
        "teacher_training_authorized": False,
        "checkpoint_mutation_authorized": False,
        "source_media_rehash_performed": False,
        "held_out_evaluation_disclosed": True,
        "human_animated_visual_acceptance_required": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    request["p2_exavatar_heldout_evaluation_request_sha256"] = _digest(
        request,
        omit="p2_exavatar_heldout_evaluation_request_sha256",
    )
    return request, runtime


def _validate_manifest(
    manifest: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    expected = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "train_animation_execution_receipt_sha256",
        "p2_exavatar_heldout_evaluation_input_sha256",
        "p2_exavatar_heldout_evaluation_request_sha256",
        "exavatar_upstream_commit",
        "exavatar_subject_id",
        "test_epoch",
        "adapter_revision",
        "held_out_source_ref",
        "held_out_frame_count",
        "held_out_frame_ids",
        "consumed_checkpoint_sha256",
        "consumed_identity_artifacts",
        "consumed_held_out_motion_artifacts",
        "evaluation_artifacts",
        "evaluation_complete",
        "inference_only",
        "teacher_training_performed",
        "checkpoint_mutation_performed",
        "source_media_rehash_performed",
        "held_out_evaluation_disclosed",
        "held_out_disclosure_purpose",
        "human_animated_visual_acceptance_required",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    }
    if set(manifest) != expected:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation manifest fields must match v1 exactly"
        )
    if manifest.get("format") != MANIFEST_FORMAT:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation manifest format/version mismatch"
        )
    try:
        _strict_v1(manifest.get("version"), label="P2 held-out evaluation manifest")
    except PhotorealP2ExAvatarAnimationRunnerError as exc:
        raise _core_error(exc) from exc

    direct_fields = (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "train_animation_execution_receipt_sha256",
        "p2_exavatar_heldout_evaluation_input_sha256",
        "p2_exavatar_heldout_evaluation_request_sha256",
        "exavatar_subject_id",
        "test_epoch",
        "adapter_revision",
    )
    for field in direct_fields:
        if manifest.get(field) != request.get(field):
            raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
                f"P2 held-out evaluation manifest provenance mismatch: {field}"
            )
    if manifest.get("exavatar_upstream_commit") != PINNED_UPSTREAM_COMMIT:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation manifest upstream commit mismatch"
        )

    motion = request["held_out_motion"]
    if manifest.get("held_out_source_ref") != motion["source_ref"]:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation manifest source mismatch"
        )
    if manifest.get("held_out_frame_count") != motion["frame_count"]:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation manifest frame count mismatch"
        )
    if manifest.get("held_out_frame_ids") != motion["frame_ids"]:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation manifest frame-id universe mismatch"
        )
    if manifest.get("consumed_checkpoint_sha256") != request["teacher_checkpoint"]["sha256"]:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation consumed different checkpoint bytes"
        )

    expected_identity = {
        item["kind"]: item["sha256"] for item in request["identity_artifacts"]
    }
    consumed_identity = manifest.get("consumed_identity_artifacts")
    if not isinstance(consumed_identity, list):
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation consumed identity universe is invalid"
        )
    observed_identity: dict[str, str] = {}
    for raw in consumed_identity:
        if not isinstance(raw, Mapping) or set(raw) != {"kind", "sha256"}:
            raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
                "P2 held-out evaluation consumed identity fields must match v1 exactly"
            )
        kind = _text(raw.get("kind"), label="P2 held-out consumed identity kind", maximum=64)
        if kind in observed_identity:
            raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
                "P2 held-out evaluation repeats consumed identity kind"
            )
        try:
            observed_identity[kind] = _sha(
                raw.get("sha256"),
                label="P2 held-out consumed identity SHA-256",
            )
        except PhotorealP2ExAvatarAnimationRunnerError as exc:
            raise _core_error(exc) from exc
    if observed_identity != expected_identity:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation consumed different identity bytes"
        )

    expected_motion = {
        item["relative_path"]: item["sha256"]
        for item in request["held_out_motion"]["artifacts"]
    }
    consumed_motion = manifest.get("consumed_held_out_motion_artifacts")
    if not isinstance(consumed_motion, list):
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation consumed motion universe is invalid"
        )
    observed_motion: dict[str, str] = {}
    for raw in consumed_motion:
        if not isinstance(raw, Mapping) or set(raw) != {"relative_path", "sha256"}:
            raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
                "P2 held-out evaluation consumed motion fields must match v1 exactly"
            )
        try:
            relative = _relative_path(
                raw.get("relative_path"),
                label="P2 held-out consumed motion path",
            )
            digest = _sha(
                raw.get("sha256"),
                label="P2 held-out consumed motion SHA-256",
            )
        except PhotorealP2ExAvatarAnimationRunnerError as exc:
            raise _core_error(exc) from exc
        if relative in observed_motion:
            raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
                "P2 held-out evaluation repeats consumed motion artifact"
            )
        observed_motion[relative] = digest
    if observed_motion != expected_motion:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation consumed different motion bytes"
        )

    artifacts = manifest.get("evaluation_artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation must produce exactly one review animation"
        )
    raw_artifact = artifacts[0]
    if not isinstance(raw_artifact, Mapping) or set(raw_artifact) != {
        "kind",
        "relative_path",
        "size_bytes",
        "sha256",
    }:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation artifact fields must match v1 exactly"
        )
    if raw_artifact.get("kind") != "heldout-animation-review-video":
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation artifact kind mismatch"
        )
    try:
        relative, path = _safe_child(
            output_root,
            raw_artifact.get("relative_path"),
            label="P2 held-out evaluation artifact path",
        )
    except PhotorealP2ExAvatarAnimationRunnerError as exc:
        raise _core_error(exc) from exc
    if relative != "review/heldout-animation.mp4":
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation artifact path mismatch"
        )
    size = raw_artifact.get("size_bytes")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
        or not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != size
    ):
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation artifact size/path mismatch"
        )
    try:
        observed_sha = _file_sha(path)
        declared_sha = _sha(
            raw_artifact.get("sha256"),
            label="P2 held-out evaluation artifact SHA-256",
        )
    except PhotorealP2ExAvatarAnimationRunnerError as exc:
        raise _core_error(exc) from exc
    if observed_sha != declared_sha:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation artifact bytes drifted"
        )
    actual_files = {
        item.relative_to(output_root).as_posix()
        for item in output_root.rglob("*")
        if item.is_file()
    }
    if actual_files != {
        "heldout-evaluation-manifest.json",
        "review/heldout-animation.mp4",
    }:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation output artifact universe mismatch"
        )

    if manifest.get("held_out_disclosure_purpose") != DISCLOSURE_PURPOSE:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation disclosure purpose mismatch"
        )
    for field, expected_value in (
        ("evaluation_complete", True),
        ("inference_only", True),
        ("teacher_training_performed", False),
        ("checkpoint_mutation_performed", False),
        ("source_media_rehash_performed", False),
        ("held_out_evaluation_disclosed", True),
        ("human_animated_visual_acceptance_required", True),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if manifest.get(field) is not expected_value:
            raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
                f"P2 held-out evaluation manifest authority mismatch: {field}"
            )
    result = dict(manifest)
    result["evaluation_artifacts"] = [
        {
            "kind": "heldout-animation-review-video",
            "relative_path": relative,
            "size_bytes": size,
            "sha256": observed_sha,
        }
    ]
    return result


def build_heldout_evaluation_receipt(
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
        "p2_exavatar_animation_execution_input_sha256": manifest[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "train_animation_execution_receipt_sha256": manifest[
            "train_animation_execution_receipt_sha256"
        ],
        "p2_exavatar_heldout_evaluation_input_sha256": manifest[
            "p2_exavatar_heldout_evaluation_input_sha256"
        ],
        "p2_exavatar_heldout_evaluation_request_sha256": request[
            "p2_exavatar_heldout_evaluation_request_sha256"
        ],
        "exavatar_upstream_commit": PINNED_UPSTREAM_COMMIT,
        "exavatar_subject_id": manifest["exavatar_subject_id"],
        "test_epoch": PINNED_TEST_EPOCH,
        "adapter_revision": manifest["adapter_revision"],
        "held_out_source_ref": manifest["held_out_source_ref"],
        "held_out_frame_count": manifest["held_out_frame_count"],
        "held_out_frame_ids": manifest["held_out_frame_ids"],
        "consumed_checkpoint_sha256": manifest["consumed_checkpoint_sha256"],
        "consumed_identity_artifacts": manifest["consumed_identity_artifacts"],
        "consumed_held_out_motion_artifacts": manifest[
            "consumed_held_out_motion_artifacts"
        ],
        "evaluation_artifacts": manifest["evaluation_artifacts"],
        "artifact_bytes_verified_by_core": True,
        "evaluation_complete": True,
        "inference_only": True,
        "teacher_training_performed": False,
        "checkpoint_mutation_performed": False,
        "source_media_rehash_performed": False,
        "held_out_evaluation_disclosed": True,
        "held_out_disclosure_purpose": DISCLOSURE_PURPOSE,
        "human_animated_visual_acceptance_required": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p2_exavatar_heldout_evaluation_execution_receipt_sha256"] = _digest(
        result,
        omit="p2_exavatar_heldout_evaluation_execution_receipt_sha256",
    )
    return validate_heldout_evaluation_receipt(result)


def validate_heldout_evaluation_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "train_animation_execution_receipt_sha256",
        "p2_exavatar_heldout_evaluation_input_sha256",
        "p2_exavatar_heldout_evaluation_request_sha256",
        "exavatar_upstream_commit",
        "exavatar_subject_id",
        "test_epoch",
        "adapter_revision",
        "held_out_source_ref",
        "held_out_frame_count",
        "held_out_frame_ids",
        "consumed_checkpoint_sha256",
        "consumed_identity_artifacts",
        "consumed_held_out_motion_artifacts",
        "evaluation_artifacts",
        "artifact_bytes_verified_by_core",
        "evaluation_complete",
        "inference_only",
        "teacher_training_performed",
        "checkpoint_mutation_performed",
        "source_media_rehash_performed",
        "held_out_evaluation_disclosed",
        "held_out_disclosure_purpose",
        "human_animated_visual_acceptance_required",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_exavatar_heldout_evaluation_execution_receipt_sha256",
    }
    if set(value) != expected:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation execution receipt fields must match v1 exactly"
        )
    if value.get("format") != RECEIPT_FORMAT:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation execution receipt format/version mismatch"
        )
    try:
        _strict_v1(
            value.get("version"),
            label="P2 held-out evaluation execution receipt",
        )
        for field in (
            "teacher_input_sha256",
            "p2_animation_plan_sha256",
            "p2_exavatar_animation_execution_input_sha256",
            "train_animation_execution_receipt_sha256",
            "p2_exavatar_heldout_evaluation_input_sha256",
            "p2_exavatar_heldout_evaluation_request_sha256",
            "adapter_revision",
            "consumed_checkpoint_sha256",
        ):
            _sha(
                value.get(field),
                label=f"P2 held-out evaluation receipt {field}",
            )
    except PhotorealP2ExAvatarAnimationRunnerError as exc:
        raise _core_error(exc) from exc
    if value.get("exavatar_upstream_commit") != PINNED_UPSTREAM_COMMIT:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation receipt upstream commit mismatch"
        )
    if value.get("test_epoch") != PINNED_TEST_EPOCH:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation receipt epoch mismatch"
        )
    source_ref = _text(
        value.get("held_out_source_ref"),
        label="P2 held-out evaluation receipt source ref",
        maximum=64,
    )
    frame_count = value.get("held_out_frame_count")
    frame_ids = value.get("held_out_frame_ids")
    if (
        isinstance(frame_count, bool)
        or not isinstance(frame_count, int)
        or frame_count < 1
        or not isinstance(frame_ids, list)
        or len(frame_ids) != frame_count
        or frame_ids != sorted(set(frame_ids))
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in frame_ids)
    ):
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation receipt frame universe is invalid"
        )

    identity = value.get("consumed_identity_artifacts")
    if not isinstance(identity, list) or len(identity) != 4:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation receipt identity universe is invalid"
        )
    identity_map: dict[str, str] = {}
    for raw in identity:
        if not isinstance(raw, Mapping) or set(raw) != {"kind", "sha256"}:
            raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
                "P2 held-out evaluation receipt identity fields must match v1 exactly"
            )
        kind = _text(raw.get("kind"), label="P2 held-out evaluation receipt identity kind", maximum=64)
        if kind in identity_map:
            raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
                "P2 held-out evaluation receipt repeats identity kind"
            )
        try:
            identity_map[kind] = _sha(
                raw.get("sha256"),
                label="P2 held-out evaluation receipt identity SHA-256",
            )
        except PhotorealP2ExAvatarAnimationRunnerError as exc:
            raise _core_error(exc) from exc
    if set(identity_map) != {"shape-param", "face-offset", "joint-offset", "locator-offset"}:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation receipt identity kind universe mismatch"
        )

    motion = value.get("consumed_held_out_motion_artifacts")
    if not isinstance(motion, list) or not motion:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation receipt motion universe is invalid"
        )
    motion_paths: set[str] = set()
    for raw in motion:
        if not isinstance(raw, Mapping) or set(raw) != {"relative_path", "sha256"}:
            raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
                "P2 held-out evaluation receipt motion fields must match v1 exactly"
            )
        try:
            relative = _relative_path(
                raw.get("relative_path"),
                label="P2 held-out evaluation receipt motion path",
            )
            _sha(
                raw.get("sha256"),
                label="P2 held-out evaluation receipt motion SHA-256",
            )
        except PhotorealP2ExAvatarAnimationRunnerError as exc:
            raise _core_error(exc) from exc
        if relative in motion_paths:
            raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
                "P2 held-out evaluation receipt repeats motion artifact"
            )
        motion_paths.add(relative)
    required_motion_paths: set[str] = set()
    for frame_id in frame_ids:
        required_motion_paths.update(
            {
                f"tasks/{source_ref}/motion/frames/{frame_id}.png",
                f"tasks/{source_ref}/motion/cam_params/{frame_id}.json",
                f"tasks/{source_ref}/motion/smplx_optimized/smplx_params_smoothed/{frame_id}.json",
            }
        )
    if not required_motion_paths.issubset(motion_paths):
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation receipt omits frame/camera/SMPL-X bytes"
        )

    artifacts = value.get("evaluation_artifacts")
    if (
        not isinstance(artifacts, list)
        or len(artifacts) != 1
        or not isinstance(artifacts[0], Mapping)
        or set(artifacts[0]) != {"kind", "relative_path", "size_bytes", "sha256"}
        or artifacts[0].get("kind") != "heldout-animation-review-video"
        or artifacts[0].get("relative_path") != "review/heldout-animation.mp4"
    ):
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation receipt output artifact contract mismatch"
        )
    size = artifacts[0].get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation receipt output size is invalid"
        )
    try:
        _sha(
            artifacts[0].get("sha256"),
            label="P2 held-out evaluation receipt output SHA-256",
        )
    except PhotorealP2ExAvatarAnimationRunnerError as exc:
        raise _core_error(exc) from exc

    if value.get("held_out_disclosure_purpose") != DISCLOSURE_PURPOSE:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation receipt disclosure purpose mismatch"
        )
    for field, expected_value in (
        ("artifact_bytes_verified_by_core", True),
        ("evaluation_complete", True),
        ("inference_only", True),
        ("teacher_training_performed", False),
        ("checkpoint_mutation_performed", False),
        ("source_media_rehash_performed", False),
        ("held_out_evaluation_disclosed", True),
        ("human_animated_visual_acceptance_required", True),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected_value:
            raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
                f"P2 held-out evaluation receipt authority mismatch: {field}"
            )
    try:
        declared = _sha(
            value.get("p2_exavatar_heldout_evaluation_execution_receipt_sha256"),
            label="P2 held-out evaluation execution receipt SHA-256",
        )
    except PhotorealP2ExAvatarAnimationRunnerError as exc:
        raise _core_error(exc) from exc
    if _digest(
        value,
        omit="p2_exavatar_heldout_evaluation_execution_receipt_sha256",
    ) != declared:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation execution receipt digest mismatch"
        )
    return dict(value)


def run_heldout_evaluation(
    evaluation_input: Mapping[str, Any],
    teacher_config: Mapping[str, Any],
    *,
    identity_root: str | Path,
    motion_output_root: str | Path,
    teacher_output_root: str | Path,
    bodyrig_repo_root: str | Path,
    adapter_script: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    request, runtime = build_heldout_evaluation_request(
        evaluation_input,
        teacher_config,
        identity_root=identity_root,
        motion_output_root=motion_output_root,
        teacher_output_root=teacher_output_root,
        bodyrig_repo_root=bodyrig_repo_root,
        adapter_script=adapter_script,
    )
    root = Path(workspace).expanduser().resolve()
    if root.exists() or root.is_symlink():
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            f"P2 held-out evaluation workspace already exists: {root}"
        )
    root.mkdir(parents=True)
    output_root = root / "output"
    output_root.mkdir()
    request_path = root / "request.json"
    log_path = root / "adapter.log"
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
    converter = make_wsl_path_converter(
        str(runtime["wsl_exe"]),
        str(runtime["distribution"]),
    )
    try:
        linux_request = converter(str(request_path))
        linux_output = converter(str(output_root))
    except (OSError, WslBridgeError) as exc:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            f"P2 held-out evaluation path conversion failed: {exc}"
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
    timeout = int(runtime["timeout_seconds"])
    if not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation timeout is invalid"
        )
    try:
        completed = run_logged_process(
            invocation,
            log_path=log_path,
            timeout_seconds=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            f"P2 held-out evaluation timed out after {timeout} seconds"
        ) from exc
    except (OSError, LoggedProcessError) as exc:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            f"P2 held-out evaluation process could not complete: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            f"P2 held-out evaluation adapter failed with exit code {completed.returncode}"
        )

    manifest_path = output_root / "heldout-evaluation-manifest.json"
    if not manifest_path.is_file():
        raise PhotorealP2ExAvatarHeldoutEvaluationRunnerError(
            "P2 held-out evaluation adapter did not create heldout-evaluation-manifest.json"
        )
    manifest = _validate_manifest(
        _read_json(
            manifest_path,
            label="P2 held-out evaluation manifest",
        ),
        request=request,
        output_root=output_root,
    )
    receipt = build_heldout_evaluation_receipt(manifest, request=request)
    receipt_path = root / "heldout-evaluation-execution-receipt.json"
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


def run_heldout_evaluation_files(
    evaluation_input_path: str | Path,
    teacher_config_path: str | Path,
    *,
    identity_root: str | Path,
    motion_output_root: str | Path,
    teacher_output_root: str | Path,
    bodyrig_repo_root: str | Path,
    adapter_script: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    return run_heldout_evaluation(
        _read_json(evaluation_input_path, label="P2 held-out evaluation input"),
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
        description="Run frozen-teacher ExAvatar inference on one HELD-OUT EVALUATION motion path."
    )
    parser.add_argument("--evaluation-input", type=Path, required=True)
    parser.add_argument("--teacher-config", type=Path, required=True)
    parser.add_argument("--identity-root", type=Path, required=True)
    parser.add_argument("--motion-output-root", type=Path, required=True)
    parser.add_argument("--teacher-output-root", type=Path, required=True)
    parser.add_argument("--bodyrig-repo-root", type=Path, required=True)
    parser.add_argument("--adapter-script", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = run_heldout_evaluation_files(
            args.evaluation_input,
            args.teacher_config,
            identity_root=args.identity_root,
            motion_output_root=args.motion_output_root,
            teacher_output_root=args.teacher_output_root,
            bodyrig_repo_root=args.bodyrig_repo_root,
            adapter_script=args.adapter_script,
            workspace=args.workspace,
        )
    except PhotorealP2ExAvatarHeldoutEvaluationRunnerError as exc:
        print(f"BodyRig P2 ExAvatar held-out evaluation: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "P2_EXAVATAR_HELDOUT_EVALUATION_COMPLETE",
                "held_out_source_ref": receipt["held_out_source_ref"],
                "held_out_frame_count": receipt["held_out_frame_count"],
                "inference_only": True,
                "teacher_training_performed": False,
                "checkpoint_mutation_performed": False,
                "artifact_bytes_verified_by_core": True,
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

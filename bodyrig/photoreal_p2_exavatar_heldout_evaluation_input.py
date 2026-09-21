from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p2_exavatar_animation_execution_input import (
    PhotorealP2ExAvatarAnimationExecutionInputError,
    validate_exavatar_animation_execution_input,
)
from .photoreal_p2_exavatar_animation_runner import (
    PhotorealP2ExAvatarAnimationRunnerError,
    validate_animation_execution_receipt,
)
from .photoreal_p2_motion_preparation_runner import (
    PhotorealP2MotionPreparationRunnerError,
    validate_motion_preparation_receipt,
)


FORMAT = "bodyrig-photoreal-p2-exavatar-heldout-evaluation-input"
VERSION = 1
DISCLOSURE_PURPOSE = "post-training-inference-only-evaluation"


class PhotorealP2ExAvatarHeldoutEvaluationInputError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            f"{label} must be a JSON object"
        )
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            f"{label} format/version mismatch"
        )
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
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
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 ExAvatar held-out evaluation input cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
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
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            f"{label} escapes its root"
        )
    return clean


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative_path(relative, label=label)
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            f"{label} escapes its root"
        ) from exc
    return clean, target


def _verify_record(
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
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            f"{label} size/path drifted: {relative}"
        )
    expected = _sha(record.get("sha256"), label=f"{label} SHA-256")
    observed = _file_sha(path)
    if observed != expected:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            f"{label} bytes drifted: {relative}"
        )
    return {
        "relative_path": relative,
        "size_bytes": size,
        "sha256": observed,
    }


def _verify_evaluation_motion(
    task: Mapping[str, Any],
    *,
    motion_output_root: Path,
) -> dict[str, Any]:
    source_ref = _text(
        task.get("source_ref"),
        label="P2 held-out evaluation source ref",
        maximum=64,
    )
    if task.get("split") != "evaluation" or task.get("role") != "held-out-motion-validation":
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation input requires an EVALUATION validation task"
        )
    motion_path = _relative_path(
        task.get("motion_path_relative"),
        label="P2 held-out evaluation motion path",
    )
    if motion_path != f"tasks/{source_ref}/motion":
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation motion path is not canonical"
        )

    artifacts = task.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation task contains no artifacts"
        )
    normalized: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    frame_ids: set[int] = set()
    camera_ids: set[int] = set()
    smplx_ids: set[int] = set()
    prefix = motion_path.rstrip("/") + "/"

    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != {
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                "P2 held-out evaluation artifact fields must match v1 exactly"
            )
        verified = _verify_record(
            motion_output_root,
            raw,
            path_field="relative_path",
            label="P2 held-out evaluation artifact",
        )
        relative = verified["relative_path"]
        if relative in seen_paths or not relative.startswith(prefix):
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                "P2 held-out evaluation artifact universe mismatch"
            )
        seen_paths.add(relative)
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
        normalized.append(verified)

    if not frame_ids or frame_ids != camera_ids or frame_ids != smplx_ids:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation frame/camera/SMPL-X ids are not aligned"
        )
    frame_count = task.get("frame_count")
    if (
        isinstance(frame_count, bool)
        or not isinstance(frame_count, int)
        or frame_count != len(frame_ids)
    ):
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation frame count mismatch"
        )

    start = task.get("window_start_seconds")
    end = task.get("window_end_seconds")
    duration = task.get("window_duration_seconds")
    for raw, label in (
        (start, "window start"),
        (end, "window end"),
        (duration, "window duration"),
    ):
        if (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or not math.isfinite(float(raw))
        ):
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                f"P2 held-out evaluation {label} is invalid"
            )
    if (
        float(start) < 0
        or float(end) <= float(start)
        or round(float(end) - float(start), 6) != round(float(duration), 6)
    ):
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation window timing is inconsistent"
        )

    return {
        "source_ref": source_ref,
        "split": "evaluation",
        "role": "held-out-motion-validation",
        "normalization_action": _text(
            task.get("normalization_action"),
            label="P2 held-out evaluation normalization action",
            maximum=128,
        ),
        "selected_eye": _text(
            task.get("selected_eye"),
            label="P2 held-out evaluation selected eye",
            maximum=16,
        ),
        "selected_viewport_id": task.get("selected_viewport_id"),
        "anchor_observation_ref": _text(
            task.get("anchor_observation_ref"),
            label="P2 held-out evaluation anchor observation ref",
            maximum=64,
        ),
        "anchor_frame_sha256": _sha(
            task.get("anchor_frame_sha256"),
            label="P2 held-out evaluation anchor frame SHA-256",
        ),
        "window_start_seconds": start,
        "window_end_seconds": end,
        "window_duration_seconds": duration,
        "motion_path_relative": motion_path,
        "frame_count": frame_count,
        "frame_ids": sorted(frame_ids),
        "artifacts": sorted(normalized, key=lambda item: item["relative_path"]),
    }


def build_heldout_evaluation_input(
    execution_input: Mapping[str, Any],
    train_execution_receipt: Mapping[str, Any],
    motion_preparation_receipt: Mapping[str, Any],
    *,
    identity_root: str | Path,
    teacher_output_root: str | Path,
    motion_output_root: str | Path,
    heldout_source_ref: str,
) -> dict[str, Any]:
    try:
        accepted_input = validate_exavatar_animation_execution_input(execution_input)
        train_receipt = validate_animation_execution_receipt(train_execution_receipt)
        motion_receipt = validate_motion_preparation_receipt(motion_preparation_receipt)
    except (
        PhotorealP2ExAvatarAnimationExecutionInputError,
        PhotorealP2ExAvatarAnimationRunnerError,
        PhotorealP2MotionPreparationRunnerError,
    ) as exc:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            f"P2 held-out evaluation authority readback failed: {exc}"
        ) from exc

    for field in ("performer_id", "selected_epoch_id", "teacher_input_sha256", "p2_animation_plan_sha256"):
        expected = accepted_input.get(field)
        if train_receipt.get(field) != expected or motion_receipt.get(field) != expected:
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                f"P2 held-out evaluation lineage mismatch: {field}"
            )
    if (
        train_receipt.get("p2_exavatar_animation_execution_input_sha256")
        != accepted_input.get("p2_exavatar_animation_execution_input_sha256")
    ):
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "TRAIN animation execution belongs to a different accepted execution input"
        )
    if train_receipt.get("consumed_checkpoint_sha256") != accepted_input["teacher_checkpoint"]["sha256"]:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "TRAIN animation execution used different checkpoint bytes"
        )
    for field, expected in (
        ("animation_complete", True),
        ("inference_only", True),
        ("teacher_training_performed", False),
        ("checkpoint_mutation_performed", False),
        ("held_out_evaluation_disclosed", False),
        ("human_animated_visual_acceptance_required", True),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("production_activation", False),
    ):
        if train_receipt.get(field) is not expected:
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                f"TRAIN animation did not preserve frozen-teacher boundary: {field}"
            )

    requested_ref = _text(
        heldout_source_ref,
        label="P2 held-out evaluation source ref",
        maximum=64,
    )
    if requested_ref == train_receipt.get("motion_driver_source_ref"):
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation source cannot reuse the TRAIN motion driver"
        )
    matches = [
        raw
        for raw in motion_receipt.get("task_results", [])
        if isinstance(raw, Mapping) and raw.get("source_ref") == requested_ref
    ]
    if len(matches) != 1:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "selected P2 held-out evaluation task is not unique"
        )

    identity_dir = Path(identity_root).expanduser().resolve()
    teacher_dir = Path(teacher_output_root).expanduser().resolve()
    motion_dir = Path(motion_output_root).expanduser().resolve()
    for root, label in (
        (identity_dir, "identity root"),
        (teacher_dir, "teacher output root"),
        (motion_dir, "motion output root"),
    ):
        if not root.is_dir() or root.is_symlink():
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                f"P2 held-out evaluation {label} is missing/not regular: {root}"
            )

    checkpoint = _verify_record(
        teacher_dir,
        accepted_input["teacher_checkpoint"],
        path_field="relative_path",
        label="frozen teacher checkpoint",
    )
    if checkpoint["sha256"] != train_receipt["consumed_checkpoint_sha256"]:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "frozen teacher checkpoint drifted after TRAIN animation"
        )

    identity_artifacts: list[dict[str, Any]] = []
    for raw in accepted_input["identity_artifacts"]:
        verified = _verify_record(
            identity_dir,
            raw,
            path_field="export_relative_path",
            label="accepted ExAvatar identity artifact",
        )
        identity_artifacts.append(
            {
                "kind": raw["kind"],
                "source_relative_path": raw["source_relative_path"],
                "export_relative_path": verified["relative_path"],
                "size_bytes": verified["size_bytes"],
                "sha256": verified["sha256"],
            }
        )

    evaluation_motion = _verify_evaluation_motion(
        matches[0],
        motion_output_root=motion_dir,
    )

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": accepted_input["performer_id"],
        "selected_epoch_id": accepted_input["selected_epoch_id"],
        "teacher_input_sha256": accepted_input["teacher_input_sha256"],
        "p2_animation_plan_sha256": accepted_input["p2_animation_plan_sha256"],
        "p2_exavatar_animation_execution_input_sha256": accepted_input[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "train_animation_execution_receipt_sha256": train_receipt[
            "p2_exavatar_animation_execution_receipt_sha256"
        ],
        "p2_motion_preparation_receipt_sha256": motion_receipt[
            "p2_motion_preparation_receipt_sha256"
        ],
        "exavatar_workspace_sha256": accepted_input["exavatar_workspace_sha256"],
        "exavatar_preprocess_state_sha256": accepted_input[
            "exavatar_preprocess_state_sha256"
        ],
        "exavatar_subject_id": accepted_input["exavatar_subject_id"],
        "teacher_checkpoint": checkpoint,
        "identity_artifacts": sorted(identity_artifacts, key=lambda item: item["kind"]),
        "identity_artifact_count": len(identity_artifacts),
        "held_out_motion": evaluation_motion,
        "frozen_teacher_checkpoint_bytes_reverified": True,
        "identity_artifact_bytes_reverified": True,
        "held_out_motion_artifact_bytes_reverified": True,
        "train_animation_complete": True,
        "train_animation_inference_only": True,
        "held_out_evaluation_disclosed_to_animation": True,
        "held_out_disclosure_purpose": DISCLOSURE_PURPOSE,
        "teacher_training_authorized": False,
        "checkpoint_mutation_authorized": False,
        "p2_heldout_animation_evaluation_authorized": True,
        "human_animated_visual_acceptance_required": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p2_exavatar_heldout_evaluation_input_sha256"] = _digest(
        result,
        omit="p2_exavatar_heldout_evaluation_input_sha256",
    )
    return validate_heldout_evaluation_input(result)


def validate_heldout_evaluation_input(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "train_animation_execution_receipt_sha256",
        "p2_motion_preparation_receipt_sha256",
        "exavatar_workspace_sha256",
        "exavatar_preprocess_state_sha256",
        "exavatar_subject_id",
        "teacher_checkpoint",
        "identity_artifacts",
        "identity_artifact_count",
        "held_out_motion",
        "frozen_teacher_checkpoint_bytes_reverified",
        "identity_artifact_bytes_reverified",
        "held_out_motion_artifact_bytes_reverified",
        "train_animation_complete",
        "train_animation_inference_only",
        "held_out_evaluation_disclosed_to_animation",
        "held_out_disclosure_purpose",
        "teacher_training_authorized",
        "checkpoint_mutation_authorized",
        "p2_heldout_animation_evaluation_authorized",
        "human_animated_visual_acceptance_required",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_exavatar_heldout_evaluation_input_sha256",
    }
    if set(value) != expected:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 ExAvatar held-out evaluation input fields must match v1 exactly"
        )
    if value.get("format") != FORMAT:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 ExAvatar held-out evaluation input format/version mismatch"
        )
    _strict_v1(value.get("version"), label="P2 ExAvatar held-out evaluation input")
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "train_animation_execution_receipt_sha256",
        "p2_motion_preparation_receipt_sha256",
        "exavatar_workspace_sha256",
        "exavatar_preprocess_state_sha256",
    ):
        _sha(value.get(field), label=f"P2 held-out evaluation input {field}")
    _text(value.get("performer_id"), label="P2 held-out evaluation performer", maximum=256)
    _text(value.get("selected_epoch_id"), label="P2 held-out evaluation epoch", maximum=256)
    _text(value.get("exavatar_subject_id"), label="P2 held-out evaluation subject", maximum=160)

    checkpoint = value.get("teacher_checkpoint")
    if not isinstance(checkpoint, Mapping) or set(checkpoint) != {
        "relative_path",
        "size_bytes",
        "sha256",
    }:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation checkpoint fields must match v1 exactly"
        )
    _relative_path(checkpoint.get("relative_path"), label="P2 held-out evaluation checkpoint path")
    checkpoint_size = checkpoint.get("size_bytes")
    if isinstance(checkpoint_size, bool) or not isinstance(checkpoint_size, int) or checkpoint_size < 1:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation checkpoint size is invalid"
        )
    _sha(checkpoint.get("sha256"), label="P2 held-out evaluation checkpoint SHA-256")

    identity = value.get("identity_artifacts")
    identity_count = value.get("identity_artifact_count")
    if (
        not isinstance(identity, list)
        or isinstance(identity_count, bool)
        or not isinstance(identity_count, int)
        or identity_count != 4
        or len(identity) != identity_count
    ):
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation identity artifact count mismatch"
        )
    seen_kinds: set[str] = set()
    for raw in identity:
        if not isinstance(raw, Mapping) or set(raw) != {
            "kind",
            "source_relative_path",
            "export_relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                "P2 held-out evaluation identity fields must match v1 exactly"
            )
        kind = _text(raw.get("kind"), label="P2 held-out evaluation identity kind", maximum=64)
        if kind in seen_kinds:
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                "P2 held-out evaluation identity kind repeated"
            )
        seen_kinds.add(kind)
        _relative_path(raw.get("source_relative_path"), label="P2 held-out identity source path")
        _relative_path(raw.get("export_relative_path"), label="P2 held-out identity export path")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                "P2 held-out evaluation identity size is invalid"
            )
        _sha(raw.get("sha256"), label="P2 held-out evaluation identity SHA-256")
    if seen_kinds != {"shape-param", "face-offset", "joint-offset", "locator-offset"}:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation identity kind universe mismatch"
        )

    motion = value.get("held_out_motion")
    if not isinstance(motion, Mapping):
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation motion is invalid"
        )
    expected_motion_fields = {
        "source_ref",
        "split",
        "role",
        "normalization_action",
        "selected_eye",
        "selected_viewport_id",
        "anchor_observation_ref",
        "anchor_frame_sha256",
        "window_start_seconds",
        "window_end_seconds",
        "window_duration_seconds",
        "motion_path_relative",
        "frame_count",
        "frame_ids",
        "artifacts",
    }
    if set(motion) != expected_motion_fields:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation motion fields must match v1 exactly"
        )
    source_ref = _text(motion.get("source_ref"), label="P2 held-out evaluation source ref", maximum=64)
    if motion.get("split") != "evaluation" or motion.get("role") != "held-out-motion-validation":
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation motion crossed EVALUATION-only authority"
        )
    if motion.get("motion_path_relative") != f"tasks/{source_ref}/motion":
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation motion path is not canonical"
        )
    frame_ids = motion.get("frame_ids")
    frame_count = motion.get("frame_count")
    if (
        not isinstance(frame_ids, list)
        or not frame_ids
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in frame_ids)
        or frame_ids != sorted(set(frame_ids))
        or isinstance(frame_count, bool)
        or not isinstance(frame_count, int)
        or frame_count != len(frame_ids)
    ):
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation frame universe is invalid"
        )
    artifacts = motion.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation artifact universe is empty"
        )
    seen_paths: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != {
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                "P2 held-out evaluation artifact fields must match v1 exactly"
            )
        relative = _relative_path(raw.get("relative_path"), label="P2 held-out evaluation artifact path")
        if relative in seen_paths or not relative.startswith(f"tasks/{source_ref}/motion/"):
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                "P2 held-out evaluation artifact universe mismatch"
            )
        seen_paths.add(relative)
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                "P2 held-out evaluation artifact size is invalid"
            )
        _sha(raw.get("sha256"), label="P2 held-out evaluation artifact SHA-256")
    required_paths: set[str] = set()
    for frame_id in frame_ids:
        required_paths.update(
            {
                f"tasks/{source_ref}/motion/frames/{frame_id}.png",
                f"tasks/{source_ref}/motion/cam_params/{frame_id}.json",
                f"tasks/{source_ref}/motion/smplx_optimized/smplx_params_smoothed/{frame_id}.json",
            }
        )
    if not required_paths.issubset(seen_paths):
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation input omits frame/camera/SMPL-X bytes"
        )

    if value.get("held_out_disclosure_purpose") != DISCLOSURE_PURPOSE:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 held-out evaluation disclosure purpose mismatch"
        )
    for field, expected_value in (
        ("frozen_teacher_checkpoint_bytes_reverified", True),
        ("identity_artifact_bytes_reverified", True),
        ("held_out_motion_artifact_bytes_reverified", True),
        ("train_animation_complete", True),
        ("train_animation_inference_only", True),
        ("held_out_evaluation_disclosed_to_animation", True),
        ("teacher_training_authorized", False),
        ("checkpoint_mutation_authorized", False),
        ("p2_heldout_animation_evaluation_authorized", True),
        ("human_animated_visual_acceptance_required", True),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected_value:
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                f"P2 held-out evaluation input authority mismatch: {field}"
            )

    claimed = _sha(
        value.get("p2_exavatar_heldout_evaluation_input_sha256"),
        label="P2 ExAvatar held-out evaluation input SHA-256",
    )
    if _digest(value, omit="p2_exavatar_heldout_evaluation_input_sha256") != claimed:
        raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
            "P2 ExAvatar held-out evaluation input digest mismatch"
        )
    return dict(value)


def build_heldout_evaluation_input_files(
    execution_input_path: str | Path,
    train_execution_receipt_path: str | Path,
    motion_preparation_receipt_path: str | Path,
    *,
    identity_root: str | Path,
    teacher_output_root: str | Path,
    motion_output_root: str | Path,
    heldout_source_ref: str,
    output_path: str | Path,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    result = build_heldout_evaluation_input(
        _read_json(execution_input_path, label="P2 ExAvatar execution input"),
        _read_json(train_execution_receipt_path, label="P2 TRAIN animation execution receipt"),
        _read_json(motion_preparation_receipt_path, label="P2 motion preparation receipt"),
        identity_root=identity_root,
        teacher_output_root=teacher_output_root,
        motion_output_root=motion_output_root,
        heldout_source_ref=heldout_source_ref,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        if not reuse_existing:
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                f"P2 ExAvatar held-out evaluation input already exists: {output}"
            )
        existing = _read_json(output, label="existing P2 held-out evaluation input")
        if existing != result:
            raise PhotorealP2ExAvatarHeldoutEvaluationInputError(
                f"existing P2 held-out evaluation input differs from canonical current state: {output}"
            )
        return result
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Authorize frozen-teacher ExAvatar inference on one HELD-OUT EVALUATION motion path."
    )
    parser.add_argument("--execution-input", type=Path, required=True)
    parser.add_argument("--train-execution-receipt", type=Path, required=True)
    parser.add_argument("--motion-preparation-receipt", type=Path, required=True)
    parser.add_argument("--identity-root", type=Path, required=True)
    parser.add_argument("--teacher-output-root", type=Path, required=True)
    parser.add_argument("--motion-output-root", type=Path, required=True)
    parser.add_argument("--heldout-source-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = build_heldout_evaluation_input_files(
            args.execution_input,
            args.train_execution_receipt,
            args.motion_preparation_receipt,
            identity_root=args.identity_root,
            teacher_output_root=args.teacher_output_root,
            motion_output_root=args.motion_output_root,
            heldout_source_ref=args.heldout_source_ref,
            output_path=args.out,
            reuse_existing=args.reuse_existing,
        )
    except PhotorealP2ExAvatarHeldoutEvaluationInputError as exc:
        print(f"BodyRig P2 ExAvatar held-out evaluation input: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "P2_EXAVATAR_HELDOUT_EVALUATION_INPUT_AUTHORIZED",
                "heldout_source_ref": result["held_out_motion"]["source_ref"],
                "heldout_frame_count": result["held_out_motion"]["frame_count"],
                "train_animation_complete": True,
                "train_animation_inference_only": True,
                "teacher_training_authorized": False,
                "checkpoint_mutation_authorized": False,
                "p2_heldout_animation_evaluation_authorized": True,
                "human_animated_visual_acceptance_required": True,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

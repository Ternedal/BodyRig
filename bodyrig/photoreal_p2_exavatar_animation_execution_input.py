from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p2_animation_plan import (
    ADAPTER as P2_ANIMATION_ADAPTER,
    PINNED_UPSTREAM_COMMIT,
    PhotorealP2AnimationPlanError,
    validate_p2_animation_plan,
)
from .photoreal_p2_exavatar_animation_identity import (
    PhotorealP2ExAvatarAnimationIdentityError,
    validate_exavatar_animation_identity,
)
from .photoreal_p2_motion_preparation_runner import (
    PhotorealP2MotionPreparationRunnerError,
    validate_motion_preparation_receipt,
)


FORMAT = "bodyrig-photoreal-p2-exavatar-animation-execution-input"
VERSION = 1
UPSTREAM_ANIMATION_SCRIPT = "avatar/main/animate.py"


class PhotorealP2ExAvatarAnimationExecutionInputError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            f"{label} must be a JSON object"
        )
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise PhotorealP2ExAvatarAnimationExecutionInputError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealP2ExAvatarAnimationExecutionInputError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            f"{label} format/version mismatch"
        )
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
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
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar animation execution input cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
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
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            f"{label} escapes its root"
        )
    return clean


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative_path(relative, label=label)
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            f"{label} escapes its root"
        ) from exc
    return clean, target


def _verify_motion_driver(
    task: Mapping[str, Any],
    *,
    motion_output_root: Path,
) -> dict[str, Any]:
    source_ref = _text(task.get("source_ref"), label="P2 animation motion driver source ref", maximum=64)
    if task.get("split") != "train" or task.get("role") != "motion-driver":
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar animation may consume only a TRAIN motion-driver task"
        )
    motion_path = _relative_path(
        task.get("motion_path_relative"),
        label="P2 animation motion path",
    )
    if motion_path != f"tasks/{source_ref}/motion":
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation motion path is not canonical"
        )

    artifacts = task.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation motion driver contains no artifacts"
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
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                "P2 animation motion artifact fields must match v1 exactly"
            )
        relative, path = _safe_child(
            motion_output_root,
            raw.get("relative_path"),
            label="P2 animation motion artifact path",
        )
        if relative in seen_paths or not relative.startswith(prefix):
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                "P2 animation motion artifact universe mismatch"
            )
        seen_paths.add(relative)
        size = raw.get("size_bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != size
        ):
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                f"P2 animation motion artifact size/path drifted: {relative}"
            )
        observed = _file_sha(path)
        expected = _sha(raw.get("sha256"), label="P2 animation motion artifact SHA-256")
        if observed != expected:
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                f"P2 animation motion artifact bytes drifted: {relative}"
            )

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

        normalized.append(
            {
                "relative_path": relative,
                "size_bytes": size,
                "sha256": observed,
            }
        )

    if not frame_ids or frame_ids != camera_ids or frame_ids != smplx_ids:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation motion driver frame/camera/SMPL-X ids are not aligned"
        )
    frame_count = task.get("frame_count")
    if (
        isinstance(frame_count, bool)
        or not isinstance(frame_count, int)
        or frame_count != len(frame_ids)
    ):
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation motion driver frame count mismatch"
        )

    return {
        "source_ref": source_ref,
        "split": "train",
        "role": "motion-driver",
        "normalization_action": _text(
            task.get("normalization_action"),
            label="P2 animation motion normalization action",
            maximum=128,
        ),
        "selected_eye": _text(
            task.get("selected_eye"),
            label="P2 animation motion selected eye",
            maximum=16,
        ),
        "selected_viewport_id": task.get("selected_viewport_id"),
        "anchor_observation_ref": _text(
            task.get("anchor_observation_ref"),
            label="P2 animation motion anchor observation ref",
            maximum=64,
        ),
        "anchor_frame_sha256": _sha(
            task.get("anchor_frame_sha256"),
            label="P2 animation motion anchor frame SHA-256",
        ),
        "window_start_seconds": task.get("window_start_seconds"),
        "window_end_seconds": task.get("window_end_seconds"),
        "window_duration_seconds": task.get("window_duration_seconds"),
        "motion_path_relative": motion_path,
        "frame_count": frame_count,
        "frame_ids": sorted(frame_ids),
        "artifacts": sorted(normalized, key=lambda item: item["relative_path"]),
    }


def build_exavatar_animation_execution_input(
    animation_plan: Mapping[str, Any],
    identity_receipt: Mapping[str, Any],
    motion_receipt: Mapping[str, Any],
    *,
    identity_output_root: str | Path,
    motion_output_root: str | Path,
    motion_driver_source_ref: str,
) -> dict[str, Any]:
    try:
        plan = validate_p2_animation_plan(animation_plan)
        identity = validate_exavatar_animation_identity(
            identity_receipt,
            output_root=identity_output_root,
        )
        motion = validate_motion_preparation_receipt(motion_receipt)
    except (
        PhotorealP2AnimationPlanError,
        PhotorealP2ExAvatarAnimationIdentityError,
        PhotorealP2MotionPreparationRunnerError,
    ) as exc:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            f"P2 ExAvatar animation input authority readback failed: {exc}"
        ) from exc

    for field in ("performer_id", "selected_epoch_id", "teacher_input_sha256"):
        if identity.get(field) != plan.get(field) or motion.get(field) != plan.get(field):
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                f"P2 ExAvatar animation input lineage mismatch: {field}"
            )
    if identity.get("p2_animation_plan_sha256") != plan.get("p2_animation_plan_sha256"):
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar identity belongs to a different animation plan"
        )
    if motion.get("p2_animation_plan_sha256") != plan.get("p2_animation_plan_sha256"):
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 motion preparation belongs to a different animation plan"
        )
    if identity.get("p2_animation_identity_input_ready") is not True:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar animation identity input is not ready"
        )
    if motion.get("p2_animation_execution_authorized") is not True:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 motion preparation does not authorize animation execution"
        )

    requested_ref = _text(
        motion_driver_source_ref,
        label="P2 animation selected motion driver source ref",
        maximum=64,
    )
    matches = [
        raw
        for raw in motion.get("task_results", [])
        if isinstance(raw, Mapping) and raw.get("source_ref") == requested_ref
    ]
    if len(matches) != 1:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "selected P2 animation motion driver is not unique in preparation receipt"
        )
    driver = _verify_motion_driver(
        matches[0],
        motion_output_root=Path(motion_output_root).expanduser().resolve(),
    )

    checkpoint = identity.get("teacher_checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar identity receipt lacks accepted checkpoint binding"
        )
    plan_checkpoint = plan.get("teacher_checkpoint")
    if not isinstance(plan_checkpoint, Mapping) or dict(checkpoint) != dict(plan_checkpoint):
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar identity checkpoint differs from animation plan"
        )

    identity_artifacts = identity.get("identity_artifacts")
    if not isinstance(identity_artifacts, list) or len(identity_artifacts) != 4:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar identity artifact universe is incomplete"
        )

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": plan["performer_id"],
        "selected_epoch_id": plan["selected_epoch_id"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "p2_animation_plan_sha256": plan["p2_animation_plan_sha256"],
        "p2_exavatar_animation_identity_sha256": identity[
            "p2_exavatar_animation_identity_sha256"
        ],
        "p2_motion_preparation_receipt_sha256": motion[
            "p2_motion_preparation_receipt_sha256"
        ],
        "exavatar_upstream_commit": PINNED_UPSTREAM_COMMIT,
        "exavatar_animation_adapter": P2_ANIMATION_ADAPTER,
        "exavatar_animation_script": UPSTREAM_ANIMATION_SCRIPT,
        "exavatar_subject_id": identity["exavatar_subject_id"],
        "teacher_checkpoint": dict(checkpoint),
        "identity_artifacts": [dict(item) for item in identity_artifacts],
        "identity_artifact_count": len(identity_artifacts),
        "motion_driver": driver,
        "identity_artifact_bytes_reverified": True,
        "motion_driver_artifact_bytes_reverified": True,
        "held_out_evaluation_disclosed_to_animation": False,
        "train_motion_driver_only": True,
        "animation_started": False,
        "p2_animation_execution_authorized": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p2_exavatar_animation_execution_input_sha256"] = _digest(
        result,
        omit="p2_exavatar_animation_execution_input_sha256",
    )
    return validate_exavatar_animation_execution_input(result)


def validate_exavatar_animation_execution_input(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_identity_sha256",
        "p2_motion_preparation_receipt_sha256",
        "exavatar_upstream_commit",
        "exavatar_animation_adapter",
        "exavatar_animation_script",
        "exavatar_subject_id",
        "teacher_checkpoint",
        "identity_artifacts",
        "identity_artifact_count",
        "motion_driver",
        "identity_artifact_bytes_reverified",
        "motion_driver_artifact_bytes_reverified",
        "held_out_evaluation_disclosed_to_animation",
        "train_motion_driver_only",
        "animation_started",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_exavatar_animation_execution_input_sha256",
    }
    if set(value) != expected_fields:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar animation execution input fields must match v1 exactly"
        )
    if value.get("format") != FORMAT:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar animation execution input format/version mismatch"
        )
    _strict_v1(value.get("version"), label="P2 ExAvatar animation execution input")
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_identity_sha256",
        "p2_motion_preparation_receipt_sha256",
    ):
        _sha(value.get(field), label=f"P2 ExAvatar animation execution input {field}")
    if value.get("exavatar_upstream_commit") != PINNED_UPSTREAM_COMMIT:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar animation execution input upstream commit mismatch"
        )
    if value.get("exavatar_animation_adapter") != P2_ANIMATION_ADAPTER:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar animation execution input adapter mismatch"
        )
    if value.get("exavatar_animation_script") != UPSTREAM_ANIMATION_SCRIPT:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar animation execution input script mismatch"
        )
    _text(value.get("performer_id"), label="P2 animation performer id", maximum=256)
    _text(value.get("selected_epoch_id"), label="P2 animation epoch id", maximum=256)
    _text(value.get("exavatar_subject_id"), label="P2 animation ExAvatar subject id", maximum=160)

    checkpoint = value.get("teacher_checkpoint")
    if not isinstance(checkpoint, Mapping) or set(checkpoint) != {
        "relative_path",
        "size_bytes",
        "sha256",
    }:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation checkpoint fields must match v1 exactly"
        )
    _relative_path(checkpoint.get("relative_path"), label="P2 animation checkpoint path")
    checkpoint_size = checkpoint.get("size_bytes")
    if isinstance(checkpoint_size, bool) or not isinstance(checkpoint_size, int) or checkpoint_size < 1:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation checkpoint size is invalid"
        )
    _sha(checkpoint.get("sha256"), label="P2 animation checkpoint SHA-256")

    identity_artifacts = value.get("identity_artifacts")
    identity_count = value.get("identity_artifact_count")
    if (
        not isinstance(identity_artifacts, list)
        or isinstance(identity_count, bool)
        or not isinstance(identity_count, int)
        or identity_count != 4
        or len(identity_artifacts) != identity_count
    ):
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation identity artifact count mismatch"
        )
    seen_kinds: set[str] = set()
    for raw in identity_artifacts:
        if not isinstance(raw, Mapping) or set(raw) != {
            "kind",
            "source_relative_path",
            "export_relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                "P2 animation identity artifact fields must match v1 exactly"
            )
        kind = _text(raw.get("kind"), label="P2 animation identity artifact kind", maximum=64)
        if kind in seen_kinds:
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                "P2 animation identity artifact kind is repeated"
            )
        seen_kinds.add(kind)
        _relative_path(raw.get("source_relative_path"), label="P2 animation identity source path")
        _relative_path(raw.get("export_relative_path"), label="P2 animation identity export path")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                "P2 animation identity artifact size is invalid"
            )
        _sha(raw.get("sha256"), label="P2 animation identity artifact SHA-256")

    driver = value.get("motion_driver")
    if not isinstance(driver, Mapping):
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation motion driver is invalid"
        )
    expected_driver_fields = {
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
    if set(driver) != expected_driver_fields:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation motion driver fields must match v1 exactly"
        )
    source_ref = _text(driver.get("source_ref"), label="P2 animation motion driver source ref", maximum=64)
    if driver.get("split") != "train" or driver.get("role") != "motion-driver":
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation motion driver crossed TRAIN-only authority"
        )
    if driver.get("motion_path_relative") != f"tasks/{source_ref}/motion":
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation motion path is not canonical"
        )
    frame_ids = driver.get("frame_ids")
    frame_count = driver.get("frame_count")
    if (
        not isinstance(frame_ids, list)
        or not frame_ids
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in frame_ids)
        or frame_ids != sorted(set(frame_ids))
        or isinstance(frame_count, bool)
        or not isinstance(frame_count, int)
        or frame_count != len(frame_ids)
    ):
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation motion frame universe is invalid"
        )
    artifacts = driver.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 animation motion artifact universe is empty"
        )
    seen_paths: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != {
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                "P2 animation motion artifact fields must match v1 exactly"
            )
        relative = _relative_path(raw.get("relative_path"), label="P2 animation motion artifact path")
        if relative in seen_paths or not relative.startswith(f"tasks/{source_ref}/motion/"):
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                "P2 animation motion artifact universe mismatch"
            )
        seen_paths.add(relative)
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                "P2 animation motion artifact size is invalid"
            )
        _sha(raw.get("sha256"), label="P2 animation motion artifact SHA-256")

    for field, expected in (
        ("identity_artifact_bytes_reverified", True),
        ("motion_driver_artifact_bytes_reverified", True),
        ("held_out_evaluation_disclosed_to_animation", False),
        ("train_motion_driver_only", True),
        ("animation_started", False),
        ("p2_animation_execution_authorized", True),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                f"P2 ExAvatar animation execution input authority mismatch: {field}"
            )

    claimed = _sha(
        value.get("p2_exavatar_animation_execution_input_sha256"),
        label="P2 ExAvatar animation execution input SHA-256",
    )
    if _digest(value, omit="p2_exavatar_animation_execution_input_sha256") != claimed:
        raise PhotorealP2ExAvatarAnimationExecutionInputError(
            "P2 ExAvatar animation execution input digest mismatch"
        )
    return dict(value)


def build_exavatar_animation_execution_input_files(
    animation_plan_path: str | Path,
    identity_receipt_path: str | Path,
    motion_receipt_path: str | Path,
    *,
    identity_output_root: str | Path,
    motion_output_root: str | Path,
    motion_driver_source_ref: str,
    output_path: str | Path,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    result = build_exavatar_animation_execution_input(
        _read_json(animation_plan_path, label="P2 animation plan"),
        _read_json(identity_receipt_path, label="P2 ExAvatar animation identity receipt"),
        _read_json(motion_receipt_path, label="P2 motion preparation receipt"),
        identity_output_root=identity_output_root,
        motion_output_root=motion_output_root,
        motion_driver_source_ref=motion_driver_source_ref,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        if not reuse_existing:
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                f"P2 ExAvatar animation execution input already exists: {output}"
            )
        existing = _read_json(output, label="existing P2 ExAvatar animation execution input")
        if existing != result:
            raise PhotorealP2ExAvatarAnimationExecutionInputError(
                f"existing P2 ExAvatar animation execution input differs from canonical current state: {output}"
            )
        return result
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bind accepted ExAvatar identity inputs to one core-verified TRAIN motion driver."
    )
    parser.add_argument("--animation-plan", type=Path, required=True)
    parser.add_argument("--identity-receipt", type=Path, required=True)
    parser.add_argument("--identity-root", type=Path, required=True)
    parser.add_argument("--motion-receipt", type=Path, required=True)
    parser.add_argument("--motion-output-root", type=Path, required=True)
    parser.add_argument("--motion-driver-source-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = build_exavatar_animation_execution_input_files(
            args.animation_plan,
            args.identity_receipt,
            args.motion_receipt,
            identity_output_root=args.identity_root,
            motion_output_root=args.motion_output_root,
            motion_driver_source_ref=args.motion_driver_source_ref,
            output_path=args.out,
            reuse_existing=args.reuse_existing,
        )
    except PhotorealP2ExAvatarAnimationExecutionInputError as exc:
        print(f"BodyRig P2 ExAvatar animation execution input: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "P2_EXAVATAR_ANIMATION_EXECUTION_INPUT_AUTHORIZED",
                "motion_driver_source_ref": result["motion_driver"]["source_ref"],
                "motion_frame_count": result["motion_driver"]["frame_count"],
                "held_out_evaluation_disclosed_to_animation": False,
                "animation_started": False,
                "p2_animation_execution_authorized": True,
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

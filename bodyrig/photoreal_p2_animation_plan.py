from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p1_likeness_review import (
    PhotorealP1LikenessReviewError,
    validate_likeness_review_receipt,
)
from .photoreal_teacher_authority import validate_external_teacher_files_strict
from .photoreal_teacher_runner import PhotorealTeacherRunnerError


FORMAT = "bodyrig-photoreal-p2-animation-plan"
VERSION = 1
ADAPTER = "bodyrig-exavatar-p2-animation-v1"
STATIC_TEACHER_ADAPTER = "bodyrig-exavatar-static-teacher-v1"
UPSTREAM_ANIMATION_SCRIPT = "avatar/main/animate.py"
EXPECTED_CHECKPOINT = "checkpoint/snapshot_4.pth"
EXPECTED_TEST_EPOCH = "4"

REQUIRED_SMPLX_FIELDS = (
    "root_pose",
    "body_pose",
    "jaw_pose",
    "leye_pose",
    "reye_pose",
    "lhand_pose",
    "rhand_pose",
    "expr",
    "trans",
)
REQUIRED_CAMERA_FIELDS = ("R", "t", "focal", "princpt")
REQUIRED_MOTION_VALIDATION_CRITERIA = (
    "head-turn",
    "eye-motion",
    "mouth-motion",
    "hands",
    "full-body-pose",
)


class PhotorealP2AnimationPlanError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2AnimationPlanError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealP2AnimationPlanError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP2AnimationPlanError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2AnimationPlanError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealP2AnimationPlanError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2AnimationPlanError(f"{label} format/version mismatch")
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2AnimationPlanError(f"{label} format/version mismatch")


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
        raise PhotorealP2AnimationPlanError("P2 animation plan cannot be canonically serialized") from exc
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: str | Path) -> str:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise PhotorealP2AnimationPlanError(f"required file is missing or not regular: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_artifact_path(root: Path, relative: str) -> Path:
    rel = Path(relative.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise PhotorealP2AnimationPlanError("teacher checkpoint path escapes output root")
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PhotorealP2AnimationPlanError("teacher checkpoint path escapes output root") from exc
    return path


def _checkpoint_binding(validated_teacher: Mapping[str, Any], teacher_output_root: Path) -> dict[str, Any]:
    artifacts = validated_teacher.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealP2AnimationPlanError("validated teacher contains no artifacts")
    checkpoints = [
        item for item in artifacts
        if isinstance(item, Mapping) and item.get("kind") == "checkpoint"
    ]
    if len(checkpoints) != 1:
        raise PhotorealP2AnimationPlanError("P2 requires exactly one accepted static-teacher checkpoint")
    checkpoint = checkpoints[0]
    relative = _text(checkpoint.get("relative_path"), label="teacher checkpoint path")
    if relative != EXPECTED_CHECKPOINT:
        raise PhotorealP2AnimationPlanError("P2 teacher checkpoint is not the canonical final ExAvatar epoch")
    claimed = _sha(checkpoint.get("sha256"), label="teacher checkpoint SHA-256")
    path = _safe_artifact_path(teacher_output_root, relative)
    actual = _sha256_file(path)
    if actual != claimed:
        raise PhotorealP2AnimationPlanError("teacher checkpoint bytes differ from validated manifest")
    size = checkpoint.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1 or path.stat().st_size != size:
        raise PhotorealP2AnimationPlanError("teacher checkpoint size differs from validated manifest")
    return {
        "relative_path": relative,
        "sha256": claimed,
        "size_bytes": size,
    }


def build_p2_animation_plan(
    validated_teacher: Mapping[str, Any],
    teacher_output_root: str | Path,
    p1_review_manifest: Mapping[str, Any],
    p1_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    output = Path(teacher_output_root).expanduser().resolve()
    if not output.is_dir() or output.is_symlink():
        raise PhotorealP2AnimationPlanError(f"teacher output root is missing/not regular: {output}")

    try:
        p1 = validate_likeness_review_receipt(
            p1_receipt,
            review_manifest=p1_review_manifest,
        )
    except PhotorealP1LikenessReviewError as exc:
        raise PhotorealP2AnimationPlanError(f"P1 likeness receipt is invalid: {exc}") from exc

    if p1.get("p1_static_teacher_status") != "pass":
        raise PhotorealP2AnimationPlanError("P2 animation requires an explicit all-PASS P1 static teacher")
    for field in (
        "p1_static_teacher_acceptance_authority",
        "human_visual_likeness_acceptance",
        "p2_animation_authorized",
    ):
        if p1.get(field) is not True:
            raise PhotorealP2AnimationPlanError(f"P1 receipt does not authorize P2 animation: {field}")
    if p1.get("photoreal_acceptance_authority") is not False or p1.get("production_activation") is not False:
        raise PhotorealP2AnimationPlanError("P1 receipt crossed downstream authority")

    if validated_teacher.get("training_complete") is not True:
        raise PhotorealP2AnimationPlanError("P2 requires a completed static teacher")
    if validated_teacher.get("adapter") != STATIC_TEACHER_ADAPTER:
        raise PhotorealP2AnimationPlanError("P2 canonical plan currently requires the ExAvatar static teacher")
    if validated_teacher.get("photoreal_acceptance_authority") is not False:
        raise PhotorealP2AnimationPlanError("static teacher unexpectedly owns photoreal acceptance authority")
    if validated_teacher.get("production_activation") is not False:
        raise PhotorealP2AnimationPlanError("static teacher crossed production authority")

    performer_id = _text(validated_teacher.get("performer_id"), label="teacher performer id", maximum=256)
    selected_epoch_id = _text(validated_teacher.get("selected_epoch_id"), label="teacher epoch id", maximum=256)
    teacher_input_sha = _sha(validated_teacher.get("teacher_input_sha256"), label="teacher input SHA-256")
    for field, expected in (
        ("performer_id", performer_id),
        ("selected_epoch_id", selected_epoch_id),
        ("teacher_input_sha256", teacher_input_sha),
    ):
        if p1.get(field) != expected:
            raise PhotorealP2AnimationPlanError(f"P1/static-teacher provenance mismatch: {field}")

    upstream_repository = _text(
        validated_teacher.get("upstream_repository"),
        label="teacher upstream repository",
    )
    upstream_commit = _text(
        validated_teacher.get("upstream_commit"),
        label="teacher upstream commit",
        maximum=64,
    )
    adapter_revision = _text(
        validated_teacher.get("adapter_revision"),
        label="teacher adapter revision",
        maximum=128,
    )
    checkpoint = _checkpoint_binding(validated_teacher, output)
    teacher_manifest_sha = _sha256_file(output / "teacher-manifest.json")

    plan: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "selected_epoch_id": selected_epoch_id,
        "teacher_input_sha256": teacher_input_sha,
        "teacher_manifest_file_sha256": teacher_manifest_sha,
        "teacher_adapter": STATIC_TEACHER_ADAPTER,
        "teacher_adapter_revision": adapter_revision,
        "teacher_upstream_repository": upstream_repository,
        "teacher_upstream_commit": upstream_commit,
        "teacher_checkpoint": checkpoint,
        "p1_likeness_review_manifest_sha256": _sha(
            p1_review_manifest.get("p1_likeness_review_manifest_sha256"),
            label="P1 likeness review manifest SHA-256",
        ),
        "p1_likeness_review_sha256": _sha(
            p1.get("p1_likeness_review_sha256"),
            label="P1 likeness review SHA-256",
        ),
        "animation_adapter": ADAPTER,
        "animation_contract": {
            "upstream_repository": upstream_repository,
            "upstream_commit": upstream_commit,
            "upstream_script": UPSTREAM_ANIMATION_SCRIPT,
            "test_epoch": EXPECTED_TEST_EPOCH,
            "motion_path_layout": {
                "reference_frames": "frames/<frame>.png",
                "camera_parameters": "cam_params/<frame>.json",
                "smplx_parameters": "smplx_optimized/smplx_params_smoothed/<frame>.json",
            },
            "required_smplx_fields": list(REQUIRED_SMPLX_FIELDS),
            "required_camera_fields": list(REQUIRED_CAMERA_FIELDS),
            "frame_id_contract": "integer filename stem shared across frames/camera/SMPL-X parameter files",
            "identity_shape_source": "accepted-static-teacher",
            "visual_identity_authority": "accepted-static-teacher",
            "rig_role": "motion-and-correspondence-only",
        },
        "required_motion_validation_criteria": list(REQUIRED_MOTION_VALIDATION_CRITERIA),
        "source_motion_evidence_required": True,
        "held_out_motion_validation_required": True,
        "human_motion_acceptance_required": True,
        "p1_static_teacher_acceptance_authority": True,
        "p2_animation_build_authorized": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    plan["p2_animation_plan_sha256"] = _digest(plan, omit="p2_animation_plan_sha256")
    return plan


def build_p2_animation_plan_files(
    config_path: str | Path,
    teacher_input_path: str | Path,
    teacher_workspace: str | Path,
    p1_review_root: str | Path,
    p1_receipt_path: str | Path,
    output_path: str | Path,
    *,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    workspace = Path(teacher_workspace).expanduser().resolve()
    try:
        validated_teacher = validate_external_teacher_files_strict(
            config_path,
            teacher_input_path,
            workspace,
        )
    except PhotorealTeacherRunnerError as exc:
        raise PhotorealP2AnimationPlanError(f"strict static-teacher readback failed: {exc}") from exc

    review_root = Path(p1_review_root).expanduser().resolve()
    manifest = _read_json(
        review_root / "p1-likeness-review-manifest.json",
        label="P1 likeness review manifest",
    )
    receipt = _read_json(p1_receipt_path, label="P1 likeness review receipt")
    plan = build_p2_animation_plan(
        validated_teacher,
        workspace / "output",
        manifest,
        receipt,
    )

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        if not reuse_existing:
            raise PhotorealP2AnimationPlanError(f"P2 animation plan already exists: {output}")
        existing = _read_json(output, label="existing P2 animation plan")
        if existing != plan:
            raise PhotorealP2AnimationPlanError(
                f"existing P2 animation plan differs from canonical current state: {output}"
            )
        return plan

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(plan, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except OSError as exc:
        raise PhotorealP2AnimationPlanError(f"failed to persist P2 animation plan: {output}") from exc
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Authorize the exact P2 ExAvatar animation build contract from an accepted P1 teacher."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--teacher-input", type=Path, required=True)
    parser.add_argument("--teacher-workspace", type=Path, required=True)
    parser.add_argument("--p1-review-root", type=Path, required=True)
    parser.add_argument("--p1-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = build_p2_animation_plan_files(
            args.config,
            args.teacher_input,
            args.teacher_workspace,
            args.p1_review_root,
            args.p1_receipt,
            args.out,
            reuse_existing=args.reuse_existing,
        )
    except PhotorealP2AnimationPlanError as exc:
        print(f"BodyRig P2 animation plan: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P2_ANIMATION_BUILD_AUTHORIZED",
                "animation_adapter": result["animation_adapter"],
                "upstream_script": result["animation_contract"]["upstream_script"],
                "p2_animation_build_authorized": result["p2_animation_build_authorized"],
                "p2_animated_teacher_acceptance_authority": result[
                    "p2_animated_teacher_acceptance_authority"
                ],
                "quest_distillation_authorized": result["quest_distillation_authorized"],
                "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
                "production_activation": result["production_activation"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

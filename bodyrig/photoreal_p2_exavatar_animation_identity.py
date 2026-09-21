from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p2_animation_plan import (
    PINNED_UPSTREAM_COMMIT,
    PhotorealP2AnimationPlanError,
    validate_p2_animation_plan,
)


FORMAT = "bodyrig-photoreal-p2-exavatar-animation-identity"
VERSION = 1
WORKSPACE_FORMAT = "bodyrig-photoreal-exavatar-workspace"
PREPROCESS_FORMAT = "bodyrig-photoreal-exavatar-preprocess-state"

IDENTITY_FILES = (
    ("shape-param", "smplx_optimized/shape_param.json", "identity/shape_param.json"),
    ("face-offset", "smplx_optimized/face_offset.json", "identity/face_offset.json"),
    ("joint-offset", "smplx_optimized/joint_offset.json", "identity/joint_offset.json"),
    ("locator-offset", "smplx_optimized/locator_offset.json", "identity/locator_offset.json"),
)


class PhotorealP2ExAvatarAnimationIdentityError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP2ExAvatarAnimationIdentityError(
            f"{label} must be a JSON object"
        )
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise PhotorealP2ExAvatarAnimationIdentityError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2ExAvatarAnimationIdentityError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealP2ExAvatarAnimationIdentityError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2ExAvatarAnimationIdentityError(
            f"{label} format/version mismatch"
        )
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            f"{label} format/version mismatch"
        )


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
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "P2 ExAvatar animation identity authority cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP2ExAvatarAnimationIdentityError(
            f"required file is missing/not regular: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: Any, *, label: str) -> str:
    raw = _text(value, label=label).replace("\\", "/")
    relative = Path(raw)
    first = raw.split("/", 1)[0]
    if relative.is_absolute() or raw.startswith("../") or "/../" in f"/{raw}/" or ":" in first:
        raise PhotorealP2ExAvatarAnimationIdentityError(f"{label} escapes its root")
    return relative.as_posix()


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _safe_relative(relative, label=label)
    target = (root / clean).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            f"{label} escapes its root"
        ) from exc
    return clean, target


def _validate_workspace(
    root: Path,
    *,
    plan: Mapping[str, Any],
) -> tuple[dict[str, Any], Path]:
    receipt = _read_json(root / "workspace-receipt.json", label="ExAvatar workspace receipt")
    if receipt.get("format") != WORKSPACE_FORMAT:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar workspace format/version mismatch"
        )
    _strict_v1(receipt.get("version"), label="ExAvatar workspace")

    for field in ("performer_id", "selected_epoch_id", "teacher_input_sha256"):
        if receipt.get(field) != plan.get(field):
            raise PhotorealP2ExAvatarAnimationIdentityError(
                f"ExAvatar workspace/P2 plan lineage mismatch: {field}"
            )
    if receipt.get("upstream_commit") != PINNED_UPSTREAM_COMMIT:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar workspace upstream commit mismatch"
        )
    for field, expected in (
        ("smplx_gender_explicit", True),
        ("upstream_default_gender_accepted", False),
        ("held_out_evaluation_disclosed", False),
        ("original_video_copied", False),
        ("dependency_root_modified", False),
        ("photoreal_acceptance_authority", False),
        ("human_visual_acceptance_required", True),
        ("build_only", True),
        ("runtime_dependency", False),
        ("production_activation", False),
    ):
        if receipt.get(field) is not expected:
            raise PhotorealP2ExAvatarAnimationIdentityError(
                f"ExAvatar workspace authority mismatch: {field}"
            )

    claimed = _sha(receipt.get("workspace_sha256"), label="ExAvatar workspace SHA-256")
    if _digest(receipt, omit="workspace_sha256") != claimed:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar workspace digest mismatch"
        )

    relative = _safe_relative(
        receipt.get("working_dataset_relative_path"),
        label="ExAvatar working dataset path",
    )
    dataset = (root / relative).resolve()
    try:
        dataset.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar working dataset escapes workspace"
        ) from exc
    if not dataset.is_dir() or dataset.is_symlink():
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar working dataset is missing/not regular"
        )
    if (dataset / "video.mp4").exists():
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar working dataset unexpectedly contains original video"
        )
    return receipt, dataset


def _validate_preprocess(
    root: Path,
    *,
    workspace: Mapping[str, Any],
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    state = _read_json(root / "preprocess-state.json", label="ExAvatar preprocess state")
    if state.get("format") != PREPROCESS_FORMAT:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar preprocess state format/version mismatch"
        )
    _strict_v1(state.get("version"), label="ExAvatar preprocess state")
    if state.get("workspace_sha256") != workspace.get("workspace_sha256"):
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar preprocess state belongs to different workspace"
        )
    for field, expected in (
        ("preprocessing_complete", True),
        ("teacher_training_authorized_by_preprocessing", False),
        ("photoreal_acceptance_authority", False),
        ("human_visual_acceptance_required", True),
        ("production_activation", False),
    ):
        if state.get(field) is not expected:
            raise PhotorealP2ExAvatarAnimationIdentityError(
                f"ExAvatar preprocess state authority mismatch: {field}"
            )
    claimed = _sha(
        state.get("preprocess_state_sha256"),
        label="ExAvatar preprocess state SHA-256",
    )
    if _digest(state, omit="preprocess_state_sha256") != claimed:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar preprocess state digest mismatch"
        )

    stages = state.get("completed_stages")
    if not isinstance(stages, list) or not stages:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar preprocess completed stage list is invalid"
        )
    matches = [
        item for item in stages
        if isinstance(item, Mapping) and item.get("name") == "smplx-fit"
    ]
    if len(matches) != 1:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar preprocess state must contain exactly one SMPL-X fit stage"
        )
    fit_stage = matches[0]
    outputs = fit_stage.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar SMPL-X fit stage has no output provenance"
        )
    return state, fit_stage


def _fit_output_record(
    fit_stage: Mapping[str, Any],
    *,
    expected_path: Path,
) -> Mapping[str, Any]:
    outputs = fit_stage.get("outputs")
    if not isinstance(outputs, list):
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "ExAvatar SMPL-X fit output provenance is invalid"
        )
    expected = expected_path.resolve().as_posix()
    matches: list[Mapping[str, Any]] = []
    for raw in outputs:
        if not isinstance(raw, Mapping):
            continue
        path_value = raw.get("path")
        if not isinstance(path_value, str):
            continue
        normalized = path_value.replace("\\", "/")
        if normalized == expected:
            matches.append(raw)
    if len(matches) != 1:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            f"identity source is not uniquely bound by SMPL-X fit provenance: {expected_path.name}"
        )
    return matches[0]


def _verify_checkpoint(
    plan: Mapping[str, Any],
    *,
    teacher_output_root: Path,
) -> dict[str, Any]:
    checkpoint = plan.get("teacher_checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "P2 animation plan checkpoint binding is invalid"
        )
    relative, path = _safe_child(
        teacher_output_root,
        checkpoint.get("relative_path"),
        label="accepted teacher checkpoint path",
    )
    size = checkpoint.get("size_bytes")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
        or not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != size
    ):
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "accepted teacher checkpoint size/path drifted"
        )
    observed = _file_sha(path)
    expected = _sha(
        checkpoint.get("sha256"),
        label="accepted teacher checkpoint SHA-256",
    )
    if observed != expected:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "accepted teacher checkpoint bytes drifted"
        )
    return {
        "relative_path": relative,
        "size_bytes": size,
        "sha256": observed,
    }


def _identity_artifacts(
    dataset: Path,
    fit_stage: Mapping[str, Any],
    *,
    output_root: Path,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for kind, source_relative, exported_relative in IDENTITY_FILES:
        _, source = _safe_child(
            dataset,
            source_relative,
            label=f"{kind} identity source path",
        )
        record = _fit_output_record(fit_stage, expected_path=source)
        size = record.get("size_bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or not source.is_file()
            or source.is_symlink()
            or source.stat().st_size != size
        ):
            raise PhotorealP2ExAvatarAnimationIdentityError(
                f"{kind} identity source size/path drifted"
            )
        expected_sha = _sha(record.get("sha256"), label=f"{kind} preprocess SHA-256")
        observed_sha = _file_sha(source)
        if observed_sha != expected_sha:
            raise PhotorealP2ExAvatarAnimationIdentityError(
                f"{kind} identity source bytes drifted since preprocessing"
            )

        _, target = _safe_child(
            output_root,
            exported_relative,
            label=f"{kind} identity export path",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise PhotorealP2ExAvatarAnimationIdentityError(
                f"{kind} identity export destination already exists"
            )
        shutil.copy2(source, target)
        copied_sha = _file_sha(target)
        if copied_sha != observed_sha or target.stat().st_size != size:
            raise PhotorealP2ExAvatarAnimationIdentityError(
                f"{kind} identity export bytes changed during copy"
            )
        result.append(
            {
                "kind": kind,
                "source_relative_path": source_relative,
                "export_relative_path": exported_relative,
                "size_bytes": size,
                "sha256": copied_sha,
            }
        )
    return result


def build_exavatar_animation_identity(
    animation_plan: Mapping[str, Any],
    *,
    exavatar_workspace_root: str | Path,
    teacher_output_root: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    try:
        plan = validate_p2_animation_plan(animation_plan)
    except PhotorealP2AnimationPlanError as exc:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            f"P2 animation plan strict readback failed: {exc}"
        ) from exc

    workspace_root = Path(exavatar_workspace_root).expanduser().resolve()
    teacher_root = Path(teacher_output_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    if not workspace_root.is_dir() or workspace_root.is_symlink():
        raise PhotorealP2ExAvatarAnimationIdentityError(
            f"ExAvatar workspace root is missing/not regular: {workspace_root}"
        )
    if not teacher_root.is_dir() or teacher_root.is_symlink():
        raise PhotorealP2ExAvatarAnimationIdentityError(
            f"teacher output root is missing/not regular: {teacher_root}"
        )
    if output.exists() or output.is_symlink():
        raise PhotorealP2ExAvatarAnimationIdentityError(
            f"P2 ExAvatar animation identity output already exists: {output}"
        )
    output.mkdir(parents=True)

    try:
        workspace, dataset = _validate_workspace(workspace_root, plan=plan)
        preprocess, fit_stage = _validate_preprocess(
            workspace_root,
            workspace=workspace,
        )
        checkpoint = _verify_checkpoint(plan, teacher_output_root=teacher_root)
        identity = _identity_artifacts(
            dataset,
            fit_stage,
            output_root=output,
        )

        receipt: dict[str, Any] = {
            "format": FORMAT,
            "version": VERSION,
            "performer_id": _text(plan.get("performer_id"), label="P2 performer id", maximum=256),
            "selected_epoch_id": _text(plan.get("selected_epoch_id"), label="P2 selected epoch id", maximum=256),
            "teacher_input_sha256": _sha(
                plan.get("teacher_input_sha256"),
                label="teacher input SHA-256",
            ),
            "p2_animation_plan_sha256": _sha(
                plan.get("p2_animation_plan_sha256"),
                label="P2 animation plan SHA-256",
            ),
            "teacher_checkpoint": checkpoint,
            "exavatar_workspace_sha256": _sha(
                workspace.get("workspace_sha256"),
                label="ExAvatar workspace SHA-256",
            ),
            "exavatar_preprocess_state_sha256": _sha(
                preprocess.get("preprocess_state_sha256"),
                label="ExAvatar preprocess state SHA-256",
            ),
            "exavatar_upstream_commit": PINNED_UPSTREAM_COMMIT,
            "exavatar_subject_id": _text(
                workspace.get("subject_id"),
                label="ExAvatar subject id",
                maximum=160,
            ),
            "identity_artifacts": identity,
            "identity_artifact_count": len(identity),
            "teacher_checkpoint_bytes_reverified": True,
            "identity_bytes_reverified_against_preprocess_state": True,
            "source_media_rehash_performed": False,
            "p2_animation_identity_input_ready": True,
            "p2_animation_execution_authorized": False,
            "p2_animated_teacher_acceptance_authority": False,
            "quest_distillation_authorized": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }
        receipt["p2_exavatar_animation_identity_sha256"] = _digest(
            receipt,
            omit="p2_exavatar_animation_identity_sha256",
        )
        receipt = validate_exavatar_animation_identity(receipt, output_root=output)
        receipt_path = output / "p2-exavatar-animation-identity.json"
        receipt_path.write_text(
            json.dumps(
                receipt,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return receipt
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def validate_exavatar_animation_identity(
    receipt: Mapping[str, Any],
    *,
    output_root: str | Path,
) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "teacher_checkpoint",
        "exavatar_workspace_sha256",
        "exavatar_preprocess_state_sha256",
        "exavatar_upstream_commit",
        "exavatar_subject_id",
        "identity_artifacts",
        "identity_artifact_count",
        "teacher_checkpoint_bytes_reverified",
        "identity_bytes_reverified_against_preprocess_state",
        "source_media_rehash_performed",
        "p2_animation_identity_input_ready",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_exavatar_animation_identity_sha256",
    }
    if set(receipt) != expected_fields:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "P2 ExAvatar animation identity fields must match v1 exactly"
        )
    if receipt.get("format") != FORMAT:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "P2 ExAvatar animation identity format/version mismatch"
        )
    _strict_v1(receipt.get("version"), label="P2 ExAvatar animation identity")
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "exavatar_workspace_sha256",
        "exavatar_preprocess_state_sha256",
    ):
        _sha(receipt.get(field), label=f"P2 ExAvatar animation identity {field}")
    if receipt.get("exavatar_upstream_commit") != PINNED_UPSTREAM_COMMIT:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "P2 ExAvatar animation identity upstream mismatch"
        )
    _text(receipt.get("performer_id"), label="P2 performer id", maximum=256)
    _text(receipt.get("selected_epoch_id"), label="P2 selected epoch id", maximum=256)
    _text(receipt.get("exavatar_subject_id"), label="ExAvatar subject id", maximum=160)

    checkpoint = receipt.get("teacher_checkpoint")
    if not isinstance(checkpoint, Mapping) or set(checkpoint) != {
        "relative_path",
        "size_bytes",
        "sha256",
    }:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "P2 ExAvatar animation identity checkpoint fields must match v1 exactly"
        )
    _safe_relative(
        checkpoint.get("relative_path"),
        label="accepted teacher checkpoint path",
    )
    checkpoint_size = checkpoint.get("size_bytes")
    if (
        isinstance(checkpoint_size, bool)
        or not isinstance(checkpoint_size, int)
        or checkpoint_size < 1
    ):
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "accepted teacher checkpoint size is invalid"
        )
    _sha(checkpoint.get("sha256"), label="accepted teacher checkpoint SHA-256")

    values = receipt.get("identity_artifacts")
    count = receipt.get("identity_artifact_count")
    if (
        not isinstance(values, list)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(IDENTITY_FILES)
        or len(values) != count
    ):
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "P2 ExAvatar animation identity artifact count mismatch"
        )

    expected_by_kind = {
        kind: (source_relative, exported_relative)
        for kind, source_relative, exported_relative in IDENTITY_FILES
    }
    root = Path(output_root).expanduser().resolve()
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in values:
        if not isinstance(raw, Mapping) or set(raw) != {
            "kind",
            "source_relative_path",
            "export_relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PhotorealP2ExAvatarAnimationIdentityError(
                "P2 ExAvatar animation identity artifact fields must match v1 exactly"
            )
        kind = _text(raw.get("kind"), label="identity artifact kind", maximum=64)
        if kind in seen or kind not in expected_by_kind:
            raise PhotorealP2ExAvatarAnimationIdentityError(
                "P2 ExAvatar animation identity artifact universe mismatch"
            )
        seen.add(kind)
        expected_source, expected_export = expected_by_kind[kind]
        if raw.get("source_relative_path") != expected_source:
            raise PhotorealP2ExAvatarAnimationIdentityError(
                "P2 ExAvatar animation identity source path mismatch"
            )
        exported, path = _safe_child(
            root,
            raw.get("export_relative_path"),
            label="identity artifact export path",
        )
        if exported != expected_export:
            raise PhotorealP2ExAvatarAnimationIdentityError(
                "P2 ExAvatar animation identity export path mismatch"
            )
        size = raw.get("size_bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != size
        ):
            raise PhotorealP2ExAvatarAnimationIdentityError(
                "P2 ExAvatar animation identity exported artifact size/path mismatch"
            )
        observed = _file_sha(path)
        if observed != _sha(raw.get("sha256"), label="identity artifact SHA-256"):
            raise PhotorealP2ExAvatarAnimationIdentityError(
                "P2 ExAvatar animation identity exported artifact bytes drifted"
            )
        normalized.append(
            {
                "kind": kind,
                "source_relative_path": expected_source,
                "export_relative_path": exported,
                "size_bytes": size,
                "sha256": observed,
            }
        )
    if seen != set(expected_by_kind):
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "P2 ExAvatar animation identity artifact universe mismatch"
        )

    expected_files = {item[1] for item in expected_by_kind.values()}
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    allowed_file_sets = (
        expected_files,
        expected_files | {"p2-exavatar-animation-identity.json"},
    )
    if actual_files not in allowed_file_sets:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "P2 ExAvatar animation identity output file universe mismatch"
        )

    for field, expected in (
        ("teacher_checkpoint_bytes_reverified", True),
        ("identity_bytes_reverified_against_preprocess_state", True),
        ("source_media_rehash_performed", False),
        ("p2_animation_identity_input_ready", True),
        ("p2_animation_execution_authorized", False),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if receipt.get(field) is not expected:
            raise PhotorealP2ExAvatarAnimationIdentityError(
                f"P2 ExAvatar animation identity authority mismatch: {field}"
            )

    claimed = _sha(
        receipt.get("p2_exavatar_animation_identity_sha256"),
        label="P2 ExAvatar animation identity SHA-256",
    )
    if _digest(receipt, omit="p2_exavatar_animation_identity_sha256") != claimed:
        raise PhotorealP2ExAvatarAnimationIdentityError(
            "P2 ExAvatar animation identity digest mismatch"
        )
    result = dict(receipt)
    result["identity_artifacts"] = sorted(normalized, key=lambda item: item["kind"])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export the exact ExAvatar identity geometry paired with the accepted P2 teacher checkpoint."
    )
    parser.add_argument("--animation-plan", type=Path, required=True)
    parser.add_argument("--exavatar-workspace-root", type=Path, required=True)
    parser.add_argument("--teacher-output-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan = _read_json(args.animation_plan, label="P2 animation plan")
        receipt = build_exavatar_animation_identity(
            plan,
            exavatar_workspace_root=args.exavatar_workspace_root,
            teacher_output_root=args.teacher_output_root,
            output_root=args.out,
        )
    except PhotorealP2ExAvatarAnimationIdentityError as exc:
        print(f"BodyRig P2 ExAvatar animation identity: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P2_EXAVATAR_ANIMATION_IDENTITY_READY",
                "identity_artifact_count": receipt["identity_artifact_count"],
                "teacher_checkpoint_bytes_reverified": True,
                "identity_bytes_reverified_against_preprocess_state": True,
                "source_media_rehash_performed": False,
                "p2_animation_execution_authorized": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

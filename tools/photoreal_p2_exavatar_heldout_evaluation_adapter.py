from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from tools.photoreal_p2_exavatar_animation_adapter import (
    PINNED_TEST_EPOCH,
    PINNED_UPSTREAM_COMMIT,
    VERSION,
    ExAvatarP2AnimationAdapterError,
    _digest,
    _file_sha,
    _prepare_stage,
    _run_animation,
    _sha,
    _strict_v1,
    _text,
    _validate_preprocess,
    _validate_runtime_preflight,
    _validate_workspace,
)


REQUEST_FORMAT = "bodyrig-photoreal-p2-exavatar-heldout-evaluation-request"
MANIFEST_FORMAT = "bodyrig-photoreal-p2-exavatar-heldout-evaluation-manifest"
DISCLOSURE_PURPOSE = "post-training-inference-only-evaluation"


class ExAvatarP2HeldoutEvaluationAdapterError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            f"{label} is unreadable: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            f"{label} must be a JSON object"
        )
    return value


def _translate_error(exc: Exception) -> ExAvatarP2HeldoutEvaluationAdapterError:
    return ExAvatarP2HeldoutEvaluationAdapterError(str(exc))


def _validate_request(
    request: Mapping[str, Any],
    *,
    workspace_root: Path,
    runtime_preflight_path: Path,
) -> None:
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
        "exavatar_workspace_sha256",
        "exavatar_preprocess_state_sha256",
        "exavatar_upstream_repository",
        "exavatar_upstream_commit",
        "exavatar_subject_id",
        "test_epoch",
        "adapter_revision",
        "bodyrig_linux_repo_root",
        "adapter_linux_path",
        "teacher_checkpoint",
        "identity_artifacts",
        "held_out_motion",
        "evaluation_mode",
        "held_out_disclosure_purpose",
        "teacher_training_authorized",
        "checkpoint_mutation_authorized",
        "source_media_rehash_performed",
        "held_out_evaluation_disclosed",
        "human_animated_visual_acceptance_required",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_exavatar_heldout_evaluation_request_sha256",
    }
    if set(request) != expected:
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            "P2 held-out evaluation request fields must match v1 exactly"
        )
    if request.get("format") != REQUEST_FORMAT:
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            "P2 held-out evaluation request format/version mismatch"
        )
    try:
        _strict_v1(
            request.get("version"),
            label="P2 held-out evaluation request",
        )
        for field in (
            "teacher_input_sha256",
            "p2_animation_plan_sha256",
            "p2_exavatar_animation_execution_input_sha256",
            "train_animation_execution_receipt_sha256",
            "p2_exavatar_heldout_evaluation_input_sha256",
            "exavatar_workspace_sha256",
            "exavatar_preprocess_state_sha256",
            "adapter_revision",
        ):
            _sha(
                request.get(field),
                label=f"P2 held-out evaluation request {field}",
            )
        declared = _sha(
            request.get("p2_exavatar_heldout_evaluation_request_sha256"),
            label="P2 held-out evaluation request SHA-256",
        )
    except ExAvatarP2AnimationAdapterError as exc:
        raise _translate_error(exc) from exc
    if _digest(
        request,
        omit="p2_exavatar_heldout_evaluation_request_sha256",
    ) != declared:
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            "P2 held-out evaluation request digest mismatch"
        )
    if request.get("exavatar_upstream_repository") != "https://github.com/mks0601/ExAvatar_RELEASE":
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            "P2 held-out evaluation repository mismatch"
        )
    if request.get("exavatar_upstream_commit") != PINNED_UPSTREAM_COMMIT:
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            "P2 held-out evaluation upstream commit mismatch"
        )
    if request.get("test_epoch") != PINNED_TEST_EPOCH:
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            "P2 held-out evaluation epoch mismatch"
        )
    try:
        if _file_sha(Path(__file__).resolve()) != _sha(
            request.get("adapter_revision"),
            label="P2 held-out evaluation adapter revision",
        ):
            raise ExAvatarP2HeldoutEvaluationAdapterError(
                "P2 held-out evaluation adapter bytes differ from core request"
            )
    except ExAvatarP2AnimationAdapterError as exc:
        raise _translate_error(exc) from exc

    if request.get("evaluation_mode") != "inference-only-held-out":
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            "P2 held-out evaluation request is not inference-only evaluation"
        )
    if request.get("held_out_disclosure_purpose") != DISCLOSURE_PURPOSE:
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            "P2 held-out evaluation disclosure purpose mismatch"
        )
    for field, expected_value in (
        ("teacher_training_authorized", False),
        ("checkpoint_mutation_authorized", False),
        ("source_media_rehash_performed", False),
        ("held_out_evaluation_disclosed", True),
        ("human_animated_visual_acceptance_required", True),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if request.get(field) is not expected_value:
            raise ExAvatarP2HeldoutEvaluationAdapterError(
                f"P2 held-out evaluation request authority mismatch: {field}"
            )
    motion = request.get("held_out_motion")
    if (
        not isinstance(motion, Mapping)
        or motion.get("split") != "evaluation"
        or motion.get("role") != "held-out-motion-validation"
    ):
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            "P2 held-out evaluation request is not EVALUATION-motion-only"
        )

    try:
        workspace = _validate_workspace(workspace_root, request)
        preprocess = _validate_preprocess(workspace_root, request)
        _validate_runtime_preflight(
            runtime_preflight_path,
            _sha(
                request.get("exavatar_workspace_sha256"),
                label="held-out request workspace SHA-256",
            ),
        )
    except ExAvatarP2AnimationAdapterError as exc:
        raise _translate_error(exc) from exc
    if workspace.get("workspace_sha256") != request.get("exavatar_workspace_sha256"):
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            "P2 held-out evaluation workspace mismatch"
        )
    if preprocess.get("preprocess_state_sha256") != request.get(
        "exavatar_preprocess_state_sha256"
    ):
        raise ExAvatarP2HeldoutEvaluationAdapterError(
            "P2 held-out evaluation preprocess state mismatch"
        )


def _prepare_evaluation_stage(
    stage: Path,
    request: Mapping[str, Any],
    *,
    workspace_root: Path,
) -> tuple[Path, Path, list[dict[str, str]], list[dict[str, str]]]:
    staging_request = dict(request)
    staging_request["motion_driver"] = request["held_out_motion"]
    try:
        return _prepare_stage(
            stage,
            staging_request,
            workspace_root=workspace_root,
        )
    except ExAvatarP2AnimationAdapterError as exc:
        raise _translate_error(exc) from exc


def _run_evaluation(
    main_dir: Path,
    motion_dir: Path,
    request: Mapping[str, Any],
    log_path: Path,
) -> Path:
    try:
        return _run_animation(
            main_dir,
            motion_dir,
            request,
            log_path,
        )
    except ExAvatarP2AnimationAdapterError as exc:
        raise _translate_error(exc) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pinned frozen-teacher ExAvatar HELD-OUT evaluation adapter."
    )
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--runtime-preflight", type=Path, required=True)
    parser.add_argument("--bodyrig-request", type=Path, required=True)
    parser.add_argument("--bodyrig-output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        request = _read_json(
            args.bodyrig_request.expanduser().resolve(),
            label="P2 held-out evaluation request",
        )
        workspace = args.workspace_root.expanduser().resolve()
        preflight = args.runtime_preflight.expanduser().resolve()
        output = args.bodyrig_output.expanduser().resolve()
        if not workspace.is_dir() or workspace.is_symlink():
            raise ExAvatarP2HeldoutEvaluationAdapterError(
                f"accepted ExAvatar workspace missing/not regular: {workspace}"
            )
        if not preflight.is_file() or preflight.is_symlink():
            raise ExAvatarP2HeldoutEvaluationAdapterError(
                f"ExAvatar runtime preflight missing/not regular: {preflight}"
            )
        if not output.is_dir() or output.is_symlink() or any(output.iterdir()):
            raise ExAvatarP2HeldoutEvaluationAdapterError(
                "P2 held-out evaluation output directory must exist and be empty"
            )
        _validate_request(
            request,
            workspace_root=workspace,
            runtime_preflight_path=preflight,
        )

        with tempfile.TemporaryDirectory(
            prefix="bodyrig-p2-exavatar-heldout-evaluation-"
        ) as temp:
            stage = Path(temp)
            (
                main_dir,
                motion_dir,
                consumed_identity,
                consumed_motion,
            ) = _prepare_evaluation_stage(
                stage,
                request,
                workspace_root=workspace,
            )
            log = stage / "heldout-evaluation.log"
            generated = _run_evaluation(
                main_dir,
                motion_dir,
                request,
                log,
            )
            target = output / "review" / "heldout-animation.mp4"
            target.parent.mkdir(parents=True)
            shutil.copy2(generated, target)
            artifact = {
                "kind": "heldout-animation-review-video",
                "relative_path": "review/heldout-animation.mp4",
                "size_bytes": target.stat().st_size,
                "sha256": _file_sha(target),
            }

        manifest = {
            "format": MANIFEST_FORMAT,
            "version": VERSION,
            "performer_id": request["performer_id"],
            "selected_epoch_id": request["selected_epoch_id"],
            "teacher_input_sha256": request["teacher_input_sha256"],
            "p2_animation_plan_sha256": request["p2_animation_plan_sha256"],
            "p2_exavatar_animation_execution_input_sha256": request[
                "p2_exavatar_animation_execution_input_sha256"
            ],
            "train_animation_execution_receipt_sha256": request[
                "train_animation_execution_receipt_sha256"
            ],
            "p2_exavatar_heldout_evaluation_input_sha256": request[
                "p2_exavatar_heldout_evaluation_input_sha256"
            ],
            "p2_exavatar_heldout_evaluation_request_sha256": request[
                "p2_exavatar_heldout_evaluation_request_sha256"
            ],
            "exavatar_upstream_commit": PINNED_UPSTREAM_COMMIT,
            "exavatar_subject_id": request["exavatar_subject_id"],
            "test_epoch": PINNED_TEST_EPOCH,
            "adapter_revision": request["adapter_revision"],
            "held_out_source_ref": request["held_out_motion"]["source_ref"],
            "held_out_frame_count": request["held_out_motion"]["frame_count"],
            "held_out_frame_ids": request["held_out_motion"]["frame_ids"],
            "consumed_checkpoint_sha256": request["teacher_checkpoint"]["sha256"],
            "consumed_identity_artifacts": consumed_identity,
            "consumed_held_out_motion_artifacts": consumed_motion,
            "evaluation_artifacts": [artifact],
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
        (output / "heldout-evaluation-manifest.json").write_text(
            json.dumps(
                manifest,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": "P2_EXAVATAR_HELDOUT_EVALUATION_ADAPTER_COMPLETE",
                    "held_out_source_ref": manifest["held_out_source_ref"],
                    "held_out_frame_count": manifest["held_out_frame_count"],
                    "inference_only": True,
                    "teacher_training_performed": False,
                    "checkpoint_mutation_performed": False,
                    "held_out_evaluation_disclosed": True,
                    "human_animated_visual_acceptance_required": True,
                    "production_activation": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except ExAvatarP2HeldoutEvaluationAdapterError as exc:
        print(
            f"BodyRig P2 ExAvatar held-out evaluation adapter: FAIL: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

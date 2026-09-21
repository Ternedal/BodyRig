from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


REQUEST_FORMAT = "bodyrig-photoreal-p2-exavatar-animation-request"
MANIFEST_FORMAT = "bodyrig-photoreal-p2-exavatar-animation-manifest"
WORKSPACE_FORMAT = "bodyrig-photoreal-exavatar-workspace"
PREPROCESS_FORMAT = "bodyrig-photoreal-exavatar-preprocess-state"
RUNTIME_PREFLIGHT_FORMAT = "bodyrig-photoreal-exavatar-runtime-preflight"
VERSION = 1
PINNED_UPSTREAM_COMMIT = "d45268730c779fae4118f1a361cf9ff639bc4d1e"
PINNED_TEST_EPOCH = 4
IDENTITY_KINDS = {
    "shape-param": "shape_param.json",
    "face-offset": "face_offset.json",
    "joint-offset": "joint_offset.json",
    "locator-offset": "locator_offset.json",
}


class ExAvatarP2AnimationAdapterError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExAvatarP2AnimationAdapterError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ExAvatarP2AnimationAdapterError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise ExAvatarP2AnimationAdapterError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise ExAvatarP2AnimationAdapterError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise ExAvatarP2AnimationAdapterError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 1.0:
        raise ExAvatarP2AnimationAdapterError(f"{label} format/version mismatch")


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ExAvatarP2AnimationAdapterError(f"required file is missing/not regular: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _relative(value: Any, *, label: str) -> str:
    result = _text(value, label=label).replace("\\", "/")
    first = result.split("/", 1)[0]
    if result.startswith("/") or result.startswith("../") or "/../" in f"/{result}/" or ":" in first:
        raise ExAvatarP2AnimationAdapterError(f"{label} escapes its root")
    return result


def _copy_verified(
    source_value: Any,
    *,
    size_value: Any,
    sha_value: Any,
    destination: Path,
    label: str,
) -> str:
    source = Path(_text(source_value, label=f"{label} source path")).expanduser().resolve()
    size = size_value
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
        or not source.is_file()
        or source.is_symlink()
        or source.stat().st_size != size
    ):
        raise ExAvatarP2AnimationAdapterError(f"{label} source size/path drifted")
    expected = _sha(sha_value, label=f"{label} SHA-256")
    observed = _file_sha(source)
    if observed != expected:
        raise ExAvatarP2AnimationAdapterError(f"{label} source bytes drifted")
    if destination.exists() or destination.is_symlink():
        raise ExAvatarP2AnimationAdapterError(f"{label} destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if destination.stat().st_size != size or _file_sha(destination) != expected:
        raise ExAvatarP2AnimationAdapterError(f"{label} changed during staging copy")
    return expected


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise ExAvatarP2AnimationAdapterError(
            "could not verify pinned ExAvatar repository"
            + (f": {detail}" if detail else "")
        )
    return (completed.stdout or "").strip()


def _validate_workspace(root: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    receipt = _read_json(root / "workspace-receipt.json", label="ExAvatar workspace receipt")
    if receipt.get("format") != WORKSPACE_FORMAT:
        raise ExAvatarP2AnimationAdapterError("ExAvatar workspace format/version mismatch")
    _strict_v1(receipt.get("version"), label="ExAvatar workspace")
    claimed = _sha(receipt.get("workspace_sha256"), label="ExAvatar workspace SHA-256")
    if claimed != request.get("exavatar_workspace_sha256"):
        raise ExAvatarP2AnimationAdapterError("ExAvatar workspace differs from accepted animation input")
    if _digest(receipt, omit="workspace_sha256") != claimed:
        raise ExAvatarP2AnimationAdapterError("ExAvatar workspace digest mismatch")
    if receipt.get("upstream_commit") != PINNED_UPSTREAM_COMMIT:
        raise ExAvatarP2AnimationAdapterError("ExAvatar workspace upstream commit mismatch")
    if receipt.get("subject_id") != request.get("exavatar_subject_id"):
        raise ExAvatarP2AnimationAdapterError("ExAvatar workspace subject mismatch")
    if receipt.get("performer_id") != request.get("performer_id"):
        raise ExAvatarP2AnimationAdapterError("ExAvatar workspace performer mismatch")
    if receipt.get("selected_epoch_id") != request.get("selected_epoch_id"):
        raise ExAvatarP2AnimationAdapterError("ExAvatar workspace epoch mismatch")
    if receipt.get("teacher_input_sha256") != request.get("teacher_input_sha256"):
        raise ExAvatarP2AnimationAdapterError("ExAvatar workspace teacher-input mismatch")
    if receipt.get("dataset") != "Custom":
        raise ExAvatarP2AnimationAdapterError("ExAvatar workspace dataset is not Custom")
    for field, expected in (
        ("smplx_gender_explicit", True),
        ("upstream_default_gender_accepted", False),
        ("held_out_evaluation_disclosed", False),
        ("original_video_copied", False),
        ("dependency_root_modified", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if receipt.get(field) is not expected:
            raise ExAvatarP2AnimationAdapterError(
                f"ExAvatar workspace authority mismatch: {field}"
            )
    return receipt


def _validate_preprocess(root: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    state = _read_json(root / "preprocess-state.json", label="ExAvatar preprocess state")
    if state.get("format") != PREPROCESS_FORMAT:
        raise ExAvatarP2AnimationAdapterError("ExAvatar preprocess format/version mismatch")
    _strict_v1(state.get("version"), label="ExAvatar preprocess state")
    claimed = _sha(
        state.get("preprocess_state_sha256"),
        label="ExAvatar preprocess state SHA-256",
    )
    if claimed != request.get("exavatar_preprocess_state_sha256"):
        raise ExAvatarP2AnimationAdapterError(
            "ExAvatar preprocess state differs from accepted animation input"
        )
    if _digest(state, omit="preprocess_state_sha256") != claimed:
        raise ExAvatarP2AnimationAdapterError("ExAvatar preprocess-state digest mismatch")
    if state.get("workspace_sha256") != request.get("exavatar_workspace_sha256"):
        raise ExAvatarP2AnimationAdapterError(
            "ExAvatar preprocess state belongs to different workspace"
        )
    if state.get("preprocessing_complete") is not True:
        raise ExAvatarP2AnimationAdapterError("ExAvatar preprocessing is incomplete")
    if state.get("photoreal_acceptance_authority") is not False or state.get("production_activation") is not False:
        raise ExAvatarP2AnimationAdapterError(
            "ExAvatar preprocess state crossed downstream authority"
        )
    return state


def _validate_runtime_preflight(path: Path, workspace_sha: str) -> dict[str, Any]:
    value = _read_json(path, label="ExAvatar runtime preflight")
    if value.get("format") != RUNTIME_PREFLIGHT_FORMAT:
        raise ExAvatarP2AnimationAdapterError("ExAvatar runtime preflight format/version mismatch")
    _strict_v1(value.get("version"), label="ExAvatar runtime preflight")
    if value.get("workspace_sha256") != workspace_sha:
        raise ExAvatarP2AnimationAdapterError(
            "ExAvatar runtime preflight belongs to different workspace"
        )
    if value.get("runtime_environment_ready") is not True or value.get("blockers") != []:
        raise ExAvatarP2AnimationAdapterError("ExAvatar runtime environment is not ready")
    claimed = _sha(
        value.get("runtime_preflight_sha256"),
        label="ExAvatar runtime preflight SHA-256",
    )
    if _digest(value, omit="runtime_preflight_sha256") != claimed:
        raise ExAvatarP2AnimationAdapterError("ExAvatar runtime preflight digest mismatch")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise ExAvatarP2AnimationAdapterError(
            "ExAvatar runtime preflight crossed downstream authority"
        )
    return value


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
        "motion_driver",
        "source_media_rehash_performed",
        "held_out_evaluation_disclosed",
        "train_motion_driver_only",
        "human_animated_visual_acceptance_required",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_exavatar_animation_request_sha256",
    }
    if set(request) != expected:
        raise ExAvatarP2AnimationAdapterError(
            "P2 ExAvatar animation request fields must match v1 exactly"
        )
    if request.get("format") != REQUEST_FORMAT:
        raise ExAvatarP2AnimationAdapterError(
            "P2 ExAvatar animation request format/version mismatch"
        )
    _strict_v1(request.get("version"), label="P2 ExAvatar animation request")
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "exavatar_workspace_sha256",
        "exavatar_preprocess_state_sha256",
        "adapter_revision",
    ):
        _sha(request.get(field), label=f"P2 ExAvatar animation request {field}")
    claimed = _sha(
        request.get("p2_exavatar_animation_request_sha256"),
        label="P2 ExAvatar animation request SHA-256",
    )
    if _digest(request, omit="p2_exavatar_animation_request_sha256") != claimed:
        raise ExAvatarP2AnimationAdapterError("P2 ExAvatar animation request digest mismatch")
    if request.get("exavatar_upstream_repository") != "https://github.com/mks0601/ExAvatar_RELEASE":
        raise ExAvatarP2AnimationAdapterError("P2 ExAvatar animation repository mismatch")
    if request.get("exavatar_upstream_commit") != PINNED_UPSTREAM_COMMIT:
        raise ExAvatarP2AnimationAdapterError("P2 ExAvatar animation upstream commit mismatch")
    if request.get("test_epoch") != PINNED_TEST_EPOCH:
        raise ExAvatarP2AnimationAdapterError("P2 ExAvatar animation epoch mismatch")
    if _file_sha(Path(__file__).resolve()) != _sha(
        request.get("adapter_revision"),
        label="P2 ExAvatar adapter revision",
    ):
        raise ExAvatarP2AnimationAdapterError(
            "P2 ExAvatar animation adapter bytes differ from core request"
        )
    for field, expected_value in (
        ("source_media_rehash_performed", False),
        ("held_out_evaluation_disclosed", False),
        ("train_motion_driver_only", True),
        ("human_animated_visual_acceptance_required", True),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if request.get(field) is not expected_value:
            raise ExAvatarP2AnimationAdapterError(
                f"P2 ExAvatar animation request authority mismatch: {field}"
            )
    driver = request.get("motion_driver")
    if not isinstance(driver, Mapping) or driver.get("split") != "train" or driver.get("role") != "motion-driver":
        raise ExAvatarP2AnimationAdapterError(
            "P2 ExAvatar animation request is not TRAIN-motion-only"
        )
    _validate_workspace(workspace_root, request)
    _validate_preprocess(workspace_root, request)
    _validate_runtime_preflight(
        runtime_preflight_path,
        _sha(request.get("exavatar_workspace_sha256"), label="request workspace SHA-256"),
    )


def _copy_code(source: Path, destination: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        raise ExAvatarP2AnimationAdapterError(f"required ExAvatar code tree missing: {source}")
    shutil.copytree(
        source,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


def _prepare_stage(
    stage: Path,
    request: Mapping[str, Any],
    *,
    workspace_root: Path,
) -> tuple[Path, Path, list[dict[str, str]], list[dict[str, str]]]:
    source_repo = workspace_root / "repos" / "ExAvatar_RELEASE"
    if _git(source_repo, "rev-parse", "HEAD").lower() != PINNED_UPSTREAM_COMMIT:
        raise ExAvatarP2AnimationAdapterError("ExAvatar workspace repository HEAD drifted")
    protected = [
        "avatar/main/animate.py",
        "avatar/main/model.py",
        "avatar/common/base.py",
        "avatar/data/Custom/Custom.py",
    ]
    if _git(source_repo, "status", "--porcelain", "--", *protected):
        raise ExAvatarP2AnimationAdapterError(
            "pinned ExAvatar animation/runtime code has local modifications"
        )

    avatar = stage / "avatar"
    _copy_code(source_repo / "avatar" / "main", avatar / "main")
    _copy_code(source_repo / "avatar" / "common", avatar / "common")
    custom_source = source_repo / "avatar" / "data" / "Custom"
    if not custom_source.is_dir():
        raise ExAvatarP2AnimationAdapterError("ExAvatar Custom dataset code is missing")
    shutil.copytree(
        custom_source,
        avatar / "data" / "Custom",
        symlinks=True,
        ignore=shutil.ignore_patterns("data", "__pycache__", "*.pyc", "*.pyo"),
    )

    subject = _text(request.get("exavatar_subject_id"), label="ExAvatar subject id", maximum=160)
    dataset = avatar / "data" / "Custom" / "data" / subject
    identity_dir = dataset / "smplx_optimized"
    identity_dir.mkdir(parents=True)

    consumed_identity: list[dict[str, str]] = []
    identity = request.get("identity_artifacts")
    if not isinstance(identity, list) or len(identity) != 4:
        raise ExAvatarP2AnimationAdapterError("P2 ExAvatar identity universe is incomplete")
    seen_kinds: set[str] = set()
    for raw in identity:
        if not isinstance(raw, Mapping):
            raise ExAvatarP2AnimationAdapterError("P2 ExAvatar identity entry is invalid")
        kind = _text(raw.get("kind"), label="P2 ExAvatar identity kind", maximum=64)
        filename = IDENTITY_KINDS.get(kind)
        if filename is None or kind in seen_kinds:
            raise ExAvatarP2AnimationAdapterError("P2 ExAvatar identity kind universe mismatch")
        seen_kinds.add(kind)
        digest = _copy_verified(
            raw.get("linux_source_path"),
            size_value=raw.get("size_bytes"),
            sha_value=raw.get("sha256"),
            destination=identity_dir / filename,
            label=f"P2 ExAvatar {kind}",
        )
        consumed_identity.append({"kind": kind, "sha256": digest})
    if seen_kinds != set(IDENTITY_KINDS):
        raise ExAvatarP2AnimationAdapterError("P2 ExAvatar identity universe mismatch")

    checkpoint = request.get("teacher_checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise ExAvatarP2AnimationAdapterError("P2 ExAvatar checkpoint binding is invalid")
    checkpoint_target = avatar / "output" / "model_dump" / subject / "snapshot_4.pth"
    checkpoint_digest = _copy_verified(
        checkpoint.get("linux_source_path"),
        size_value=checkpoint.get("size_bytes"),
        sha_value=checkpoint.get("sha256"),
        destination=checkpoint_target,
        label="P2 ExAvatar teacher checkpoint",
    )

    driver = request.get("motion_driver")
    if not isinstance(driver, Mapping):
        raise ExAvatarP2AnimationAdapterError("P2 ExAvatar motion driver is invalid")
    motion = stage / "motion"
    motion.mkdir()
    source_ref = _text(driver.get("source_ref"), label="P2 ExAvatar motion source ref", maximum=64)
    prefix = f"tasks/{source_ref}/motion/"
    artifacts = driver.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ExAvatarP2AnimationAdapterError("P2 ExAvatar motion artifact universe is empty")
    consumed_motion: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping):
            raise ExAvatarP2AnimationAdapterError("P2 ExAvatar motion artifact is invalid")
        relative = _relative(raw.get("relative_path"), label="P2 ExAvatar motion artifact path")
        if relative in seen_paths or not relative.startswith(prefix):
            raise ExAvatarP2AnimationAdapterError("P2 ExAvatar motion artifact universe mismatch")
        seen_paths.add(relative)
        local = relative[len(prefix):]
        if not local or local.startswith("../") or "/../" in f"/{local}/":
            raise ExAvatarP2AnimationAdapterError("P2 ExAvatar motion staging path is invalid")
        digest = _copy_verified(
            raw.get("linux_source_path"),
            size_value=raw.get("size_bytes"),
            sha_value=raw.get("sha256"),
            destination=motion / local,
            label="P2 ExAvatar motion artifact",
        )
        consumed_motion.append({"relative_path": relative, "sha256": digest})

    return (
        avatar / "main",
        motion,
        sorted(consumed_identity, key=lambda item: item["kind"]),
        sorted(consumed_motion, key=lambda item: item["relative_path"]),
    )


def _run_animation(main: Path, motion: Path, request: Mapping[str, Any], log: Path) -> Path:
    subject = _text(request.get("exavatar_subject_id"), label="ExAvatar subject id", maximum=160)
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["PYOPENGL_PLATFORM"] = "egl"
    argv = [
        sys.executable,
        "animate.py",
        "--subject_id",
        subject,
        "--test_epoch",
        str(PINNED_TEST_EPOCH),
        "--motion_path",
        str(motion),
    ]
    with log.open("wb") as stream:
        completed = subprocess.run(
            argv,
            cwd=str(main),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            shell=False,
            check=False,
        )
    if completed.returncode != 0:
        try:
            tail = log.read_bytes()[-12000:].decode("utf-8", errors="replace").strip()
        except OSError:
            tail = ""
        raise ExAvatarP2AnimationAdapterError(
            f"pinned ExAvatar animate.py failed with exit code {completed.returncode}"
            + (f": {tail}" if tail else "")
        )
    output = main / "motion.mp4"
    if not output.is_file() or output.is_symlink() or output.stat().st_size < 1:
        raise ExAvatarP2AnimationAdapterError("pinned ExAvatar animate.py produced no motion.mp4")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pinned build-private ExAvatar P2 animation adapter."
    )
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--runtime-preflight", type=Path, required=True)
    parser.add_argument("--bodyrig-request", type=Path, required=True)
    parser.add_argument("--bodyrig-output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        request = _read_json(
            args.bodyrig_request.expanduser().resolve(),
            label="P2 ExAvatar animation request",
        )
        workspace = args.workspace_root.expanduser().resolve()
        preflight = args.runtime_preflight.expanduser().resolve()
        output = args.bodyrig_output.expanduser().resolve()
        if not workspace.is_dir() or workspace.is_symlink():
            raise ExAvatarP2AnimationAdapterError(
                f"accepted ExAvatar workspace missing/not regular: {workspace}"
            )
        if not preflight.is_file() or preflight.is_symlink():
            raise ExAvatarP2AnimationAdapterError(
                f"ExAvatar runtime preflight missing/not regular: {preflight}"
            )
        if not output.is_dir() or output.is_symlink() or any(output.iterdir()):
            raise ExAvatarP2AnimationAdapterError(
                "BodyRig P2 animation output directory must exist and be empty"
            )
        _validate_request(
            request,
            workspace_root=workspace,
            runtime_preflight_path=preflight,
        )

        with tempfile.TemporaryDirectory(prefix="bodyrig-p2-exavatar-animation-") as temp:
            stage = Path(temp)
            main_dir, motion_dir, consumed_identity, consumed_motion = _prepare_stage(
                stage,
                request,
                workspace_root=workspace,
            )
            log = stage / "animate.log"
            generated = _run_animation(main_dir, motion_dir, request, log)

            target = output / "review" / "animation.mp4"
            target.parent.mkdir(parents=True)
            shutil.copy2(generated, target)
            animation_artifact = {
                "kind": "animation-review-video",
                "relative_path": "review/animation.mp4",
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
            "p2_exavatar_animation_request_sha256": request[
                "p2_exavatar_animation_request_sha256"
            ],
            "exavatar_upstream_commit": PINNED_UPSTREAM_COMMIT,
            "exavatar_subject_id": request["exavatar_subject_id"],
            "test_epoch": PINNED_TEST_EPOCH,
            "adapter_revision": request["adapter_revision"],
            "motion_driver_source_ref": request["motion_driver"]["source_ref"],
            "motion_frame_count": request["motion_driver"]["frame_count"],
            "motion_frame_ids": request["motion_driver"]["frame_ids"],
            "consumed_checkpoint_sha256": request["teacher_checkpoint"]["sha256"],
            "consumed_identity_artifacts": consumed_identity,
            "consumed_motion_artifacts": consumed_motion,
            "animation_artifacts": [animation_artifact],
            "animation_complete": True,
            "source_media_rehash_performed": False,
            "held_out_evaluation_disclosed": False,
            "human_animated_visual_acceptance_required": True,
            "p2_animated_teacher_acceptance_authority": False,
            "quest_distillation_authorized": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }
        (output / "animation-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": "P2_EXAVATAR_ANIMATION_ADAPTER_COMPLETE",
                    "motion_driver_source_ref": manifest["motion_driver_source_ref"],
                    "motion_frame_count": manifest["motion_frame_count"],
                    "animation_artifact_count": 1,
                    "held_out_evaluation_disclosed": False,
                    "human_animated_visual_acceptance_required": True,
                    "production_activation": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except ExAvatarP2AnimationAdapterError as exc:
        print(f"BodyRig P2 ExAvatar animation adapter: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

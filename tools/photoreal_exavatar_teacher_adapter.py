from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

UPSTREAM_REPOSITORY = "https://github.com/mks0601/ExAvatar_RELEASE"
UPSTREAM_COMMIT = "d45268730c779fae4118f1a361cf9ff639bc4d1e"
REQUEST_FORMAT = "bodyrig-photoreal-teacher-request"
WORKSPACE_FORMAT = "bodyrig-photoreal-exavatar-workspace"
PREPROCESS_FORMAT = "bodyrig-photoreal-exavatar-preprocess-state"
RUNTIME_PREFLIGHT_FORMAT = "bodyrig-photoreal-exavatar-runtime-preflight"
MANIFEST_FORMAT = "bodyrig-photoreal-teacher-manifest"
VERSION = 1
FINAL_EPOCH = 4
NEUTRAL_RENDER_COUNT = 50
NEUTRAL_CAMERA_MANIFEST_FORMAT = "bodyrig-photoreal-exavatar-neutral-camera-manifest"
NEUTRAL_CAMERA_MANIFEST_VERSION = 1
NEUTRAL_ELEVATION_RADIANS = -math.pi / 6.0


class ExAvatarTeacherAdapterError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExAvatarTeacherAdapterError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ExAvatarTeacherAdapterError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise ExAvatarTeacherAdapterError(f"{label} is invalid")
    return result


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _run(argv: list[str], *, cwd: Path, log_path: Path, label: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["PYOPENGL_PLATFORM"] = "egl"
    try:
        with log_path.open("wb") as log:
            completed = subprocess.run(
                argv,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
                check=False,
            )
    except OSError as exc:
        raise ExAvatarTeacherAdapterError(f"{label} could not start: {exc}") from exc
    if completed.returncode != 0:
        try:
            tail = log_path.read_bytes()[-12000:].decode("utf-8", errors="replace").strip()
        except OSError:
            tail = ""
        raise ExAvatarTeacherAdapterError(
            f"{label} failed with exit code {completed.returncode}" + (f": {tail}" if tail else "")
        )


def _validate_request(request: Mapping[str, Any], args: argparse.Namespace) -> None:
    if request.get("format") != REQUEST_FORMAT or request.get("version") != VERSION:
        raise ExAvatarTeacherAdapterError("teacher request format/version mismatch")
    if request.get("adapter") != args.bodyrig_adapter or request.get("adapter_revision") != args.bodyrig_revision:
        raise ExAvatarTeacherAdapterError("teacher request adapter provenance mismatch")
    if request.get("upstream_repository") != UPSTREAM_REPOSITORY or request.get("upstream_commit") != UPSTREAM_COMMIT:
        raise ExAvatarTeacherAdapterError("teacher request upstream provenance mismatch")
    if args.bodyrig_upstream_commit != UPSTREAM_COMMIT:
        raise ExAvatarTeacherAdapterError("CLI upstream commit differs from pinned ExAvatar commit")
    if request.get("held_out_paths_disclosed") is not False or request.get("held_out_frame_hashes_disclosed") is not False:
        raise ExAvatarTeacherAdapterError("teacher request disclosed held-out evaluation evidence")
    if request.get("photoreal_acceptance_authority") is not False or request.get("production_activation") is not False:
        raise ExAvatarTeacherAdapterError("teacher request crossed downstream authority")
    sources = request.get("training_sources")
    observations = request.get("training_observations")
    if not isinstance(sources, list) or not sources or not isinstance(observations, list) or not observations:
        raise ExAvatarTeacherAdapterError("teacher request has no training evidence")


def _validate_workspace(root: Path, request: Mapping[str, Any]) -> tuple[dict[str, Any], Path]:
    receipt = _read_json(root / "workspace-receipt.json", label="ExAvatar workspace receipt")
    if receipt.get("format") != WORKSPACE_FORMAT or receipt.get("version") != VERSION:
        raise ExAvatarTeacherAdapterError("ExAvatar workspace receipt format/version mismatch")
    if receipt.get("upstream_commit") != UPSTREAM_COMMIT:
        raise ExAvatarTeacherAdapterError("ExAvatar workspace targets different upstream commit")
    if receipt.get("teacher_input_sha256") != request.get("teacher_input_sha256"):
        raise ExAvatarTeacherAdapterError("ExAvatar workspace targets different teacher input")
    if receipt.get("performer_id") != request.get("performer_id") or receipt.get("selected_epoch_id") != request.get("selected_epoch_id"):
        raise ExAvatarTeacherAdapterError("ExAvatar workspace performer/epoch mismatch")
    if receipt.get("dataset") != "Custom" or receipt.get("smplx_gender_explicit") is not True:
        raise ExAvatarTeacherAdapterError("ExAvatar workspace config authority is invalid")
    if receipt.get("upstream_default_gender_accepted") is not False:
        raise ExAvatarTeacherAdapterError("ExAvatar workspace accepted upstream gender default")
    if receipt.get("held_out_evaluation_disclosed") is not False or receipt.get("original_video_copied") is not False:
        raise ExAvatarTeacherAdapterError("ExAvatar workspace contains forbidden held-out/original source evidence")
    if receipt.get("dependency_root_modified") is not False:
        raise ExAvatarTeacherAdapterError("ExAvatar workspace dependency-root integrity failed")
    if receipt.get("photoreal_acceptance_authority") is not False or receipt.get("production_activation") is not False:
        raise ExAvatarTeacherAdapterError("ExAvatar workspace crossed downstream authority")
    declared = _sha(receipt.get("workspace_sha256"), label="workspace SHA-256")
    if _digest(receipt, omit="workspace_sha256") != declared:
        raise ExAvatarTeacherAdapterError("ExAvatar workspace digest mismatch")
    subject = str(receipt.get("subject_id") or "").strip()
    dataset = root / str(receipt.get("working_dataset_relative_path") or "")
    if not subject or not dataset.is_dir():
        raise ExAvatarTeacherAdapterError("ExAvatar workspace subject/dataset is missing")
    if (dataset / "video.mp4").exists():
        raise ExAvatarTeacherAdapterError("ExAvatar workspace unexpectedly contains original video.mp4")
    if (dataset / "frame_list_test.txt").read_text(encoding="utf-8") != "":
        raise ExAvatarTeacherAdapterError("ExAvatar workspace test list is not empty")
    return receipt, dataset


def _validate_preprocess(root: Path, workspace: Mapping[str, Any]) -> dict[str, Any]:
    state = _read_json(root / "preprocess-state.json", label="ExAvatar preprocess state")
    if state.get("format") != PREPROCESS_FORMAT or state.get("version") != VERSION:
        raise ExAvatarTeacherAdapterError("ExAvatar preprocess state format/version mismatch")
    if state.get("workspace_sha256") != workspace.get("workspace_sha256"):
        raise ExAvatarTeacherAdapterError("ExAvatar preprocess state belongs to different workspace")
    if state.get("preprocessing_complete") is not True:
        raise ExAvatarTeacherAdapterError("ExAvatar preprocessing is incomplete")
    if state.get("teacher_training_authorized_by_preprocessing") is not False:
        raise ExAvatarTeacherAdapterError("ExAvatar preprocessing improperly granted teacher authority")
    if state.get("photoreal_acceptance_authority") is not False or state.get("production_activation") is not False:
        raise ExAvatarTeacherAdapterError("ExAvatar preprocess state crossed downstream authority")
    declared = _sha(state.get("preprocess_state_sha256"), label="preprocess state SHA-256")
    if _digest(state, omit="preprocess_state_sha256") != declared:
        raise ExAvatarTeacherAdapterError("ExAvatar preprocess state digest mismatch")
    return state


def _validate_runtime_preflight(path: Path, workspace: Mapping[str, Any]) -> dict[str, Any]:
    receipt = _read_json(path, label="ExAvatar runtime preflight")
    if receipt.get("format") != RUNTIME_PREFLIGHT_FORMAT or receipt.get("version") != VERSION:
        raise ExAvatarTeacherAdapterError("ExAvatar runtime preflight format/version mismatch")
    if receipt.get("workspace_sha256") != workspace.get("workspace_sha256"):
        raise ExAvatarTeacherAdapterError("ExAvatar runtime preflight belongs to different workspace")
    if receipt.get("runtime_environment_ready") is not True or receipt.get("blockers") != []:
        raise ExAvatarTeacherAdapterError("ExAvatar runtime environment is not ready")
    if receipt.get("photoreal_acceptance_authority") is not False or receipt.get("production_activation") is not False:
        raise ExAvatarTeacherAdapterError("ExAvatar runtime preflight crossed downstream authority")
    declared = _sha(receipt.get("runtime_preflight_sha256"), label="runtime preflight SHA-256")
    if _digest(receipt, omit="runtime_preflight_sha256") != declared:
        raise ExAvatarTeacherAdapterError("ExAvatar runtime preflight digest mismatch")
    return receipt


def _materialization(dataset: Path, request: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    receipt = _read_json(dataset / "materialization-receipt.json", label="ExAvatar materialization receipt")
    if receipt.get("teacher_input_sha256") != request.get("teacher_input_sha256"):
        raise ExAvatarTeacherAdapterError("materialization targets different teacher input")
    if receipt.get("held_out_evaluation_disclosed") is not False or receipt.get("original_video_copied") is not False:
        raise ExAvatarTeacherAdapterError("materialization disclosed forbidden source/eval data")
    source_key = str(receipt.get("source_key") or "").strip()
    frames = receipt.get("frames")
    if not source_key or not isinstance(frames, list) or not frames:
        raise ExAvatarTeacherAdapterError("materialization source/frame provenance is missing")

    source_universe = {
        str(item.get("source_key") or ""): item
        for item in request["training_sources"]
        if isinstance(item, Mapping)
    }
    if source_key not in source_universe:
        raise ExAvatarTeacherAdapterError("ExAvatar benchmark source is outside authorized training universe")
    if source_universe[source_key].get("sha256") != receipt.get("source_sha256"):
        raise ExAvatarTeacherAdapterError("ExAvatar benchmark source SHA differs from teacher request")

    authorized: set[tuple[str, str, float | None, str]] = set()
    for item in request["training_observations"]:
        if not isinstance(item, Mapping):
            continue
        timestamp_raw = item.get("timestamp_seconds")
        timestamp = None if timestamp_raw is None else round(float(timestamp_raw), 6)
        authorized.add((str(item.get("source_key") or ""), str(item.get("frame_sha256") or "").lower(), timestamp, str(item.get("eye") or "")))

    consumed: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, Mapping):
            raise ExAvatarTeacherAdapterError("materialization frame entry is invalid")
        timestamp = round(float(frame.get("timestamp_seconds")), 6)
        key = (source_key, _sha(frame.get("source_frame_sha256"), label="materialization source frame SHA-256"), timestamp, str(frame.get("eye") or ""))
        if key not in authorized:
            raise ExAvatarTeacherAdapterError("materialized ExAvatar frame is outside authorized training observations")
        consumed.append({"source_key": key[0], "frame_sha256": key[1], "timestamp_seconds": key[2], "eye": key[3]})
    if not consumed:
        raise ExAvatarTeacherAdapterError("ExAvatar benchmark consumed no authorized observations")
    return source_key, consumed


def _cleanup_atomic_checkpoint_temps(model_dir: Path) -> None:
    if not model_dir.exists():
        if model_dir.is_symlink():
            raise ExAvatarTeacherAdapterError(f"ExAvatar model path is a broken symlink: {model_dir}")
        return
    if not model_dir.is_dir() or model_dir.is_symlink():
        raise ExAvatarTeacherAdapterError(f"ExAvatar model path is not a regular directory: {model_dir}")
    prefix = "snapshot_"
    suffix = ".pth.bodyrig-tmp"
    for path in model_dir.iterdir():
        name = path.name
        if not (name.startswith(prefix) and name.endswith(suffix)):
            continue
        raw_epoch = name[len(prefix) : -len(suffix)]
        if not raw_epoch.isdigit():
            raise ExAvatarTeacherAdapterError(f"invalid ExAvatar checkpoint temp name: {name}")
        epoch = int(raw_epoch)
        if epoch < 0 or epoch > FINAL_EPOCH:
            raise ExAvatarTeacherAdapterError(f"unexpected ExAvatar checkpoint temp epoch: {epoch}")
        if not path.is_file() or path.is_symlink():
            raise ExAvatarTeacherAdapterError(f"unsafe ExAvatar checkpoint temp entry: {name}")
        path.unlink()


def _snapshot_epochs(model_dir: Path) -> list[int]:
    if not model_dir.exists():
        if model_dir.is_symlink():
            raise ExAvatarTeacherAdapterError(f"ExAvatar model path is a broken symlink: {model_dir}")
        return []
    if not model_dir.is_dir() or model_dir.is_symlink():
        raise ExAvatarTeacherAdapterError(f"ExAvatar model path is not a regular directory: {model_dir}")
    epochs: list[int] = []
    for path in model_dir.iterdir():
        if not path.is_file() or path.is_symlink():
            raise ExAvatarTeacherAdapterError(
                f"unexpected non-regular file entry in ExAvatar model directory: {path.name}"
            )
        name = path.name
        if not name.startswith("snapshot_") or not name.endswith(".pth"):
            raise ExAvatarTeacherAdapterError(
                f"unexpected file in ExAvatar model directory: {name}"
            )
        raw_epoch = name[len("snapshot_") : -len(".pth")]
        if not raw_epoch.isdigit():
            raise ExAvatarTeacherAdapterError(f"invalid ExAvatar snapshot name: {name}")
        epoch = int(raw_epoch)
        if epoch < 0 or epoch > FINAL_EPOCH:
            raise ExAvatarTeacherAdapterError(f"unexpected ExAvatar snapshot epoch: {epoch}")
        if epoch in epochs:
            raise ExAvatarTeacherAdapterError(f"duplicate ExAvatar snapshot epoch: {epoch}")
        if path.stat().st_size < 1:
            raise ExAvatarTeacherAdapterError(f"empty ExAvatar snapshot: {name}")
        epochs.append(epoch)
    return sorted(epochs)


def _training_resume_plan(
    model_dir: Path,
    neutral_dir: Path,
    *,
    subject: str,
) -> tuple[str, list[str] | None, str | None]:
    _cleanup_atomic_checkpoint_temps(model_dir)
    snapshot_epochs = _snapshot_epochs(model_dir)
    if neutral_dir.is_symlink():
        raise ExAvatarTeacherAdapterError(
            f"ExAvatar neutral-pose path may not be a symlink: {neutral_dir}"
        )
    if neutral_dir.exists() and not neutral_dir.is_dir():
        raise ExAvatarTeacherAdapterError(
            f"ExAvatar neutral-pose path is not a directory: {neutral_dir}"
        )
    final_checkpoint = model_dir / f"snapshot_{FINAL_EPOCH}.pth"
    if final_checkpoint.is_file():
        return "reuse-final-checkpoint", None, None
    if neutral_dir.exists():
        if snapshot_epochs:
            raise ExAvatarTeacherAdapterError(
                "neutral-pose output exists before final checkpoint; refusing ambiguous resume"
            )
        raise ExAvatarTeacherAdapterError(
            "neutral-pose output exists without any training checkpoint"
        )
    if snapshot_epochs:
        return (
            "resume-from-checkpoint",
            [sys.executable, "train.py", "--subject_id", subject, "--continue"],
            "train-resume.log",
        )
    return (
        "fresh",
        [sys.executable, "train.py", "--subject_id", subject],
        "train.log",
    )


def _neutral_render_complete(neutral_dir: Path) -> bool:
    if neutral_dir.is_symlink():
        raise ExAvatarTeacherAdapterError(
            f"ExAvatar neutral-pose path may not be a symlink: {neutral_dir}"
        )
    if not neutral_dir.exists():
        return False
    if not neutral_dir.is_dir():
        raise ExAvatarTeacherAdapterError(
            f"ExAvatar neutral-pose path is not a directory: {neutral_dir}"
        )
    expected = [
        *[neutral_dir / f"{index}.png" for index in range(NEUTRAL_RENDER_COUNT)],
        neutral_dir / "rgb.txt",
    ]
    return all(path.is_file() and not path.is_symlink() and path.stat().st_size > 0 for path in expected)


def _prepare_neutral_render(neutral_dir: Path) -> bool:
    if _neutral_render_complete(neutral_dir):
        return False
    if neutral_dir.exists():
        if not neutral_dir.is_dir() or neutral_dir.is_symlink():
            raise ExAvatarTeacherAdapterError(
                f"ExAvatar neutral-pose path is not a removable partial directory: {neutral_dir}"
            )
        shutil.rmtree(neutral_dir)
    return True


def _copy_artifact(source: Path, output: Path, relative: str, kind: str) -> dict[str, Any]:
    if not source.is_file() or source.stat().st_size < 1:
        raise ExAvatarTeacherAdapterError(f"teacher artifact source missing: {source}")
    target = output / relative
    if target.exists():
        raise ExAvatarTeacherAdapterError(f"teacher artifact destination already exists: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {"kind": kind, "relative_path": relative.replace("\\", "/"), "size_bytes": target.stat().st_size, "sha256": _file_sha(target)}


def _neutral_camera_manifest() -> dict[str, Any]:
    views: list[dict[str, Any]] = []
    for index in range(NEUTRAL_RENDER_COUNT):
        upstream_azimuth = math.pi + (math.pi * 2.0 * index / NEUTRAL_RENDER_COUNT)
        upstream_degrees = 180.0 + (360.0 * index / NEUTRAL_RENDER_COUNT)
        normalized_degrees = ((upstream_degrees + 180.0) % 360.0) - 180.0
        views.append(
            {
                "index": index,
                "render_relative_path": f"review/neutral-pose/{index}.png",
                "upstream_azimuth_radians": round(upstream_azimuth, 12),
                "upstream_azimuth_degrees": round(upstream_degrees, 6),
                "normalized_azimuth_degrees": round(normalized_degrees, 6),
                "elevation_radians": round(NEUTRAL_ELEVATION_RADIANS, 12),
                "elevation_degrees": -30.0,
                "semantic_view_label": None,
            }
        )
    manifest: dict[str, Any] = {
        "format": NEUTRAL_CAMERA_MANIFEST_FORMAT,
        "version": NEUTRAL_CAMERA_MANIFEST_VERSION,
        "upstream_repository": UPSTREAM_REPOSITORY,
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_script": "avatar/main/get_neutral_pose.py",
        "view_count": NEUTRAL_RENDER_COUNT,
        "view_ordering": "upstream-get-neutral-pose-v1",
        "views": views,
        "semantic_view_labels_machine_assigned": False,
        "human_semantic_alignment_required": True,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    manifest["camera_manifest_sha256"] = _digest(manifest, omit="camera_manifest_sha256")
    return manifest


def _write_neutral_camera_manifest(output: Path) -> dict[str, Any]:
    relative = "review/neutral-pose/cameras.json"
    target = output / relative
    if target.exists():
        raise ExAvatarTeacherAdapterError(f"teacher artifact destination already exists: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    value = _neutral_camera_manifest()
    target.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return {
        "kind": "neutral-pose-camera-manifest",
        "relative_path": relative,
        "size_bytes": target.stat().st_size,
        "sha256": _file_sha(target),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BodyRig ExAvatar photoreal teacher benchmark adapter")
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--runtime-preflight", type=Path, required=True)
    parser.add_argument("--bodyrig-request", type=Path, required=True)
    parser.add_argument("--bodyrig-output", type=Path, required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--bodyrig-upstream-commit", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request = _read_json(args.bodyrig_request.expanduser().resolve(), label="BodyRig teacher request")
        _validate_request(request, args)
        root = args.workspace_root.expanduser().resolve()
        output = args.bodyrig_output.expanduser().resolve()
        runtime_preflight_path = args.runtime_preflight.expanduser().resolve()
        if not root.is_dir():
            raise ExAvatarTeacherAdapterError(f"ExAvatar workspace not found: {root}")
        if not output.is_dir() or any(output.iterdir()):
            raise ExAvatarTeacherAdapterError("BodyRig teacher output directory must exist and be empty")
        workspace, dataset = _validate_workspace(root, request)
        _validate_preprocess(root, workspace)
        runtime_preflight = _validate_runtime_preflight(runtime_preflight_path, workspace)
        source_key, consumed_observations = _materialization(dataset, request)

        exavatar_main = root / "repos" / "ExAvatar_RELEASE" / "avatar" / "main"
        subject = str(workspace["subject_id"])
        model_dir = root / "repos" / "ExAvatar_RELEASE" / "avatar" / "output" / "model_dump" / subject
        neutral_dir = exavatar_main / "neutral_pose"
        logs = root / "logs" / "teacher"
        checkpoint = model_dir / f"snapshot_{FINAL_EPOCH}.pth"
        training_mode, train_argv, train_log_name = _training_resume_plan(
            model_dir,
            neutral_dir,
            subject=subject,
        )
        if train_argv is not None:
            _run(
                train_argv,
                cwd=exavatar_main,
                log_path=logs / str(train_log_name),
                label=(
                    "ExAvatar teacher training resume"
                    if training_mode == "resume-from-checkpoint"
                    else "ExAvatar teacher training"
                ),
            )

        if not checkpoint.is_file() or checkpoint.stat().st_size < 1:
            raise ExAvatarTeacherAdapterError(f"ExAvatar final checkpoint missing: {checkpoint}")

        render_neutral = _prepare_neutral_render(neutral_dir)
        if render_neutral:
            _run(
                [sys.executable, "get_neutral_pose.py", "--subject_id", subject, "--test_epoch", str(FINAL_EPOCH)],
                cwd=exavatar_main,
                log_path=logs / "neutral-pose.log",
                label="ExAvatar neutral-pose review rendering",
            )
        expected_renders = [neutral_dir / f"{index}.png" for index in range(NEUTRAL_RENDER_COUNT)]
        if any(not path.is_file() or path.stat().st_size < 1 for path in expected_renders):
            raise ExAvatarTeacherAdapterError("ExAvatar neutral-pose review render set is incomplete")
        if not (neutral_dir / "rgb.txt").is_file():
            raise ExAvatarTeacherAdapterError("ExAvatar neutral-pose Gaussian RGB/XYZ export is missing")

        artifacts: list[dict[str, Any]] = []
        artifacts.append(_copy_artifact(checkpoint, output, f"checkpoint/snapshot_{FINAL_EPOCH}.pth", "checkpoint"))
        for index, path in enumerate(expected_renders):
            artifacts.append(_copy_artifact(path, output, f"review/neutral-pose/{index}.png", "neutral-pose-render"))
        artifacts.append(_write_neutral_camera_manifest(output))
        artifacts.append(_copy_artifact(neutral_dir / "rgb.txt", output, "review/neutral-pose/rgb.txt", "neutral-pose-gaussian-export"))
        artifacts.append(_copy_artifact(root / "workspace-receipt.json", output, "provenance/workspace-receipt.json", "provenance"))
        artifacts.append(_copy_artifact(root / "preprocess-state.json", output, "provenance/preprocess-state.json", "provenance"))
        artifacts.append(_copy_artifact(runtime_preflight_path, output, "provenance/runtime-preflight.json", "provenance"))
        artifacts.append(_copy_artifact(dataset / "materialization-receipt.json", output, "provenance/materialization-receipt.json", "provenance"))

        manifest = {
            "format": MANIFEST_FORMAT,
            "version": VERSION,
            "performer_id": request["performer_id"],
            "selected_epoch_id": request["selected_epoch_id"],
            "teacher_input_sha256": request["teacher_input_sha256"],
            "adapter": request["adapter"],
            "adapter_revision": request["adapter_revision"],
            "upstream_repository": request["upstream_repository"],
            "upstream_commit": request["upstream_commit"],
            "training_complete": True,
            "consumed_training_source_keys": [source_key],
            "consumed_training_observations": consumed_observations,
            "artifacts": artifacts,
            "photoreal_acceptance_authority": False,
            "human_visual_acceptance_required": True,
            "production_activation": False,
        }
        (output / "teacher-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "format": MANIFEST_FORMAT,
                    "version": VERSION,
                    "training_complete": True,
                    "consumed_source": source_key,
                    "consumed_observation_count": len(consumed_observations),
                    "artifact_count": len(artifacts),
                    "smplx_gender": workspace["smplx_gender"],
                    "runtime_preflight_sha256": runtime_preflight["runtime_preflight_sha256"],
                    "training_mode": training_mode,
                    "photoreal_acceptance_authority": False,
                    "production_activation": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    except ExAvatarTeacherAdapterError as exc:
        print(f"BodyRig ExAvatar teacher adapter: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

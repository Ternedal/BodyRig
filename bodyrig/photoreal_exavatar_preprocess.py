from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

WORKSPACE_FORMAT = "bodyrig-photoreal-exavatar-workspace"
STATE_FORMAT = "bodyrig-photoreal-exavatar-preprocess-state"
PLAN_FORMAT = "bodyrig-photoreal-exavatar-preprocess-plan"
FIT_PUBLISH_JOURNAL_FORMAT = "bodyrig-photoreal-exavatar-smplx-fit-publish"
FIT_PUBLISH_ENTRIES = ("smplx_optimized", "smplx_optimized.mp4")
UNWRAP_PUBLISH_ENTRIES = ("face_texture.png", "face_texture_mask.png")
VERSION = 1


class PhotorealExAvatarPreprocessError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarPreprocessError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealExAvatarPreprocessError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealExAvatarPreprocessError(f"{label} is invalid")
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


def _workspace(root: Path) -> dict[str, Any]:
    receipt = _read_json(root / "workspace-receipt.json", label="ExAvatar workspace receipt")
    if receipt.get("format") != WORKSPACE_FORMAT or receipt.get("version") != VERSION:
        raise PhotorealExAvatarPreprocessError("ExAvatar workspace receipt format/version mismatch")
    if receipt.get("dataset") != "Custom" or receipt.get("smplx_gender_explicit") is not True:
        raise PhotorealExAvatarPreprocessError("ExAvatar workspace config authority is invalid")
    if receipt.get("upstream_default_gender_accepted") is not False:
        raise PhotorealExAvatarPreprocessError("ExAvatar workspace accepted upstream gender default")
    if receipt.get("held_out_evaluation_disclosed") is not False or receipt.get("original_video_copied") is not False:
        raise PhotorealExAvatarPreprocessError("ExAvatar workspace disclosed forbidden source/eval data")
    if receipt.get("dependency_root_modified") is not False:
        raise PhotorealExAvatarPreprocessError("ExAvatar workspace dependency-root integrity failed")
    if receipt.get("photoreal_acceptance_authority") is not False or receipt.get("production_activation") is not False:
        raise PhotorealExAvatarPreprocessError("ExAvatar workspace crossed downstream authority")
    declared = _sha(receipt.get("workspace_sha256"), label="workspace SHA-256")
    if _digest(receipt, omit="workspace_sha256") != declared:
        raise PhotorealExAvatarPreprocessError("ExAvatar workspace digest mismatch")
    return receipt


def _frame_indices(dataset: Path, expected_count: int) -> list[int]:
    path = dataset / "frame_list_train.txt"
    if not path.is_file():
        raise PhotorealExAvatarPreprocessError("ExAvatar training frame list is missing")
    try:
        values = [int(line.strip()) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except ValueError as exc:
        raise PhotorealExAvatarPreprocessError("ExAvatar training frame list is invalid") from exc
    if len(values) != expected_count or values != list(range(expected_count)):
        raise PhotorealExAvatarPreprocessError("ExAvatar training frame list is not the exact materialized frame set")
    return values


def build_preprocess_plan(*, workspace_root: str | Path, camera_mode: str, python_executable: str) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise PhotorealExAvatarPreprocessError(f"ExAvatar workspace not found: {root}")
    receipt = _workspace(root)
    mode = str(camera_mode or "").strip().lower()
    if mode not in {"colmap", "virtual"}:
        raise PhotorealExAvatarPreprocessError("camera_mode must be explicitly colmap or virtual")
    python = str(python_executable or "").strip()
    if not python or "\n" in python or "\r" in python:
        raise PhotorealExAvatarPreprocessError("python_executable is invalid")
    subject = str(receipt.get("subject_id") or "").strip()
    dataset = root / str(receipt.get("working_dataset_relative_path") or "")
    if not dataset.is_dir():
        raise PhotorealExAvatarPreprocessError("ExAvatar workspace dataset is missing")
    frame_count = int(receipt.get("frame_count") or 0)
    frames = _frame_indices(dataset, frame_count)

    stages: list[dict[str, Any]] = [
        {"name": "camera", "camera_mode": mode},
        {"name": "wholebody-keypoints"},
        {"name": "deca-flame"},
        {"name": "hand4whole-smplx-init"},
        {"name": "smplx-fit"},
        {"name": "face-texture-unwrap"},
        {"name": "smplx-smooth"},
        {"name": "sam-masks"},
    ]
    if mode == "virtual":
        stages.append({"name": "background-depth"})
    else:
        stages.append({"name": "background-colmap", "execution": "camera-stage-output"})

    plan: dict[str, Any] = {
        "format": PLAN_FORMAT,
        "version": VERSION,
        "workspace_sha256": receipt["workspace_sha256"],
        "subject_id": subject,
        "smplx_gender": receipt["smplx_gender"],
        "camera_mode": mode,
        "python_executable": python,
        "frame_count": frame_count,
        "frame_indices": frames,
        "stages": stages,
        "held_out_evaluation_disclosed": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "production_activation": False,
    }
    plan["preprocess_plan_sha256"] = _digest(plan, omit="preprocess_plan_sha256")
    return plan


def _stage_env(python_executable: str) -> dict[str, str]:
    executable = Path(python_executable).expanduser()
    if not executable.is_absolute():
        raise PhotorealExAvatarPreprocessError(
            "ExAvatar preprocess stage Python executable must be absolute"
        )
    bin_dir = executable.parent
    env = os.environ.copy()
    inherited_path = env.get("PATH", "")
    env["PATH"] = str(bin_dir) + (os.pathsep + inherited_path if inherited_path else "")
    venv_root = bin_dir.parent
    if (venv_root / "pyvenv.cfg").is_file():
        env["VIRTUAL_ENV"] = str(venv_root)
    env["PYTHONNOUSERSITE"] = "1"
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["PYOPENGL_PLATFORM"] = "egl"
    return env


def _run_stage(argv: list[str], *, cwd: Path, log_path: Path, label: str) -> None:
    if not argv:
        raise PhotorealExAvatarPreprocessError(f"{label} command is empty")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = _stage_env(argv[0])
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
        raise PhotorealExAvatarPreprocessError(f"{label} could not start: {exc}") from exc
    if completed.returncode != 0:
        try:
            tail = log_path.read_bytes()[-8000:].decode("utf-8", errors="replace").strip()
        except OSError:
            tail = ""
        raise PhotorealExAvatarPreprocessError(
            f"{label} failed with exit code {completed.returncode}" + (f": {tail}" if tail else "")
        )


def _require_files(paths: list[Path], *, label: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file() or path.stat().st_size < 1:
            raise PhotorealExAvatarPreprocessError(f"{label} output missing: {path}")
        records.append({"path": path.as_posix(), "size_bytes": path.stat().st_size, "sha256": _file_sha(path)})
    return records


def _fit_publish_journal_path(dataset: Path) -> Path:
    return dataset / ".bodyrig-smplx-fit-publish.json"


def _validate_fit_publish_entries(entries: object) -> list[str]:
    if not isinstance(entries, list) or not entries:
        raise PhotorealExAvatarPreprocessError("SMPL-X fit publish journal entries are invalid")
    normalized: list[str] = []
    for raw in entries:
        if not isinstance(raw, str) or not raw or raw in {".", ".."} or "/" in raw or "\\" in raw:
            raise PhotorealExAvatarPreprocessError("SMPL-X fit publish journal contains unsafe entry")
        if Path(raw).name != raw or raw in normalized:
            raise PhotorealExAvatarPreprocessError("SMPL-X fit publish journal contains unsafe entry")
        normalized.append(raw)
    if set(normalized) != set(FIT_PUBLISH_ENTRIES) or len(normalized) != len(FIT_PUBLISH_ENTRIES):
        raise PhotorealExAvatarPreprocessError("SMPL-X fit publish journal contains unexpected output set")
    return sorted(normalized)


def _write_fit_publish_journal(dataset: Path, entries: list[str]) -> Path:
    names = _validate_fit_publish_entries(entries)
    journal = _fit_publish_journal_path(dataset)
    temp = journal.with_name(journal.name + ".tmp")
    if journal.exists() or journal.is_symlink():
        raise PhotorealExAvatarPreprocessError("SMPL-X fit publish journal already exists")
    if temp.is_symlink():
        raise PhotorealExAvatarPreprocessError("SMPL-X fit publish journal temp may not be a symlink")
    if temp.exists():
        if not temp.is_file():
            raise PhotorealExAvatarPreprocessError("SMPL-X fit publish journal temp is not a regular file")
        temp.unlink()
    value: dict[str, Any] = {
        "format": FIT_PUBLISH_JOURNAL_FORMAT,
        "version": VERSION,
        "entries": names,
    }
    value["journal_sha256"] = _digest(value, omit="journal_sha256")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(journal)
    return journal


def _read_fit_publish_journal(dataset: Path) -> list[str]:
    journal = _fit_publish_journal_path(dataset)
    if journal.is_symlink():
        raise PhotorealExAvatarPreprocessError("SMPL-X fit publish journal may not be a symlink")
    value = _read_json(journal, label="SMPL-X fit publish journal")
    if set(value) != {"format", "version", "entries", "journal_sha256"}:
        raise PhotorealExAvatarPreprocessError("SMPL-X fit publish journal shape is invalid")
    if value.get("format") != FIT_PUBLISH_JOURNAL_FORMAT or value.get("version") != VERSION:
        raise PhotorealExAvatarPreprocessError("SMPL-X fit publish journal format/version mismatch")
    claimed = _sha(value.get("journal_sha256"), label="SMPL-X fit publish journal SHA-256")
    if _digest(value, omit="journal_sha256") != claimed:
        raise PhotorealExAvatarPreprocessError("SMPL-X fit publish journal digest mismatch")
    return _validate_fit_publish_entries(value.get("entries"))


def _remove_uncommitted_fit_target(path: Path) -> None:
    if path.is_symlink():
        raise PhotorealExAvatarPreprocessError(f"uncommitted SMPL-X fit target may not be a symlink: {path}")
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    if path.is_file():
        path.unlink()
        return
    raise PhotorealExAvatarPreprocessError(f"uncommitted SMPL-X fit target is not regular: {path}")


def _recover_interrupted_fit_publication(source: Path, dataset: Path) -> bool:
    journal = _fit_publish_journal_path(dataset)
    if not journal.exists() and not journal.is_symlink():
        return False
    entries = _read_fit_publish_journal(dataset)
    for name in entries:
        _remove_uncommitted_fit_target(dataset / name)
    _clear_uncommitted_directory(source, label="SMPL-X fit output")
    journal.unlink()
    return True


def _finalize_fit_publish_journal(dataset: Path) -> bool:
    journal = _fit_publish_journal_path(dataset)
    if not journal.exists() and not journal.is_symlink():
        return False
    _read_fit_publish_journal(dataset)
    journal.unlink()
    return True


def _move_fit_outputs(source: Path, dataset: Path) -> Path:
    if source.is_symlink() or not source.is_dir():
        raise PhotorealExAvatarPreprocessError(f"SMPL-X fit output directory missing or unsafe: {source}")
    children = sorted(source.iterdir(), key=lambda child: child.name)
    entries = _validate_fit_publish_entries([child.name for child in children])
    for child in children:
        if child.is_symlink() or not (child.is_file() or child.is_dir()):
            raise PhotorealExAvatarPreprocessError(f"SMPL-X fit output is not regular: {child}")
        target = dataset / child.name
        if target.exists() or target.is_symlink():
            raise PhotorealExAvatarPreprocessError(f"SMPL-X fit output collides with dataset path: {target}")

    journal = _write_fit_publish_journal(dataset, entries)
    for child in children:
        shutil.move(str(child), str(dataset / child.name))
    return journal


def _clear_uncommitted_directory(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise PhotorealExAvatarPreprocessError(f"uncommitted {label} may not be a symlink: {path}")
    if not path.exists():
        return
    if not path.is_dir():
        raise PhotorealExAvatarPreprocessError(f"uncommitted {label} is not a directory: {path}")
    shutil.rmtree(path)


def _clear_uncommitted_file(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise PhotorealExAvatarPreprocessError(f"uncommitted {label} may not be a symlink: {path}")
    if not path.exists():
        return
    if not path.is_file():
        raise PhotorealExAvatarPreprocessError(f"uncommitted {label} is not a regular file: {path}")
    path.unlink()


def _clear_uncommitted_stage_outputs(
    *,
    directories: list[Path] | tuple[Path, ...] = (),
    files: list[Path] | tuple[Path, ...] = (),
    label: str,
) -> None:
    for path in directories:
        _clear_uncommitted_directory(path, label=f"{label} directory")
    for path in files:
        _clear_uncommitted_file(path, label=f"{label} file")


def _copy_unwrapped(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise PhotorealExAvatarPreprocessError("ExAvatar unwrapped texture output is missing or unsafe")
    children = sorted(source.iterdir(), key=lambda child: child.name)
    names = [child.name for child in children]
    if names != sorted(UNWRAP_PUBLISH_ENTRIES):
        raise PhotorealExAvatarPreprocessError("ExAvatar unwrapped texture output set is not pinned upstream output")
    for child in children:
        if child.is_symlink() or not child.is_file():
            raise PhotorealExAvatarPreprocessError(f"ExAvatar unwrapped texture output is not a regular file: {child}")
        destination = target / child.name
        if destination.exists() or destination.is_symlink():
            raise PhotorealExAvatarPreprocessError(f"unwrapped texture destination already exists: {destination}")
    target.mkdir(parents=True, exist_ok=True)
    for child in children:
        shutil.move(str(child), str(target / child.name))


def _state_path(root: Path) -> Path:
    return root / "preprocess-state.json"


def _validate_completed_stage_outputs(root: Path, state: Mapping[str, Any]) -> None:
    completed = state.get("completed_stages")
    if not isinstance(completed, list):
        raise PhotorealExAvatarPreprocessError("ExAvatar preprocess state completed_stages is invalid")
    workspace_root = root.resolve()
    for stage in completed:
        if not isinstance(stage, Mapping):
            raise PhotorealExAvatarPreprocessError("ExAvatar preprocess completed stage entry is invalid")
        name = str(stage.get("name") or "").strip()
        outputs = stage.get("outputs")
        if not name or not isinstance(outputs, list) or not outputs:
            raise PhotorealExAvatarPreprocessError("ExAvatar preprocess completed stage output provenance is invalid")
        for raw in outputs:
            if not isinstance(raw, Mapping) or set(raw) != {"path", "size_bytes", "sha256"}:
                raise PhotorealExAvatarPreprocessError(
                    f"ExAvatar preprocess completed stage output record is invalid: {name}"
                )
            path_value = raw.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                raise PhotorealExAvatarPreprocessError(
                    f"ExAvatar preprocess completed stage output path is invalid: {name}"
                )
            path = Path(path_value)
            if not path.is_absolute() or path.is_symlink():
                raise PhotorealExAvatarPreprocessError(
                    f"ExAvatar preprocess completed stage output path is unsafe: {name}"
                )
            resolved = path.resolve()
            try:
                resolved.relative_to(workspace_root)
            except ValueError as exc:
                raise PhotorealExAvatarPreprocessError(
                    f"ExAvatar preprocess completed stage output escapes workspace: {name}"
                ) from exc
            declared_size = raw.get("size_bytes")
            if (
                isinstance(declared_size, bool)
                or not isinstance(declared_size, int)
                or declared_size < 1
                or not resolved.is_file()
                or resolved.stat().st_size != declared_size
            ):
                raise PhotorealExAvatarPreprocessError(
                    f"ExAvatar preprocess completed stage output size/path drifted: {name}"
                )
            expected_sha = _sha(raw.get("sha256"), label=f"{name} output SHA-256")
            if _file_sha(resolved) != expected_sha:
                raise PhotorealExAvatarPreprocessError(
                    f"ExAvatar preprocess completed stage output SHA-256 drifted: {name}"
                )


def _load_state(root: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    path = _state_path(root)
    if not path.exists():
        return {
            "format": STATE_FORMAT,
            "version": VERSION,
            "preprocess_plan_sha256": plan["preprocess_plan_sha256"],
            "workspace_sha256": plan["workspace_sha256"],
            "completed_stages": [],
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }
    state = _read_json(path, label="ExAvatar preprocess state")
    if state.get("format") != STATE_FORMAT or state.get("version") != VERSION:
        raise PhotorealExAvatarPreprocessError("ExAvatar preprocess state format/version mismatch")
    if state.get("preprocess_plan_sha256") != plan["preprocess_plan_sha256"] or state.get("workspace_sha256") != plan["workspace_sha256"]:
        raise PhotorealExAvatarPreprocessError("ExAvatar preprocess state belongs to different plan/workspace")
    if state.get("photoreal_acceptance_authority") is not False or state.get("production_activation") is not False:
        raise PhotorealExAvatarPreprocessError("ExAvatar preprocess state crossed downstream authority")
    if not isinstance(state.get("completed_stages"), list):
        raise PhotorealExAvatarPreprocessError("ExAvatar preprocess state completed_stages is invalid")
    if "preprocess_state_sha256" in state:
        claimed = _sha(state.get("preprocess_state_sha256"), label="preprocess state SHA-256")
        if _digest(state, omit="preprocess_state_sha256") != claimed:
            raise PhotorealExAvatarPreprocessError("ExAvatar preprocess state digest mismatch")
    _validate_completed_stage_outputs(root, state)
    return state


def _write_state(root: Path, state: Mapping[str, Any]) -> None:
    path = _state_path(root)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(dict(state), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def _mark_stage(root: Path, state: dict[str, Any], *, name: str, outputs: list[dict[str, Any]]) -> None:
    completed = list(state["completed_stages"])
    completed.append({"name": name, "outputs": outputs})
    state["completed_stages"] = completed
    _write_state(root, state)


def run_preprocess(*, workspace_root: str | Path, camera_mode: str, python_executable: str) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    plan = build_preprocess_plan(workspace_root=root, camera_mode=camera_mode, python_executable=python_executable)
    state = _load_state(root, plan)
    done = [str(item.get("name")) for item in state["completed_stages"] if isinstance(item, Mapping)]
    expected_prefix = [str(item["name"]) for item in plan["stages"][: len(done)]]
    if done != expected_prefix:
        raise PhotorealExAvatarPreprocessError("ExAvatar preprocess state is not a valid stage prefix")

    exavatar = root / "repos" / "ExAvatar_RELEASE"
    dataset = root / str(_workspace(root)["working_dataset_relative_path"])
    subject = plan["subject_id"]
    frames = list(plan["frame_indices"])
    python = plan["python_executable"]
    logs = root / "logs" / "preprocess"

    def already(name: str) -> bool:
        return name in done

    if already("smplx-fit"):
        _finalize_fit_publish_journal(dataset)

    if not already("camera"):
        if plan["camera_mode"] == "colmap":
            _clear_uncommitted_stage_outputs(
                directories=(dataset / "sparse",),
                label="COLMAP camera",
            )
            cwd = exavatar / "fitting" / "tools" / "COLMAP"
            _run_stage([python, "run_colmap.py", "--root_path", str(dataset)], cwd=cwd, log_path=logs / "01-camera-colmap.log", label="ExAvatar COLMAP camera stage")
            outputs = _require_files(
                [dataset / "sparse" / "cameras.txt", dataset / "sparse" / "images.txt", dataset / "sparse" / "points3D.txt"],
                label="COLMAP camera",
            )
        else:
            _clear_uncommitted_stage_outputs(
                directories=(dataset / "cam_params",),
                label="virtual camera",
            )
            cwd = exavatar / "fitting" / "tools"
            _run_stage([python, "make_virtual_cam_params.py", "--root_path", str(dataset)], cwd=cwd, log_path=logs / "01-camera-virtual.log", label="ExAvatar virtual camera stage")
            outputs = _require_files([dataset / "cam_params" / f"{index}.json" for index in frames], label="virtual camera")
        _mark_stage(root, state, name="camera", outputs=outputs)
        done.append("camera")

    if not already("wholebody-keypoints"):
        _clear_uncommitted_stage_outputs(
            directories=(dataset / "keypoints_whole_body",),
            files=(dataset / "keypoints_whole_body.mp4",),
            label="whole-body keypoints",
        )
        cwd = exavatar / "fitting" / "tools" / "mmpose"
        _run_stage([python, "run_mmpose.py", "--root_path", str(dataset)], cwd=cwd, log_path=logs / "02-wholebody-keypoints.log", label="ExAvatar whole-body keypoint stage")
        outputs = _require_files([dataset / "keypoints_whole_body" / f"{index}.json" for index in frames], label="whole-body keypoints")
        _mark_stage(root, state, name="wholebody-keypoints", outputs=outputs)
        done.append("wholebody-keypoints")

    if not already("deca-flame"):
        _clear_uncommitted_stage_outputs(
            directories=(dataset / "flame_init",),
            label="DECA/FLAME",
        )
        cwd = exavatar / "fitting" / "tools" / "DECA"
        _run_stage([python, "run_deca.py", "--root_path", str(dataset)], cwd=cwd, log_path=logs / "03-deca-flame.log", label="ExAvatar DECA/FLAME stage")
        outputs = _require_files(
            [dataset / "flame_init" / "shape_param.json", *[dataset / "flame_init" / "flame_params" / f"{index}.json" for index in frames]],
            label="DECA/FLAME",
        )
        _mark_stage(root, state, name="deca-flame", outputs=outputs)
        done.append("deca-flame")

    if not already("hand4whole-smplx-init"):
        _clear_uncommitted_stage_outputs(
            directories=(dataset / "smplx_init",),
            files=(dataset / "smplx_init.mp4",),
            label="Hand4Whole SMPL-X init",
        )
        cwd = exavatar / "fitting" / "tools" / "Hand4Whole_RELEASE" / "demo"
        _run_stage([python, "run_hand4whole.py", "--gpu", "0", "--root_path", str(dataset)], cwd=cwd, log_path=logs / "04-hand4whole.log", label="ExAvatar Hand4Whole stage")
        outputs = _require_files([dataset / "smplx_init" / f"{index}.json" for index in frames], label="Hand4Whole SMPL-X init")
        _mark_stage(root, state, name="hand4whole-smplx-init", outputs=outputs)
        done.append("hand4whole-smplx-init")

    if not already("smplx-fit"):
        cwd = exavatar / "fitting" / "main"
        result_root = exavatar / "fitting" / "output" / "result" / subject
        _recover_interrupted_fit_publication(result_root, dataset)
        _clear_uncommitted_directory(result_root, label="SMPL-X fit output")
        _run_stage([python, "fit.py", "--subject_id", subject], cwd=cwd, log_path=logs / "05-smplx-fit.log", label="ExAvatar SMPL-X fit stage")
        _move_fit_outputs(result_root, dataset)
        optimized = dataset / "smplx_optimized"
        outputs = _require_files(
            [
                optimized / "shape_param.json",
                optimized / "face_offset.json",
                optimized / "joint_offset.json",
                optimized / "locator_offset.json",
                *[optimized / "smplx_params" / f"{index}.json" for index in frames],
            ],
            label="SMPL-X fit",
        )
        _mark_stage(root, state, name="smplx-fit", outputs=outputs)
        _finalize_fit_publish_journal(dataset)
        done.append("smplx-fit")

    if not already("face-texture-unwrap"):
        cwd = exavatar / "fitting" / "main"
        unwrap = exavatar / "fitting" / "output" / "result" / subject / "unwrapped_textures"
        optimized = dataset / "smplx_optimized"
        _clear_uncommitted_directory(unwrap, label="face-texture scratch output")
        _clear_uncommitted_file(optimized / "face_texture.png", label="face texture output")
        _clear_uncommitted_file(optimized / "face_texture_mask.png", label="face texture mask output")
        _run_stage([python, "unwrap.py", "--subject_id", subject], cwd=cwd, log_path=logs / "06-face-texture-unwrap.log", label="ExAvatar face texture unwrap stage")
        _copy_unwrapped(unwrap, optimized)
        outputs = _require_files([optimized / "face_texture.png", optimized / "face_texture_mask.png"], label="face texture unwrap")
        _mark_stage(root, state, name="face-texture-unwrap", outputs=outputs)
        done.append("face-texture-unwrap")

    if not already("smplx-smooth"):
        optimized = dataset / "smplx_optimized"
        _clear_uncommitted_stage_outputs(
            directories=(
                optimized / "smplx_params_smoothed",
                optimized / "meshes_smoothed",
                optimized / "renders_smoothed",
            ),
            files=(dataset / "smplx_optimized_smoothed.mp4",),
            label="SMPL-X smoothing",
        )
        cwd = exavatar / "fitting" / "tools"
        _run_stage([python, "smooth_smplx_params.py", "--root_path", str(dataset)], cwd=cwd, log_path=logs / "07-smplx-smooth.log", label="ExAvatar SMPL-X smoothing stage")
        outputs = _require_files(
            [
                *[optimized / "smplx_params_smoothed" / f"{index}.json" for index in frames],
                *[optimized / "meshes_smoothed" / f"{index}_smplx.ply" for index in frames],
            ],
            label="SMPL-X smoothing",
        )
        _mark_stage(root, state, name="smplx-smooth", outputs=outputs)
        done.append("smplx-smooth")

    if not already("sam-masks"):
        _clear_uncommitted_stage_outputs(
            directories=(dataset / "masks",),
            files=(dataset / "masks.mp4",),
            label="SAM masks",
        )
        cwd = exavatar / "fitting" / "tools" / "segment-anything"
        _run_stage([python, "run_sam.py", "--root_path", str(dataset)], cwd=cwd, log_path=logs / "08-sam-masks.log", label="ExAvatar SAM mask stage")
        outputs = _require_files([dataset / "masks" / f"{index}.png" for index in frames], label="SAM masks")
        _mark_stage(root, state, name="sam-masks", outputs=outputs)
        done.append("sam-masks")

    if plan["camera_mode"] == "virtual" and not already("background-depth"):
        _clear_uncommitted_stage_outputs(
            directories=(dataset / "depthmaps",),
            files=(dataset / "depthmaps.mp4", dataset / "bkg_point_cloud.txt"),
            label="background depth",
        )
        cwd = exavatar / "fitting" / "tools" / "Depth-Anything-V2"
        _run_stage([python, "run_depth_anything.py", "--root_path", str(dataset)], cwd=cwd, log_path=logs / "09-background-depth.log", label="ExAvatar background depth stage")
        outputs = _require_files([dataset / "bkg_point_cloud.txt"], label="background depth")
        _mark_stage(root, state, name="background-depth", outputs=outputs)
        done.append("background-depth")
    elif plan["camera_mode"] == "colmap" and not already("background-colmap"):
        outputs = _require_files([dataset / "sparse" / "points3D.txt"], label="COLMAP background")
        _mark_stage(root, state, name="background-colmap", outputs=outputs)
        done.append("background-colmap")

    completed_names = [str(item.get("name")) for item in state["completed_stages"] if isinstance(item, Mapping)]
    expected_names = [str(item["name"]) for item in plan["stages"]]
    if completed_names != expected_names:
        raise PhotorealExAvatarPreprocessError("ExAvatar preprocessing did not complete the exact stage plan")
    state["preprocessing_complete"] = True
    state["teacher_training_authorized_by_preprocessing"] = False
    state["photoreal_acceptance_authority"] = False
    state["human_visual_acceptance_required"] = True
    state["production_activation"] = False
    state["preprocess_state_sha256"] = _digest(state, omit="preprocess_state_sha256")
    _write_state(root, state)
    return state

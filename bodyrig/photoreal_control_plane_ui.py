from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .operator_launch import OperatorLaunchError, launch_canonical_operator
from .photoreal_calibration_ui import find_latest_performer_run, list_performer_runs
from .photoreal_v2_operator_status import (
    PhotorealV2OperatorStatusError,
    inspect_photoreal_v2_status,
)
from .storage import data_dir, person_library


class PhotorealControlPlaneError(RuntimeError):
    pass


_ALLOWED_INPUTS = {
    "asset_root",
    "reference_model_root",
    "smplx_gender",
    "camera_mode",
    "setup_public_code",
    "setup_runtime",
    "p2_motion_config",
    "p2_review_selection_input",
    "single_motion_driver_source_ref",
    "reviewed_by",
    "review_notes",
    "p3_target_profile",
    "p3_machine_probe",
    "assembly_receipt",
    "body_release_status",
    "photoreal_person_binding_output",
}
_BOOL_INPUTS = {"setup_public_code", "setup_runtime"}
_PROCESS_MARKERS = (
    "photoreal_exavatar_preprocess_cli",
    "run_colmap.py",
    "make_virtual_cam_params.py",
    "run_mmpose.py",
    "run_deca.py",
    "run_hand4whole.py",
    "fit.py",
    "unwrap.py",
    "smooth_smplx_params.py",
    "run_sam.py",
    "run_depth_anything.py",
    "train.py",
    "get_neutral_pose.py",
)


def _operator_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _profile_performer(profile: Mapping[str, Any]) -> tuple[str, str]:
    source = profile.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "stash-performer":
        raise PhotorealControlPlaneError(
            "Personen er ikke bundet til en Stash performer"
        )
    performer_id = str(source.get("performer_id") or "").strip()
    if not performer_id:
        raise PhotorealControlPlaneError(
            "Person Stash performer binding has no performer id"
        )
    return performer_id, str(source.get("performer_name") or "").strip()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _flag_value(command: list[Any], flag: str) -> str | None:
    values = [str(item) for item in command]
    try:
        index = values.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(values):
        return None
    value = values[index + 1].strip()
    return value or None


def _teacher_transport(teacher_root: Path) -> dict[str, str] | None:
    config = _read_json(teacher_root / "exavatar-teacher-config.json")
    if config is not None:
        command = config.get("command")
        if isinstance(command, list):
            workspace = _flag_value(command, "--workspace-root")
            distribution = _flag_value(command, "--distribution")
            wsl_exe = _flag_value(command, "--wsl-exe")
            linux_python = _flag_value(command, "--linux-python")
            if all((workspace, distribution, wsl_exe, linux_python)):
                return {
                    "workspace": str(workspace),
                    "distribution": str(distribution),
                    "wsl_exe": str(wsl_exe),
                    "linux_python": str(linux_python),
                    "source": "teacher-config",
                }

    # Before stage 7 the teacher config does not exist yet. The canonical
    # operator's default workspace is nevertheless deterministic from the
    # already-authoritative teacher input. This fallback is monitoring-only;
    # it never becomes execution authority.
    teacher_input = _read_json(teacher_root / "teacher-input.json")
    if teacher_input is None:
        return None
    performer_id = str(teacher_input.get("performer_id") or "").strip()
    teacher_sha = str(teacher_input.get("teacher_input_sha256") or "").strip().lower()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", performer_id).strip("-_.")
    if (
        not safe
        or len(teacher_sha) != 64
        or any(ch not in "0123456789abcdef" for ch in teacher_sha)
    ):
        return None
    return {
        "workspace": f"/opt/bodyrig-exavatar/workspaces/bodyrig-{safe}-{teacher_sha[:12]}",
        "distribution": "Ubuntu-22.04",
        "wsl_exe": shutil.which("wsl.exe") or "wsl.exe",
        "linux_python": "/opt/bodyrig-exavatar/bin/python",
        "source": "canonical-default-derived",
    }


def _run_readonly(
    argv: list[str],
    *,
    timeout: float = 5.0,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PhotorealControlPlaneError(str(exc)) from exc


_PROBE_SCRIPT = r"""
import json, os, re, sys
from pathlib import Path

root = Path(sys.argv[1])
def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None

workspace = read_json(root / "workspace-receipt.json") or {}
state = read_json(root / "preprocess-state.json") or {}
subject = str(workspace.get("subject_id") or "")
completed = []
for item in state.get("completed_stages") or []:
    if isinstance(item, dict):
        name = str(item.get("name") or "").strip()
        if name:
            completed.append(name)

model_dir = (
    root / "repos" / "ExAvatar_RELEASE" / "avatar" / "output" / "model_dump" / subject
)
epochs = []
if model_dir.is_dir():
    for path in model_dir.glob("snapshot_*.pth"):
        match = re.fullmatch(r"snapshot_(\d+)\.pth", path.name)
        if match and path.is_file() and path.stat().st_size > 0:
            epochs.append(int(match.group(1)))
epochs = sorted(set(epochs))

neutral = root / "repos" / "ExAvatar_RELEASE" / "avatar" / "main" / "neutral_pose"
neutral_count = sum(
    1 for index in range(50)
    if (neutral / f"{index}.png").is_file()
    and (neutral / f"{index}.png").stat().st_size > 0
)

logs = []
for pattern in ("logs/preprocess/*.log", "logs/teacher/*.log"):
    for path in root.glob(pattern):
        try:
            stat = path.stat()
        except OSError:
            continue
        logs.append((stat.st_mtime, stat.st_size, path))
logs.sort(key=lambda item: item[0])
latest = None
if logs:
    mtime, size, path = logs[-1]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    latest = {
        "name": path.name,
        "modified_unix": mtime,
        "size_bytes": size,
        "tail": "\n".join(text.splitlines()[-20:])[-6000:],
    }

active = []
root_text = str(root.resolve())
for proc in Path("/proc").iterdir():
    if not proc.name.isdigit():
        continue
    try:
        cwd = os.readlink(proc / "cwd")
        raw = (proc / "cmdline").read_bytes()
    except (OSError, PermissionError):
        continue
    if cwd != root_text and not cwd.startswith(root_text.rstrip("/") + "/"):
        continue
    command = raw.replace(b"\\x00", b" ").decode("utf-8", errors="replace").strip()
    if command:
        active.append(f"{proc.name} {command}"[:1200])

print(json.dumps({
    "workspace_present": root.is_dir(),
    "subject_id": subject or None,
    "completed_stages": completed,
    "preprocessing_complete": state.get("preprocessing_complete") is True,
    "snapshot_epochs": epochs,
    "highest_snapshot_epoch": max(epochs) if epochs else None,
    "neutral_render_count": neutral_count,
    "latest_log": latest,
    "active_processes": active[:20],
}, sort_keys=True))
""".strip()


def _probe_wsl(transport: Mapping[str, str]) -> dict[str, Any]:
    completed = _run_readonly(
        [
            transport["wsl_exe"],
            "-d",
            transport["distribution"],
            "--",
            "/usr/bin/env",
            "PYTHONNOUSERSITE=1",
            transport["linux_python"],
            "-c",
            _PROBE_SCRIPT,
            transport["workspace"],
        ]
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return {
            "available": False,
            "reason": detail or f"WSL probe failed with code {completed.returncode}",
            "active_processes": [],
        }
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "available": False,
            "reason": "WSL probe returned unreadable JSON",
            "active_processes": [],
        }
    if not isinstance(value, dict):
        return {
            "available": False,
            "reason": "WSL probe returned invalid payload",
            "active_processes": [],
        }

    active = value.get("active_processes")
    if not isinstance(active, list):
        active = []
    value["available"] = True
    value["active_processes"] = [
        str(item)[:1200]
        for item in active
        if any(marker in str(item) for marker in _PROCESS_MARKERS)
    ][:20]
    return value


def _iso_from_unix(value: Any) -> str | None:
    try:
        stamp = float(value)
    except (TypeError, ValueError):
        return None
    return (
        datetime.fromtimestamp(stamp, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _live_exavatar(teacher_root: Path) -> dict[str, Any]:
    manifest = teacher_root / "exavatar-teacher-output" / "output" / "teacher-manifest.json"
    transport = _teacher_transport(teacher_root)
    if transport is None:
        return {
            "available": False,
            "phase": "not-configured",
            "message": "ExAvatar teacher config er ikke materialiseret endnu.",
            "active_processes": [],
            "busy": False,
            "teacher_manifest_present": manifest.is_file(),
        }

    try:
        live = _probe_wsl(transport)
    except PhotorealControlPlaneError as exc:
        live = {
            "available": False,
            "reason": str(exc),
            "active_processes": [],
        }
    live["linux_workspace"] = transport["workspace"]
    live["transport_source"] = transport.get("source")
    live["teacher_manifest_present"] = manifest.is_file()
    latest = live.get("latest_log")
    if isinstance(latest, dict):
        latest["modified_utc"] = _iso_from_unix(latest.get("modified_unix"))

    active = live.get("active_processes")
    active = active if isinstance(active, list) else []
    completed = live.get("completed_stages")
    completed = completed if isinstance(completed, list) else []
    highest = live.get("highest_snapshot_epoch")
    neutral_count = int(live.get("neutral_render_count") or 0)

    if manifest.is_file():
        phase = "human-review"
    elif any("get_neutral_pose.py" in item for item in active) or neutral_count > 0:
        phase = "neutral-render"
    elif any("train.py" in item for item in active) or isinstance(highest, int):
        phase = "training"
    elif live.get("preprocessing_complete") is True:
        phase = "training-ready"
    elif completed or any(
        any(marker in item for marker in _PROCESS_MARKERS[:-2])
        for item in active
    ):
        phase = "preprocess"
    else:
        phase = "workspace-ready"

    recent_log = False
    if isinstance(latest, dict):
        try:
            age = datetime.now(tz=timezone.utc).timestamp() - float(
                latest.get("modified_unix")
            )
            recent_log = 0 <= age <= 1800
        except (TypeError, ValueError):
            recent_log = False
    busy = bool(active) or (
        phase in {"preprocess", "training", "neutral-render"} and recent_log
    )

    live.update(
        {
            "phase": phase,
            "preprocess_completed_count": len(completed),
            "preprocess_total_count": 9,
            "training_target_epoch": 4,
            "busy": busy,
        }
    )
    return live


def _photoreal_run_history(
    performer_id: str,
    current_p0_root: Path | None,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    current = current_p0_root.resolve() if current_p0_root is not None else None
    values: list[dict[str, Any]] = []
    for run_root in list_performer_runs(data_dir(), performer_id, limit=limit):
        resolved = run_root.resolve()
        teacher_root = Path(str(resolved) + "-teacher").resolve()
        teacher_input_path = teacher_root / "teacher-input.json"
        teacher_config_path = teacher_root / "exavatar-teacher-config.json"
        manifest_path = teacher_root / "exavatar-teacher-output" / "output" / "teacher-manifest.json"
        calibration_path = resolved / "identity-calibration.json"

        teacher_input = _read_json(teacher_input_path)
        teacher_sha = ""
        teacher_input_valid = False
        if isinstance(teacher_input, dict):
            candidate_sha = str(teacher_input.get("teacher_input_sha256") or "").strip().lower()
            teacher_input_valid = (
                str(teacher_input.get("performer_id") or "").strip() == performer_id
                and re.fullmatch(r"[0-9a-f]{64}", candidate_sha) is not None
            )
            if teacher_input_valid:
                teacher_sha = candidate_sha

        calibration = _read_json(calibration_path)
        calibration_state = "missing"
        identity_matching_authorized = False
        if calibration is not None:
            if (
                calibration.get("format") == "bodyrig-photoreal-identity-calibration"
                and calibration.get("version") == 1
                and str(calibration.get("target_performer_id") or "").strip() == performer_id
            ):
                calibration_state = "valid"
                identity_matching_authorized = calibration.get("identity_matching_authorized") is True
            else:
                calibration_state = "invalid"

        is_current = current is not None and resolved == current
        values.append(
            {
                "name": resolved.name,
                "path": str(resolved),
                "modified_utc": _iso_from_unix(resolved.stat().st_mtime),
                "current": is_current,
                "continuation_candidate": is_current,
                "role": "current-canonical-run" if is_current else "history-only",
                "p0_status_present": (resolved / "p0-status.json").is_file(),
                "calibration_state": calibration_state,
                "identity_matching_authorized": identity_matching_authorized,
                "teacher_root": str(teacher_root),
                "teacher_root_present": teacher_root.is_dir() and not teacher_root.is_symlink(),
                "teacher_input_present": teacher_input_path.is_file() and not teacher_input_path.is_symlink(),
                "teacher_input_valid": teacher_input_valid,
                "teacher_input_sha256": teacher_sha or None,
                "teacher_config_present": teacher_config_path.is_file() and not teacher_config_path.is_symlink(),
                "teacher_manifest_present": manifest_path.is_file() and not manifest_path.is_symlink(),
                "authority": {
                    "read_only_history": True,
                    "historical_execution_authority": False,
                    "continuation_candidate": is_current,
                    "production_activation": False,
                },
            }
        )
    return values


def _normalized_inputs(values: Mapping[str, Any] | None) -> dict[str, Any]:
    if values is None:
        return {}
    unknown = sorted(set(values) - _ALLOWED_INPUTS)
    if unknown:
        raise PhotorealControlPlaneError(
            "Ukendte Photoreal operator-inputs: " + ", ".join(unknown)
        )
    result: dict[str, Any] = {}
    for key, raw in values.items():
        if key in _BOOL_INPUTS:
            if isinstance(raw, bool):
                result[key] = raw
                continue
            text = str(raw or "").strip().lower()
            if text in {"1", "true", "yes", "on"}:
                result[key] = True
            elif text in {"0", "false", "no", "off", ""}:
                result[key] = False
            else:
                raise PhotorealControlPlaneError(
                    f"{key} skal være en boolean"
                )
            continue
        text = str(raw or "").strip()
        if text:
            result[key] = text
    return result


def inspect_person_control_plane(
    profile: Mapping[str, Any],
    *,
    operator_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    performer_id, performer_name = _profile_performer(profile)
    p0_root = find_latest_performer_run(data_dir(), performer_id)
    if p0_root is None:
        return {
            "state": "no-run",
            "performer": {"id": performer_id, "name": performer_name},
            "p0_root": None,
            "pipeline": None,
            "exavatar": {
                "available": False,
                "phase": "not-started",
                "active_processes": [],
                "busy": False,
            },
            "advance_allowed": False,
            "history": [],
            "authority": {
                "read_only_status": True,
                "browser_command_authority": False,
                "canonical_backend_command_only": True,
                "production_activation": False,
            },
        }

    inputs = _normalized_inputs(operator_inputs)
    kwargs: dict[str, Any] = {
        "p0_root": p0_root,
        "operator_root": _operator_root(),
        "person_library": person_library(),
        "person_id": str(profile.get("person_id") or ""),
        **inputs,
    }
    try:
        pipeline = inspect_photoreal_v2_status(**kwargs)
    except PhotorealV2OperatorStatusError as exc:
        pipeline = {
            "state": "blocked",
            "next_gate": "status-validation",
            "next_command": None,
            "message": str(exc),
            "missing_operator_inputs": [],
            "production_activation": False,
        }

    teacher_root = Path(
        str(
            pipeline.get("teacher_work_root")
            or (str(p0_root) + "-teacher")
        )
    ).expanduser().resolve()
    exavatar = _live_exavatar(teacher_root)
    command = pipeline.get("next_command")
    advance_allowed = (
        isinstance(command, str)
        and bool(command.strip())
        and exavatar.get("busy") is not True
        and pipeline.get("state") != "complete"
    )
    return {
        "state": str(pipeline.get("state") or "unknown"),
        "performer": {"id": performer_id, "name": performer_name},
        "p0_root": str(p0_root),
        "teacher_work_root": str(teacher_root),
        "pipeline": pipeline,
        "exavatar": exavatar,
        "advance_allowed": advance_allowed,
        "history": _photoreal_run_history(performer_id, p0_root),
        "authority": {
            "read_only_status": True,
            "browser_command_authority": False,
            "canonical_backend_command_only": True,
            "production_activation": pipeline.get("production_activation") is True,
        },
    }


def advance_person_control_plane(
    profile: Mapping[str, Any],
    *,
    operator_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    status = inspect_person_control_plane(
        profile,
        operator_inputs=operator_inputs,
    )
    pipeline = status.get("pipeline")
    if not isinstance(pipeline, Mapping):
        return {"launched": False, "status": status, "reason": "Ingen pipeline-run."}
    if status.get("exavatar", {}).get("busy") is True:
        raise PhotorealControlPlaneError(
            "ExAvatar ser aktiv ud; BodyRig starter ikke en konkurrerende proces"
        )
    if status.get("advance_allowed") is not True:
        return {
            "launched": False,
            "status": status,
            "reason": str(
                pipeline.get("message")
                or "Næste canonicale handling er ikke launch-klar"
            ),
        }
    command = pipeline.get("next_command")
    if not isinstance(command, str) or not command.strip():
        raise PhotorealControlPlaneError(
            "Canonical statusmotor returnerede ingen executable next_command"
        )
    try:
        launch = launch_canonical_operator(
            command,
            category="photoreal",
            context={
                "person_id": str(profile.get("person_id") or ""),
                "gate": str(pipeline.get("next_gate") or ""),
                "p0_root": status.get("p0_root"),
            },
            cwd=_operator_root(),
        )
    except OperatorLaunchError as exc:
        raise PhotorealControlPlaneError(str(exc)) from exc
    return {"launched": True, "launch": launch, "status": status}

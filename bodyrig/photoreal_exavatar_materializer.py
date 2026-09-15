from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter

PLAN_FORMAT = "bodyrig-photoreal-teacher-benchmark-plan"
PLAN_VERSION = 1
REQUEST_FORMAT = "bodyrig-photoreal-exavatar-materialization-request"
REQUEST_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-exavatar-materialization-receipt"
RECEIPT_VERSION = 1
UPSTREAM_COMMIT = "d45268730c779fae4118f1a361cf9ff639bc4d1e"


class PhotorealExAvatarMaterializerError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarMaterializerError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealExAvatarMaterializerError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealExAvatarMaterializerError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealExAvatarMaterializerError(f"{label} is invalid")
    return result


def _canonical_digest(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "benchmark_plan_sha256"}
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_plan(plan: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise PhotorealExAvatarMaterializerError("teacher benchmark plan format/version mismatch")
    if plan.get("benchmark") != "exavatar" or plan.get("upstream_commit") != UPSTREAM_COMMIT:
        raise PhotorealExAvatarMaterializerError("teacher benchmark plan targets unsupported benchmark/upstream")
    if plan.get("benchmark_execution_authorized") is not True or plan.get("benchmark_blockers") != []:
        raise PhotorealExAvatarMaterializerError("teacher benchmark plan does not authorize materialization")
    if plan.get("selection_authority") != "core-benchmark-scheduling-only-v1":
        raise PhotorealExAvatarMaterializerError("teacher benchmark selection authority is invalid")
    if plan.get("teacher_training_authority_inherited") is not True:
        raise PhotorealExAvatarMaterializerError("teacher benchmark plan did not inherit teacher-training authority")
    if plan.get("photoreal_acceptance_authority") is not False or plan.get("human_visual_acceptance_required") is not True:
        raise PhotorealExAvatarMaterializerError("teacher benchmark plan crossed photoreal/human authority")
    if plan.get("build_only") is not True or plan.get("runtime_dependency") is not False:
        raise PhotorealExAvatarMaterializerError("teacher benchmark plan build/runtime authority boundary is invalid")
    if plan.get("production_activation") is not False:
        raise PhotorealExAvatarMaterializerError("teacher benchmark plan crossed production authority")
    declared_digest = _sha(plan.get("benchmark_plan_sha256"), label="benchmark plan SHA-256")
    if _canonical_digest(plan) != declared_digest:
        raise PhotorealExAvatarMaterializerError("teacher benchmark plan digest mismatch")

    selected_key = _text(plan.get("selected_source_key"), label="selected source key", maximum=4096)
    selected_sha = _sha(plan.get("selected_source_sha256"), label="selected source SHA-256")
    candidates = plan.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise PhotorealExAvatarMaterializerError("teacher benchmark plan contains no candidates")
    matches = [item for item in candidates if isinstance(item, Mapping) and item.get("source_key") == selected_key]
    if len(matches) != 1:
        raise PhotorealExAvatarMaterializerError("selected benchmark source is not unique in candidate list")
    selected = dict(matches[0])
    if _sha(selected.get("source_sha256"), label="candidate source SHA-256") != selected_sha:
        raise PhotorealExAvatarMaterializerError("selected benchmark source SHA differs from candidate")
    if selected.get("projection") != "flat" or selected.get("stereo_layout") != "mono":
        raise PhotorealExAvatarMaterializerError("ExAvatar benchmark materializer requires flat mono source")
    resolved_path = _text(selected.get("resolved_path"), label="selected source resolved path")

    observations = plan.get("selected_observations")
    if not isinstance(observations, list) or not observations:
        raise PhotorealExAvatarMaterializerError("teacher benchmark plan has no selected observations")
    if int(plan.get("selected_observation_count") or 0) != len(observations):
        raise PhotorealExAvatarMaterializerError("selected benchmark observation count mismatch")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, float, str]] = set()
    for raw in observations:
        if not isinstance(raw, Mapping):
            raise PhotorealExAvatarMaterializerError("selected benchmark observation is invalid")
        source_key = _text(raw.get("source_key"), label="benchmark observation source key", maximum=4096)
        if source_key != selected_key:
            raise PhotorealExAvatarMaterializerError("benchmark observation references different source")
        eye = _text(raw.get("eye"), label="benchmark observation eye", maximum=16)
        if eye != "mono":
            raise PhotorealExAvatarMaterializerError("ExAvatar materialization requires mono observations")
        timestamp_raw = raw.get("timestamp_seconds")
        if isinstance(timestamp_raw, bool) or not isinstance(timestamp_raw, (int, float)) or float(timestamp_raw) < 0:
            raise PhotorealExAvatarMaterializerError("benchmark observation timestamp is invalid")
        timestamp = round(float(timestamp_raw), 6)
        frame_sha = _sha(raw.get("frame_sha256"), label="benchmark observation frame SHA-256")
        key = (frame_sha, timestamp, eye)
        if key in seen:
            raise PhotorealExAvatarMaterializerError("benchmark plan repeats selected observation")
        seen.add(key)
        normalized.append(
            {
                "source_key": source_key,
                "frame_sha256": frame_sha,
                "timestamp_seconds": timestamp,
                "eye": eye,
            }
        )
    normalized.sort(key=lambda item: (item["timestamp_seconds"], item["frame_sha256"]))
    selected["resolved_path"] = resolved_path
    return selected, normalized


def _build_request(plan: Mapping[str, Any], selected: Mapping[str, Any], observations: list[dict[str, Any]], linux_source_path: str) -> dict[str, Any]:
    if not linux_source_path.startswith("/"):
        raise PhotorealExAvatarMaterializerError("translated source path is not absolute Linux path")
    return {
        "format": REQUEST_FORMAT,
        "version": REQUEST_VERSION,
        "benchmark_plan_sha256": _sha(plan.get("benchmark_plan_sha256"), label="benchmark plan SHA-256"),
        "teacher_input_sha256": _sha(plan.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "performer_id": _text(plan.get("performer_id"), label="performer id", maximum=256),
        "selected_epoch_id": _text(plan.get("selected_epoch_id"), label="selected epoch id", maximum=256),
        "upstream_commit": UPSTREAM_COMMIT,
        "source": {
            "source_key": selected["source_key"],
            "source_sha256": selected["source_sha256"],
            "resolved_path": linux_source_path,
            "projection": "flat",
            "stereo_layout": "mono",
        },
        "observations": observations,
        "held_out_evaluation_disclosed": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }


def _validate_receipt(receipt: Mapping[str, Any], *, request: Mapping[str, Any], dataset_dir: Path) -> dict[str, Any]:
    if receipt.get("format") != RECEIPT_FORMAT or receipt.get("version") != RECEIPT_VERSION:
        raise PhotorealExAvatarMaterializerError("ExAvatar materialization receipt format/version mismatch")
    for field in ("benchmark_plan_sha256", "teacher_input_sha256", "performer_id", "selected_epoch_id", "upstream_commit"):
        if receipt.get(field) != request.get(field):
            raise PhotorealExAvatarMaterializerError(f"ExAvatar materialization receipt provenance mismatch: {field}")
    source = request["source"]
    if receipt.get("source_key") != source["source_key"] or receipt.get("source_sha256") != source["source_sha256"]:
        raise PhotorealExAvatarMaterializerError("ExAvatar materialization receipt source provenance mismatch")
    if receipt.get("held_out_evaluation_disclosed") is not False or receipt.get("original_video_copied") is not False:
        raise PhotorealExAvatarMaterializerError("ExAvatar materialization disclosed forbidden source/evaluation data")
    if receipt.get("photoreal_acceptance_authority") is not False or receipt.get("production_activation") is not False:
        raise PhotorealExAvatarMaterializerError("ExAvatar materialization crossed downstream authority")

    mappings = receipt.get("frames")
    observations = request["observations"]
    if not isinstance(mappings, list) or len(mappings) != len(observations):
        raise PhotorealExAvatarMaterializerError("ExAvatar materialization frame cardinality mismatch")
    expected_by_index = {index: observation for index, observation in enumerate(observations)}
    listed_files: set[str] = {"frame_list_all.txt", "frame_list_train.txt", "frame_list_test.txt", "bodyrig-source-map.json"}
    normalized_frames: list[dict[str, Any]] = []
    for raw in mappings:
        if not isinstance(raw, Mapping):
            raise PhotorealExAvatarMaterializerError("ExAvatar materialization frame mapping is invalid")
        index = raw.get("exavatar_frame_index")
        if isinstance(index, bool) or not isinstance(index, int) or index not in expected_by_index:
            raise PhotorealExAvatarMaterializerError("ExAvatar materialization frame index is invalid")
        expected = expected_by_index.pop(index)
        if raw.get("source_key") != expected["source_key"]:
            raise PhotorealExAvatarMaterializerError("ExAvatar materialization frame source mismatch")
        if _sha(raw.get("source_frame_sha256"), label="materialized source frame SHA-256") != expected["frame_sha256"]:
            raise PhotorealExAvatarMaterializerError("ExAvatar materialization source frame SHA mismatch")
        if round(float(raw.get("timestamp_seconds")), 6) != expected["timestamp_seconds"] or raw.get("eye") != "mono":
            raise PhotorealExAvatarMaterializerError("ExAvatar materialization timestamp/eye mismatch")
        relative = f"frames/{index}.png"
        if raw.get("relative_path") != relative:
            raise PhotorealExAvatarMaterializerError("ExAvatar materialization frame path is not canonical")
        path = dataset_dir / "frames" / f"{index}.png"
        if not path.is_file() or path.stat().st_size < 1:
            raise PhotorealExAvatarMaterializerError(f"materialized ExAvatar frame missing: {relative}")
        staged_sha = _file_sha(path)
        if _sha(raw.get("staged_png_sha256"), label="staged PNG SHA-256") != staged_sha:
            raise PhotorealExAvatarMaterializerError("ExAvatar staged PNG SHA mismatch")
        listed_files.add(relative)
        normalized_frames.append(dict(raw))
    if expected_by_index:
        raise PhotorealExAvatarMaterializerError("ExAvatar materialization omitted expected frames")

    for filename in ("frame_list_all.txt", "frame_list_train.txt", "frame_list_test.txt", "bodyrig-source-map.json"):
        path = dataset_dir / filename
        if not path.is_file():
            raise PhotorealExAvatarMaterializerError(f"ExAvatar materialization missing file: {filename}")
    expected_indices = "".join(f"{index}\n" for index in range(len(observations)))
    if (dataset_dir / "frame_list_all.txt").read_text(encoding="utf-8") != expected_indices:
        raise PhotorealExAvatarMaterializerError("ExAvatar frame_list_all.txt does not match exact authorized frame set")
    if (dataset_dir / "frame_list_train.txt").read_text(encoding="utf-8") != expected_indices:
        raise PhotorealExAvatarMaterializerError("ExAvatar frame_list_train.txt does not match exact authorized frame set")
    if (dataset_dir / "frame_list_test.txt").read_text(encoding="utf-8") != "":
        raise PhotorealExAvatarMaterializerError("ExAvatar frame_list_test.txt must remain empty; BodyRig held-out eval is external")

    actual_files = {
        path.relative_to(dataset_dir).as_posix()
        for path in dataset_dir.rglob("*")
        if path.is_file() and path.name != "materialization-receipt.json"
    }
    if actual_files != listed_files:
        raise PhotorealExAvatarMaterializerError("ExAvatar materialization output file universe mismatch")
    result = dict(receipt)
    result["frames"] = sorted(normalized_frames, key=lambda item: int(item["exavatar_frame_index"]))
    return result


def materialize_exavatar_benchmark(
    plan: Mapping[str, Any],
    *,
    workspace: str | Path,
    tool_path: str | Path,
    distribution: str = "Ubuntu-22.04",
    linux_python: str = "/opt/bodyrig-photoreal/bin/python",
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    selected, observations = _validate_plan(plan)
    root = Path(workspace).expanduser().resolve()
    tool = Path(tool_path).expanduser().resolve()
    if root.exists():
        raise PhotorealExAvatarMaterializerError(f"ExAvatar materialization workspace already exists: {root}")
    if not tool.is_file():
        raise PhotorealExAvatarMaterializerError(f"ExAvatar materializer tool not found: {tool}")
    root.mkdir(parents=True)
    dataset_dir = root / "dataset"
    dataset_dir.mkdir()
    log_path = root / "materializer.log"

    try:
        converter = make_wsl_path_converter(wsl_exe, distribution)
        linux_source = converter(str(selected["resolved_path"]))
        request = _build_request(plan, selected, observations, linux_source)
        with tempfile.TemporaryDirectory(prefix="bodyrig-exavatar-materialize-") as temp:
            request_path = Path(temp) / "request.json"
            request_path.write_text(
                json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            linux_request = converter(str(request_path))
            linux_output = converter(str(dataset_dir))
            linux_tool = converter(str(tool))
            invocation = [
                wsl_exe,
                "-d",
                _text(distribution, label="WSL distribution", maximum=160),
                "--",
                _text(linux_python, label="Linux Python"),
                linux_tool,
                "--request",
                linux_request,
                "--output",
                linux_output,
            ]
            completed = subprocess.run(
                invocation,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                check=False,
            )
            log_path.write_text(completed.stdout or "", encoding="utf-8")
            if completed.returncode != 0:
                tail = (completed.stdout or "")[-6000:].strip()
                raise PhotorealExAvatarMaterializerError(
                    f"ExAvatar materializer failed with exit code {completed.returncode}" + (f": {tail}" if tail else "")
                )
    except (OSError, WslBridgeError) as exc:
        raise PhotorealExAvatarMaterializerError(f"ExAvatar materializer transport failed: {exc}") from exc

    receipt_path = dataset_dir / "materialization-receipt.json"
    if not receipt_path.is_file():
        raise PhotorealExAvatarMaterializerError("ExAvatar materializer did not create materialization-receipt.json")
    receipt = _read_json(receipt_path, label="ExAvatar materialization receipt")
    return _validate_receipt(receipt, request=request, dataset_dir=dataset_dir)


def materialize_exavatar_benchmark_files(
    plan_path: str | Path,
    *,
    workspace: str | Path,
    tool_path: str | Path,
    distribution: str = "Ubuntu-22.04",
    linux_python: str = "/opt/bodyrig-photoreal/bin/python",
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    plan = _read_json(plan_path, label="photoreal teacher benchmark plan")
    return materialize_exavatar_benchmark(
        plan,
        workspace=workspace,
        tool_path=tool_path,
        distribution=distribution,
        linux_python=linux_python,
        wsl_exe=wsl_exe,
    )

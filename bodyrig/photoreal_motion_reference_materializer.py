from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .logged_process import LoggedProcessError, run_logged_process
from .photoreal_animated_review_plan import MOTION_REVIEW_DIMENSIONS

CONFIG_FORMAT = "bodyrig-photoreal-motion-reference-materializer-config"
REQUEST_FORMAT = "bodyrig-photoreal-motion-reference-materialization-request"
RESULT_FORMAT = "bodyrig-photoreal-motion-reference-materialization-result"
VERSION = 1
ADAPTER = "bodyrig-motion-reference-materializer-v1"
SAMPLE_FPS = 24.0
MAX_TIMEOUT_SECONDS = 86400

PLAN_FIELDS = {
    "format", "version", "performer_id", "selected_epoch_id", "teacher_input_sha256",
    "teacher_manifest_sha256", "static_teacher_review_sha256", "animation_plan_sha256",
    "animation_execution_receipt_sha256", "held_out_reference_catalog_sha256", "reviewer",
    "operator_supplied", "motion_review_dimensions", "selection_count", "selections",
    "animation_artifact_bytes_reverified", "held_out_evaluation_only",
    "held_out_motion_reference_selection_complete", "motion_reference_materialization_required",
    "reference_motion_bytes_materialized", "human_animated_visual_acceptance_required",
    "animated_teacher_acceptance_authority", "p3_device_distillation_authorized",
    "source_paths_build_private", "build_only", "runtime_dependency", "production_activation",
    "animated_review_plan_sha256",
}
SELECTION_FIELDS = {
    "dimension", "animation_artifact_kind", "animation_artifact_relative_path",
    "animation_artifact_size_bytes", "animation_artifact_sha256", "reference_observation_id",
    "reference_source_key", "reference_source_group_id", "reference_source_resolved_path",
    "reference_source_sha256", "reference_source_projection", "reference_source_stereo_layout",
    "reference_timestamp_seconds", "reference_eye", "reference_view_bin", "reference_frame_sha256",
    "window_before_seconds", "window_after_seconds", "window_start_seconds", "window_end_seconds",
    "reference_motion_bytes_materialized",
}


class PhotorealMotionReferenceMaterializerError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealMotionReferenceMaterializerError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealMotionReferenceMaterializerError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealMotionReferenceMaterializerError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealMotionReferenceMaterializerError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealMotionReferenceMaterializerError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealMotionReferenceMaterializerError(f"{label} is invalid")
    return clean


def _v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value != 1:
        raise PhotorealMotionReferenceMaterializerError(f"{label} version must be numeric v1")


def _finite(value: Any, *, label: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealMotionReferenceMaterializerError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise PhotorealMotionReferenceMaterializerError(f"{label} is invalid")
    return round(result, 6)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_without(value: Mapping[str, Any], key: str) -> str:
    payload = {name: item for name, item in value.items() if name != key}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _window_id(*, source_key: str, eye: str, start: float, end: float) -> str:
    payload = {"source_key": source_key, "eye": eye, "window_start_seconds": start, "window_end_seconds": end}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _validate_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != PLAN_FIELDS:
        raise PhotorealMotionReferenceMaterializerError("animated review plan fields must match v1 exactly")
    if value.get("format") != "bodyrig-photoreal-animated-review-plan":
        raise PhotorealMotionReferenceMaterializerError("animated review plan format mismatch")
    _v1(value.get("version"), label="animated review plan")
    declared = _sha(value.get("animated_review_plan_sha256"), label="animated review plan SHA-256")
    if declared != _digest_without(value, "animated_review_plan_sha256"):
        raise PhotorealMotionReferenceMaterializerError("animated review plan SHA-256 does not match content")
    for key in (
        "teacher_input_sha256", "teacher_manifest_sha256", "static_teacher_review_sha256",
        "animation_plan_sha256", "animation_execution_receipt_sha256", "held_out_reference_catalog_sha256",
    ):
        _sha(value.get(key), label=key)
    _text(value.get("performer_id"), label="performer id", maximum=256)
    _text(value.get("selected_epoch_id"), label="selected epoch id", maximum=256)
    if value.get("operator_supplied") is not True:
        raise PhotorealMotionReferenceMaterializerError("animated review plan lost operator selection authority")
    if value.get("motion_review_dimensions") != list(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealMotionReferenceMaterializerError("animated review dimension universe is not canonical")
    selections = value.get("selections")
    count = value.get("selection_count")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealMotionReferenceMaterializerError("animated review selection_count is invalid")
    if not isinstance(selections, list) or len(selections) != count:
        raise PhotorealMotionReferenceMaterializerError("animated review selections do not match count")
    dimensions: list[str] = []
    for raw in selections:
        if not isinstance(raw, Mapping) or set(raw) != SELECTION_FIELDS:
            raise PhotorealMotionReferenceMaterializerError("animated review selection fields must match v1 exactly")
        dimension = _text(raw.get("dimension"), label="motion-review dimension", maximum=80)
        dimensions.append(dimension)
        _sha(raw.get("animation_artifact_sha256"), label="animation artifact SHA-256")
        _sha(raw.get("reference_observation_id"), label="reference observation id")
        _sha(raw.get("reference_source_sha256"), label="reference source SHA-256")
        _sha(raw.get("reference_frame_sha256"), label="reference frame SHA-256")
        if raw.get("reference_source_projection") != "flat":
            raise PhotorealMotionReferenceMaterializerError("motion materialization v1 only supports flat held-out video")
        if raw.get("reference_source_stereo_layout") not in {"mono", "side-by-side", "over-under"}:
            raise PhotorealMotionReferenceMaterializerError("motion materialization stereo layout is unsupported")
        if raw.get("reference_eye") not in {"mono", "left", "right"}:
            raise PhotorealMotionReferenceMaterializerError("motion materialization eye is invalid")
        timestamp = _finite(raw.get("reference_timestamp_seconds"), label="reference timestamp")
        start = _finite(raw.get("window_start_seconds"), label="window start")
        end = _finite(raw.get("window_end_seconds"), label="window end")
        if not start <= timestamp <= end or end <= start:
            raise PhotorealMotionReferenceMaterializerError("motion review anchor timestamp is outside selected window")
        if raw.get("reference_motion_bytes_materialized") is not False:
            raise PhotorealMotionReferenceMaterializerError("animated review selection already claims materialized motion bytes")
    if dimensions != list(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealMotionReferenceMaterializerError("animated review selections are not in canonical dimension order")
    if value.get("animation_artifact_bytes_reverified") is not True or value.get("held_out_evaluation_only") is not True:
        raise PhotorealMotionReferenceMaterializerError("animated review plan evidence authority is incomplete")
    if value.get("held_out_motion_reference_selection_complete") is not True:
        raise PhotorealMotionReferenceMaterializerError("animated review held-out selection is incomplete")
    if value.get("motion_reference_materialization_required") is not True or value.get("reference_motion_bytes_materialized") is not False:
        raise PhotorealMotionReferenceMaterializerError("animated review materialization phase boundary is invalid")
    if value.get("human_animated_visual_acceptance_required") is not True:
        raise PhotorealMotionReferenceMaterializerError("animated review plan removed human acceptance")
    if value.get("animated_teacher_acceptance_authority") is not False:
        raise PhotorealMotionReferenceMaterializerError("animated review plan crossed animated-teacher acceptance authority")
    if value.get("p3_device_distillation_authorized") is not False or value.get("production_activation") is not False:
        raise PhotorealMotionReferenceMaterializerError("animated review plan crossed downstream authority")
    if value.get("source_paths_build_private") is not True or value.get("build_only") is not True or value.get("runtime_dependency") is not False:
        raise PhotorealMotionReferenceMaterializerError("animated review plan build/runtime boundary is invalid")
    return dict(value)


def build_motion_materialization_request(
    plan: Mapping[str, Any],
    *,
    adapter: str,
    revision: str,
) -> dict[str, Any]:
    plan = _validate_plan(plan)
    grouped: dict[str, dict[str, Any]] = {}
    windows: dict[tuple[str, str, float, float], dict[str, Any]] = {}
    for raw in plan["selections"]:
        source_key = _text(raw.get("reference_source_key"), label="reference source key")
        path = _text(raw.get("reference_source_resolved_path"), label="reference source path", maximum=32768)
        source_sha = _sha(raw.get("reference_source_sha256"), label="reference source SHA-256")
        projection = _text(raw.get("reference_source_projection"), label="reference projection", maximum=128)
        stereo_layout = _text(raw.get("reference_source_stereo_layout"), label="reference stereo layout", maximum=128)
        eye = _text(raw.get("reference_eye"), label="reference eye", maximum=16)
        start = _finite(raw.get("window_start_seconds"), label="window start")
        end = _finite(raw.get("window_end_seconds"), label="window end")
        source = grouped.setdefault(
            source_key,
            {
                "source_key": source_key,
                "source_sha256": source_sha,
                "kind": "video",
                "resolved_path": path,
                "projection": projection,
                "stereo_layout": stereo_layout,
                "windows": [],
            },
        )
        if any(
            source[key] != expected
            for key, expected in (
                ("source_sha256", source_sha), ("resolved_path", path),
                ("projection", projection), ("stereo_layout", stereo_layout),
            )
        ):
            raise PhotorealMotionReferenceMaterializerError("one held-out source key has conflicting materialization authority")
        key = (source_key, eye, start, end)
        window = windows.get(key)
        if window is None:
            window = {
                "window_id": _window_id(source_key=source_key, eye=eye, start=start, end=end),
                "eye": eye,
                "window_start_seconds": start,
                "window_end_seconds": end,
                "dimensions": [],
                "anchors": [],
            }
            windows[key] = window
            source["windows"].append(window)
        dimension = str(raw["dimension"])
        if dimension not in window["dimensions"]:
            window["dimensions"].append(dimension)
        anchor = {
            "observation_id": _sha(raw.get("reference_observation_id"), label="reference observation id"),
            "timestamp_seconds": _finite(raw.get("reference_timestamp_seconds"), label="reference timestamp"),
            "expected_frame_sha256": _sha(raw.get("reference_frame_sha256"), label="reference frame SHA-256"),
            "dimensions": [dimension],
        }
        existing = next((item for item in window["anchors"] if item["observation_id"] == anchor["observation_id"]), None)
        if existing is None:
            window["anchors"].append(anchor)
        else:
            if (existing["timestamp_seconds"], existing["expected_frame_sha256"]) != (anchor["timestamp_seconds"], anchor["expected_frame_sha256"]):
                raise PhotorealMotionReferenceMaterializerError("one held-out observation has conflicting anchor authority")
            if dimension not in existing["dimensions"]:
                existing["dimensions"].append(dimension)

    sources = sorted(grouped.values(), key=lambda item: item["source_key"])
    for source in sources:
        source["windows"].sort(key=lambda item: item["window_id"])
        for window in source["windows"]:
            window["dimensions"].sort()
            window["anchors"].sort(key=lambda item: item["observation_id"])
            for anchor in window["anchors"]:
                anchor["dimensions"].sort()
    return {
        "format": REQUEST_FORMAT,
        "version": VERSION,
        "performer_id": plan["performer_id"],
        "selected_epoch_id": plan["selected_epoch_id"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "animation_execution_receipt_sha256": plan["animation_execution_receipt_sha256"],
        "held_out_reference_catalog_sha256": plan["held_out_reference_catalog_sha256"],
        "animated_review_plan_sha256": plan["animated_review_plan_sha256"],
        "adapter": _text(adapter, label="motion materializer adapter", maximum=128),
        "revision": _sha(revision, label="motion materializer revision"),
        "sample_fps": SAMPLE_FPS,
        "sources": sources,
        "source_count": len(sources),
        "window_count": len(windows),
        "decode_semantics": "opencv-bgr-array-v1",
        "frame_hash_semantics": "sha256(shape-ascii-newline+contiguous-bgr-bytes)",
        "teacher_process_disclosure": False,
        "build_only": True,
        "runtime_dependency": False,
        "animated_teacher_acceptance_authority": False,
        "p3_device_distillation_authorized": False,
        "production_activation": False,
    }


def _safe_output(root: Path, relative: Any) -> tuple[str, Path]:
    value = _text(relative, label="materialized motion relative path").replace("\\", "/")
    if value.startswith("/") or value.startswith("../") or "/../" in f"/{value}/" or ":" in value.split("/", 1)[0]:
        raise PhotorealMotionReferenceMaterializerError("materialized motion path escapes output root")
    target = (root / value).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealMotionReferenceMaterializerError("materialized motion path escapes output root") from exc
    return value, target


def validate_motion_materialization_result(
    value: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    required = {
        "format", "version", "performer_id", "selected_epoch_id", "teacher_input_sha256",
        "animation_execution_receipt_sha256", "held_out_reference_catalog_sha256",
        "animated_review_plan_sha256", "adapter", "revision", "sample_fps",
        "source_count", "window_count", "materialized_windows", "all_source_hashes_verified",
        "all_anchor_hashes_verified", "decode_semantics", "frame_hash_semantics",
        "teacher_process_disclosure", "reference_motion_bytes_materialized",
        "human_animated_visual_acceptance_required", "animated_teacher_acceptance_authority",
        "p3_device_distillation_authorized", "build_only", "runtime_dependency", "production_activation",
    }
    if set(value) != required:
        raise PhotorealMotionReferenceMaterializerError("motion materialization result fields must match v1 exactly")
    if value.get("format") != RESULT_FORMAT:
        raise PhotorealMotionReferenceMaterializerError("motion materialization result format mismatch")
    _v1(value.get("version"), label="motion materialization result")
    for key in (
        "performer_id", "selected_epoch_id", "teacher_input_sha256",
        "animation_execution_receipt_sha256", "held_out_reference_catalog_sha256",
        "animated_review_plan_sha256", "adapter", "revision", "sample_fps",
        "source_count", "window_count", "decode_semantics", "frame_hash_semantics",
    ):
        if value.get(key) != request.get(key):
            raise PhotorealMotionReferenceMaterializerError(f"motion materialization provenance mismatch: {key}")
    if value.get("all_source_hashes_verified") is not True or value.get("all_anchor_hashes_verified") is not True:
        raise PhotorealMotionReferenceMaterializerError("motion materialization did not verify source/anchor hashes")
    if value.get("teacher_process_disclosure") is not False:
        raise PhotorealMotionReferenceMaterializerError("motion materialization crossed teacher disclosure boundary")
    if value.get("reference_motion_bytes_materialized") is not True:
        raise PhotorealMotionReferenceMaterializerError("motion materialization result did not materialize reference motion")
    if value.get("human_animated_visual_acceptance_required") is not True:
        raise PhotorealMotionReferenceMaterializerError("motion materialization removed human animated review")
    if value.get("animated_teacher_acceptance_authority") is not False or value.get("p3_device_distillation_authorized") is not False:
        raise PhotorealMotionReferenceMaterializerError("motion materialization crossed downstream authority")
    if value.get("build_only") is not True or value.get("runtime_dependency") is not False or value.get("production_activation") is not False:
        raise PhotorealMotionReferenceMaterializerError("motion materialization build/runtime/production boundary is invalid")

    expected_windows = {
        window["window_id"]
        for source in request["sources"]
        for window in source["windows"]
    }
    windows = value.get("materialized_windows")
    if not isinstance(windows, list) or len(windows) != len(expected_windows):
        raise PhotorealMotionReferenceMaterializerError("motion materialization window count mismatch")
    seen_windows: set[str] = set()
    listed_files: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in windows:
        if not isinstance(raw, Mapping):
            raise PhotorealMotionReferenceMaterializerError("motion materialization window entry is invalid")
        window_id = _sha(raw.get("window_id"), label="motion window id")
        if window_id not in expected_windows or window_id in seen_windows:
            raise PhotorealMotionReferenceMaterializerError("motion materialization returned unknown/duplicate window")
        seen_windows.add(window_id)
        if raw.get("source_hash_verified") is not True or raw.get("all_anchor_hashes_verified") is not True:
            raise PhotorealMotionReferenceMaterializerError("motion window lacks source/anchor verification")
        frames = raw.get("frames")
        if not isinstance(frames, list) or not frames:
            raise PhotorealMotionReferenceMaterializerError("motion window contains no materialized frames")
        frame_count = raw.get("frame_count")
        if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count != len(frames):
            raise PhotorealMotionReferenceMaterializerError("motion window frame count mismatch")
        normalized_frames: list[dict[str, Any]] = []
        for frame in frames:
            if not isinstance(frame, Mapping) or set(frame) != {"index", "requested_timestamp_seconds", "decoded_frame_sha256", "png_relative_path", "png_size_bytes", "png_sha256"}:
                raise PhotorealMotionReferenceMaterializerError("motion frame fields must match v1 exactly")
            index = frame.get("index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise PhotorealMotionReferenceMaterializerError("motion frame index is invalid")
            relative, path = _safe_output(output_dir, frame.get("png_relative_path"))
            if relative in listed_files:
                raise PhotorealMotionReferenceMaterializerError("motion materialization repeats PNG path")
            listed_files.add(relative)
            if not path.is_file():
                raise PhotorealMotionReferenceMaterializerError(f"materialized motion PNG is missing: {relative}")
            size = frame.get("png_size_bytes")
            if isinstance(size, bool) or not isinstance(size, int) or size < 1 or path.stat().st_size != size:
                raise PhotorealMotionReferenceMaterializerError(f"materialized motion PNG size mismatch: {relative}")
            png_sha = _sha(frame.get("png_sha256"), label="materialized motion PNG SHA-256")
            if _hash_file(path) != png_sha:
                raise PhotorealMotionReferenceMaterializerError(f"materialized motion PNG SHA-256 mismatch: {relative}")
            normalized_frames.append({
                "index": index,
                "requested_timestamp_seconds": _finite(frame.get("requested_timestamp_seconds"), label="motion frame timestamp"),
                "decoded_frame_sha256": _sha(frame.get("decoded_frame_sha256"), label="decoded motion frame SHA-256"),
                "png_relative_path": relative,
                "png_size_bytes": size,
                "png_sha256": png_sha,
            })
        normalized_window = dict(raw)
        normalized_window["frames"] = normalized_frames
        normalized.append(normalized_window)
    if seen_windows != expected_windows:
        raise PhotorealMotionReferenceMaterializerError("motion materialization did not cover planned windows")
    actual_files = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != "motion-materialization-result.json"
    }
    if actual_files != listed_files:
        raise PhotorealMotionReferenceMaterializerError("motion materialization output file universe mismatch")
    result = dict(value)
    result["materialized_windows"] = sorted(normalized, key=lambda item: item["window_id"])
    return result


def run_external_motion_materializer(
    config: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    workspace: str | Path,
) -> dict[str, Any]:
    if set(config) != {"format", "version", "adapter", "revision", "command", "timeout_seconds"}:
        raise PhotorealMotionReferenceMaterializerError("motion materializer config fields must match v1 exactly")
    if config.get("format") != CONFIG_FORMAT or config.get("adapter") != ADAPTER:
        raise PhotorealMotionReferenceMaterializerError("motion materializer config format/adapter mismatch")
    _v1(config.get("version"), label="motion materializer config")
    revision = _sha(config.get("revision"), label="motion materializer revision")
    command = config.get("command")
    timeout = config.get("timeout_seconds")
    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        raise PhotorealMotionReferenceMaterializerError("motion materializer command is invalid")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise PhotorealMotionReferenceMaterializerError("motion materializer timeout is invalid")
    request = build_motion_materialization_request(plan, adapter=ADAPTER, revision=revision)
    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealMotionReferenceMaterializerError(f"motion materializer workspace already exists: {root}")
    root.mkdir(parents=True)
    request_path = root / "request.json"
    output_dir = root / "output"
    log_path = root / "adapter.log"
    output_dir.mkdir()
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    invoke = [*list(command), "--bodyrig-request", str(request_path), "--bodyrig-output", str(output_dir), "--bodyrig-adapter", ADAPTER, "--bodyrig-revision", revision]
    try:
        completed = run_logged_process(invoke, log_path=log_path, timeout_seconds=timeout)
    except subprocess.TimeoutExpired as exc:
        raise PhotorealMotionReferenceMaterializerError(f"motion materializer timed out after {timeout} seconds") from exc
    except (OSError, LoggedProcessError) as exc:
        raise PhotorealMotionReferenceMaterializerError(f"motion materializer could not complete: {exc}") from exc
    if completed.returncode != 0:
        raise PhotorealMotionReferenceMaterializerError(f"motion materializer failed with exit code {completed.returncode}")
    result_path = output_dir / "motion-materialization-result.json"
    if not result_path.is_file():
        raise PhotorealMotionReferenceMaterializerError("motion materializer did not create result")
    result = _read_json(result_path, label="motion materialization result")
    return validate_motion_materialization_result(result, request=request, output_dir=output_dir)


def run_external_motion_materializer_files(
    config_path: str | Path,
    plan_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = _read_json(config_path, label="motion materializer config")
    plan = _read_json(plan_path, label="animated review plan")
    return run_external_motion_materializer(config, plan, workspace=workspace)

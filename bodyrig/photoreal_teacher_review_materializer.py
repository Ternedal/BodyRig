from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .logged_process import LoggedProcessError, run_logged_process
from .photoreal_teacher_review_mapping import (
    OUTPUT_FORMAT as MAPPING_FORMAT,
    _validate_reference_catalog,
)

CONFIG_FORMAT = "bodyrig-photoreal-reference-frame-materializer-config"
REQUEST_FORMAT = "bodyrig-photoreal-reference-frame-materialization-request"
RESULT_FORMAT = "bodyrig-photoreal-reference-frame-materialization-receipt"
VERSION = 1
ADAPTER = "bodyrig-reference-frame-materializer-v1"
MAX_TIMEOUT_SECONDS = 86400


class PhotorealTeacherReviewMaterializerError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealTeacherReviewMaterializerError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealTeacherReviewMaterializerError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealTeacherReviewMaterializerError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum:
        raise PhotorealTeacherReviewMaterializerError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealTeacherReviewMaterializerError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealTeacherReviewMaterializerError(f"{label} is invalid")
    return result


def _v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealTeacherReviewMaterializerError(f"{label} version must be numeric v1")
    if not math.isfinite(float(value)) or value != 1:
        raise PhotorealTeacherReviewMaterializerError(f"{label} version must be numeric v1")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def build_materializer_config(
    *,
    windows_python: str | Path,
    bridge_path: str | Path,
    adapter_path: str | Path,
    distribution: str = "Ubuntu-22.04",
    linux_python: str = "/opt/bodyrig-photoreal/bin/python",
    wsl_exe: str = "wsl.exe",
    timeout_seconds: int = MAX_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    windows_python_path = Path(windows_python).expanduser().resolve()
    bridge = Path(bridge_path).expanduser().resolve()
    adapter = Path(adapter_path).expanduser().resolve()
    for path, label in (
        (windows_python_path, "Windows Python"),
        (bridge, "reference frame materializer WSL bridge"),
        (adapter, "reference frame materializer adapter"),
    ):
        if not path.is_file():
            raise PhotorealTeacherReviewMaterializerError(f"{label} not found: {path}")
    distribution = _text(distribution, label="WSL distribution", maximum=160)
    linux_python = _text(linux_python, label="Linux Python", maximum=4096)
    if not linux_python.startswith("/"):
        raise PhotorealTeacherReviewMaterializerError("Linux Python must be an absolute Linux path")
    wsl_exe = _text(wsl_exe, label="WSL executable", maximum=4096)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise PhotorealTeacherReviewMaterializerError(
            f"timeout_seconds must be an integer in 1..{MAX_TIMEOUT_SECONDS}"
        )
    revision = _hash_file(adapter)
    return {
        "format": CONFIG_FORMAT,
        "version": VERSION,
        "adapter": ADAPTER,
        "revision": revision,
        "command": [
            str(windows_python_path),
            str(bridge),
            "--distribution",
            distribution,
            "--wsl-exe",
            wsl_exe,
            "--linux-python",
            linux_python,
            "--adapter-path",
            str(adapter),
        ],
        "timeout_seconds": timeout_seconds,
    }


def load_materializer_config(path: str | Path) -> dict[str, Any]:
    value = _read_json(path, label="reference frame materializer config")
    if set(value) != {"format", "version", "adapter", "revision", "command", "timeout_seconds"}:
        raise PhotorealTeacherReviewMaterializerError("materializer config fields must match v1 exactly")
    if value.get("format") != CONFIG_FORMAT:
        raise PhotorealTeacherReviewMaterializerError("materializer config format mismatch")
    _v1(value.get("version"), label="materializer config")
    if value.get("adapter") != ADAPTER:
        raise PhotorealTeacherReviewMaterializerError("materializer adapter mismatch")
    revision = _sha(value.get("revision"), label="materializer revision")
    command = value.get("command")
    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        raise PhotorealTeacherReviewMaterializerError("materializer command is invalid")
    timeout = value.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise PhotorealTeacherReviewMaterializerError("materializer timeout is invalid")
    return {
        "format": CONFIG_FORMAT,
        "version": VERSION,
        "adapter": ADAPTER,
        "revision": revision,
        "command": list(command),
        "timeout_seconds": timeout,
    }


def _validate_mapping(value: Mapping[str, Any]) -> tuple[str, str, str, str, list[Mapping[str, Any]]]:
    if value.get("format") != MAPPING_FORMAT:
        raise PhotorealTeacherReviewMaterializerError("review mapping format mismatch")
    _v1(value.get("version"), label="review mapping")
    declared = _sha(value.get("review_mapping_sha256"), label="review mapping SHA-256")
    if _digest(value, omit="review_mapping_sha256") != declared:
        raise PhotorealTeacherReviewMaterializerError("review mapping digest mismatch")
    if value.get("semantic_view_mapping_complete") is not True or value.get("reference_selection_complete") is not True:
        raise PhotorealTeacherReviewMaterializerError("review mapping is incomplete")
    if value.get("reference_bytes_materialized") is not False or value.get("reference_frame_hashes_verified") is not False:
        raise PhotorealTeacherReviewMaterializerError("review mapping already claims materialized references")
    if value.get("likeness_review_complete") is not False:
        raise PhotorealTeacherReviewMaterializerError("review mapping already claims likeness review")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise PhotorealTeacherReviewMaterializerError("review mapping crossed downstream authority")
    mappings = value.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        raise PhotorealTeacherReviewMaterializerError("review mapping contains no mappings")
    return (
        _text(value.get("performer_id"), label="mapping performer id", maximum=256),
        _text(value.get("selected_epoch_id"), label="mapping epoch id", maximum=256),
        _sha(value.get("teacher_input_sha256"), label="mapping teacher input SHA-256"),
        declared,
        mappings,
    )


def build_materialization_request(
    mapping: Mapping[str, Any],
    reference_catalog: Mapping[str, Any],
    *,
    adapter: str,
    revision: str,
) -> dict[str, Any]:
    performer_id, epoch_id, teacher_input_sha, mapping_sha, mappings = _validate_mapping(mapping)
    try:
        ref_performer, ref_epoch, ref_teacher_input_sha, observations, _candidates, sources = _validate_reference_catalog(reference_catalog)
    except ValueError as exc:
        raise PhotorealTeacherReviewMaterializerError(str(exc)) from exc
    if (ref_performer, ref_epoch, ref_teacher_input_sha) != (performer_id, epoch_id, teacher_input_sha):
        raise PhotorealTeacherReviewMaterializerError("review mapping/reference catalog lineage mismatch")
    catalog_sha = _sha(reference_catalog.get("held_out_reference_catalog_sha256"), label="reference catalog SHA-256")
    if _sha(mapping.get("held_out_reference_catalog_sha256"), label="mapping reference catalog SHA-256") != catalog_sha:
        raise PhotorealTeacherReviewMaterializerError("review mapping targets a different reference catalog")

    grouped: dict[str, dict[str, Any]] = {}
    selections: dict[str, dict[str, Any]] = {}
    for raw in mappings:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherReviewMaterializerError("review mapping entry is invalid")
        coverage = _text(raw.get("coverage"), label="mapping coverage", maximum=64)
        observation_id = _sha(raw.get("reference_observation_id"), label="reference observation id")
        observation = observations.get(observation_id)
        if observation is None:
            raise PhotorealTeacherReviewMaterializerError("mapped held-out observation is absent from reference catalog")
        source_key = _text(observation.get("source_key"), label="reference source key")
        source = sources.get(source_key)
        if source is None:
            raise PhotorealTeacherReviewMaterializerError("mapped held-out source is absent from reference catalog")
        for key, catalog_value in (
            ("reference_source_key", source_key),
            ("reference_source_sha256", source.get("sha256")),
            ("reference_frame_sha256", observation.get("frame_sha256")),
            ("reference_timestamp_seconds", observation.get("timestamp_seconds")),
            ("reference_eye", observation.get("eye")),
        ):
            if raw.get(key) != catalog_value:
                raise PhotorealTeacherReviewMaterializerError(f"review mapping/catalog mismatch: {key}")

        projection = _text(source.get("projection"), label="reference projection", maximum=128)
        stereo_layout = _text(source.get("stereo_layout"), label="reference stereo layout", maximum=128)
        kind = _text(source.get("kind"), label="reference source kind", maximum=16)
        if projection != "flat":
            raise PhotorealTeacherReviewMaterializerError(
                f"reference materialization requires reproducible flat projection; unsupported: {projection}"
            )
        if stereo_layout not in {"mono", "side-by-side", "over-under"}:
            raise PhotorealTeacherReviewMaterializerError(
                f"reference materialization does not support stereo layout: {stereo_layout}"
            )
        if kind not in {"video", "image"}:
            raise PhotorealTeacherReviewMaterializerError(f"reference materialization does not support kind: {kind}")
        eye = str(observation.get("eye") or "")
        if (stereo_layout == "mono" and eye != "mono") or (stereo_layout != "mono" and eye not in {"left", "right"}):
            raise PhotorealTeacherReviewMaterializerError("reference observation eye/layout binding is invalid")
        timestamp = observation.get("timestamp_seconds")
        if kind == "video":
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or float(timestamp) < 0:
                raise PhotorealTeacherReviewMaterializerError("video reference timestamp is invalid")
        elif timestamp is not None:
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or float(timestamp) < 0:
                raise PhotorealTeacherReviewMaterializerError("image reference timestamp is invalid")

        source_entry = grouped.setdefault(
            source_key,
            {
                "source_key": source_key,
                "source_sha256": _sha(source.get("sha256"), label="reference source SHA-256"),
                "kind": kind,
                "resolved_path": _text(source.get("resolved_path"), label="reference source path", maximum=32768),
                "projection": projection,
                "stereo_layout": stereo_layout,
                "samples": [],
            },
        )
        selection = selections.get(observation_id)
        if selection is None:
            selection = {
                "observation_id": observation_id,
                "timestamp_seconds": None if timestamp is None else round(float(timestamp), 6),
                "eye": eye,
                "expected_frame_sha256": _sha(observation.get("frame_sha256"), label="expected frame SHA-256"),
                "coverages": [],
            }
            selections[observation_id] = selection
            source_entry["samples"].append(selection)
        elif selection not in source_entry["samples"]:
            raise PhotorealTeacherReviewMaterializerError("one observation maps to multiple source entries")
        if coverage in selection["coverages"]:
            raise PhotorealTeacherReviewMaterializerError("reference materialization repeats coverage")
        selection["coverages"].append(coverage)

    sources_out = sorted(grouped.values(), key=lambda item: item["source_key"])
    for source in sources_out:
        source["samples"].sort(key=lambda item: item["observation_id"])
        for sample in source["samples"]:
            sample["coverages"].sort()
    if not sources_out or not selections:
        raise PhotorealTeacherReviewMaterializerError("reference materialization request would be empty")

    return {
        "format": REQUEST_FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "selected_epoch_id": epoch_id,
        "teacher_input_sha256": teacher_input_sha,
        "review_mapping_sha256": mapping_sha,
        "held_out_reference_catalog_sha256": catalog_sha,
        "adapter": _text(adapter, label="materializer adapter", maximum=128),
        "revision": _sha(revision, label="materializer revision"),
        "sources": sources_out,
        "source_count": len(sources_out),
        "sample_count": len(selections),
        "decode_semantics": "opencv-bgr-array-v1",
        "frame_hash_semantics": "sha256(shape-ascii-newline+contiguous-bgr-bytes)",
        "teacher_process_disclosure": False,
        "build_only": True,
        "runtime_dependency": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def _safe_output_path(root: Path, relative: Any) -> tuple[str, Path]:
    value = _text(relative, label="materialized reference relative path").replace("\\", "/")
    if value.startswith("/") or value.startswith("../") or "/../" in f"/{value}/" or ":" in value.split("/", 1)[0]:
        raise PhotorealTeacherReviewMaterializerError("materialized reference path escapes output root")
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealTeacherReviewMaterializerError("materialized reference path escapes output root") from exc
    return value, path


def validate_materialization_result(
    value: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    required = {
        "format", "version", "performer_id", "selected_epoch_id", "teacher_input_sha256",
        "review_mapping_sha256", "held_out_reference_catalog_sha256", "adapter", "revision",
        "source_count", "sample_count", "materialized_references", "all_source_hashes_verified",
        "all_frame_hashes_verified", "decode_semantics", "frame_hash_semantics", "teacher_process_disclosure",
        "photoreal_acceptance_authority", "human_visual_acceptance_required", "build_only",
        "runtime_dependency", "production_activation",
    }
    if set(value) != required:
        raise PhotorealTeacherReviewMaterializerError("materialization receipt fields must match v1 exactly")
    if value.get("format") != RESULT_FORMAT:
        raise PhotorealTeacherReviewMaterializerError("materialization receipt format mismatch")
    _v1(value.get("version"), label="materialization receipt")
    for key in (
        "performer_id", "selected_epoch_id", "teacher_input_sha256", "review_mapping_sha256",
        "held_out_reference_catalog_sha256", "adapter", "revision", "decode_semantics", "frame_hash_semantics",
    ):
        if value.get(key) != request.get(key):
            raise PhotorealTeacherReviewMaterializerError(f"materialization receipt provenance mismatch: {key}")
    if value.get("all_source_hashes_verified") is not True or value.get("all_frame_hashes_verified") is not True:
        raise PhotorealTeacherReviewMaterializerError("materialization did not verify source/frame hashes")
    if value.get("teacher_process_disclosure") is not False:
        raise PhotorealTeacherReviewMaterializerError("materialization crossed teacher disclosure boundary")
    if value.get("photoreal_acceptance_authority") is not False or value.get("human_visual_acceptance_required") is not True:
        raise PhotorealTeacherReviewMaterializerError("materialization crossed photoreal/human authority")
    if value.get("build_only") is not True or value.get("runtime_dependency") is not False or value.get("production_activation") is not False:
        raise PhotorealTeacherReviewMaterializerError("materialization crossed build/runtime/production authority")

    refs = value.get("materialized_references")
    if not isinstance(refs, list) or len(refs) != request.get("sample_count"):
        raise PhotorealTeacherReviewMaterializerError("materialized reference count mismatch")
    expected: dict[str, tuple[str, str, float | None, str, list[str]]] = {}
    for source in request["sources"]:
        for sample in source["samples"]:
            expected[sample["observation_id"]] = (
                source["source_key"], sample["expected_frame_sha256"], sample["timestamp_seconds"], sample["eye"], sample["coverages"]
            )
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    listed_paths: set[str] = set()
    for raw in refs:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherReviewMaterializerError("materialized reference entry is invalid")
        observation_id = _sha(raw.get("observation_id"), label="materialized observation id")
        if observation_id in seen or observation_id not in expected:
            raise PhotorealTeacherReviewMaterializerError("materialized observation id is repeated or unauthorized")
        seen.add(observation_id)
        source_key, frame_sha, timestamp, eye, coverages = expected[observation_id]
        checks = {
            "source_key": source_key,
            "expected_frame_sha256": frame_sha,
            "observed_frame_sha256": frame_sha,
            "timestamp_seconds": timestamp,
            "eye": eye,
            "coverages": coverages,
            "source_hash_verified": True,
            "frame_hash_verified": True,
        }
        for key, expected_value in checks.items():
            if raw.get(key) != expected_value:
                raise PhotorealTeacherReviewMaterializerError(f"materialized reference mismatch: {key}")
        relative, path = _safe_output_path(output_dir, raw.get("png_relative_path"))
        if not path.is_file():
            raise PhotorealTeacherReviewMaterializerError(f"materialized reference PNG is missing: {relative}")
        observed_size = path.stat().st_size
        if isinstance(raw.get("png_size_bytes"), bool) or raw.get("png_size_bytes") != observed_size or observed_size < 1:
            raise PhotorealTeacherReviewMaterializerError(f"materialized reference PNG size mismatch: {relative}")
        observed_sha = _hash_file(path)
        if _sha(raw.get("png_sha256"), label="materialized PNG SHA-256") != observed_sha:
            raise PhotorealTeacherReviewMaterializerError(f"materialized reference PNG hash mismatch: {relative}")
        listed_paths.add(relative)
        item = dict(raw)
        item["png_relative_path"] = relative
        normalized.append(item)
    if seen != set(expected):
        raise PhotorealTeacherReviewMaterializerError("materialization receipt omitted selected observations")
    actual_pngs = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*.png")
        if path.is_file()
    }
    if actual_pngs != listed_paths:
        raise PhotorealTeacherReviewMaterializerError("materialized reference PNG universe mismatch")
    result = dict(value)
    result["materialized_references"] = sorted(normalized, key=lambda item: item["observation_id"])
    return result


def _log_tail(path: Path, limit: int = 8000) -> str:
    try:
        return path.read_bytes()[-limit:].decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def run_external_materializer(
    config: Mapping[str, Any],
    mapping: Mapping[str, Any],
    reference_catalog: Mapping[str, Any],
    *,
    workspace: str | Path,
) -> dict[str, Any]:
    config = dict(config)
    request = build_materialization_request(
        mapping,
        reference_catalog,
        adapter=config["adapter"],
        revision=config["revision"],
    )
    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealTeacherReviewMaterializerError(f"reference materializer workspace already exists: {root}")
    root.mkdir(parents=True)
    request_path = root / "request.json"
    output_dir = root / "output"
    log_path = root / "adapter.log"
    output_dir.mkdir()
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    invoke = [
        *list(config["command"]),
        "--bodyrig-request", str(request_path),
        "--bodyrig-output", str(output_dir),
        "--bodyrig-adapter", config["adapter"],
        "--bodyrig-revision", config["revision"],
    ]
    try:
        completed = run_logged_process(invoke, log_path=log_path, timeout_seconds=config["timeout_seconds"])
    except subprocess.TimeoutExpired as exc:
        detail = _log_tail(log_path)
        raise PhotorealTeacherReviewMaterializerError(
            f"reference materializer timed out after {config['timeout_seconds']} seconds" + (f" | {detail}" if detail else "")
        ) from exc
    except (OSError, LoggedProcessError) as exc:
        detail = _log_tail(log_path)
        raise PhotorealTeacherReviewMaterializerError(
            f"reference materializer could not complete: {exc}" + (f" | {detail}" if detail else "")
        ) from exc
    if completed.returncode != 0:
        detail = _log_tail(log_path)
        raise PhotorealTeacherReviewMaterializerError(
            f"reference materializer failed with exit code {completed.returncode}" + (f": {detail}" if detail else "")
        )
    receipt_path = output_dir / "materialization-receipt.json"
    if not receipt_path.is_file():
        raise PhotorealTeacherReviewMaterializerError("reference materializer did not create materialization-receipt.json")
    receipt = _read_json(receipt_path, label="reference materialization receipt")
    return validate_materialization_result(receipt, request=request, output_dir=output_dir)


def run_external_materializer_files(
    config_path: str | Path,
    mapping_path: str | Path,
    reference_catalog_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = load_materializer_config(config_path)
    mapping = _read_json(mapping_path, label="photoreal review mapping")
    catalog = _read_json(reference_catalog_path, label="photoreal held-out reference catalog")
    return run_external_materializer(config, mapping, catalog, workspace=workspace)

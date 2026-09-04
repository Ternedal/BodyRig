from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from .logged_process import run_logged_process
from .observation import (
    Observation,
    ObservationError,
    build_analyzer_request,
    validate_analyzer_result,
)

_CHECKPOINT_FORMAT = "bodyrig-observation-source-checkpoint"
_CHECKPOINT_VERSION = 1
_BUILTIN_ADAPTER = "opencv-hog-haar"
_BUILTIN_SOURCE_TIMEOUT_SECONDS = 86_400


def _read_log_tail(path: Path, limit: int = 4000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[-limit:].decode("utf-8", errors="replace").strip()


def _source_manifest_path(command: Sequence[str]) -> tuple[int, Path] | None:
    argv = list(command)
    try:
        index = argv.index("--bodyrig-stash-manifest")
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return None
    return index + 1, Path(argv[index + 1]).expanduser().resolve()


def _load_stash_manifest_for_checkpointing(command: Sequence[str], expected_count: int) -> tuple[int, dict[str, Any]] | None:
    located = _source_manifest_path(command)
    if located is None:
        return None
    value_index, path = located
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    selected = manifest.get("selected") if isinstance(manifest, dict) else None
    if not isinstance(selected, list) or len(selected) != expected_count:
        return None
    return value_index, manifest


def _checkpoint_root(workspace: Path, adapter: str, performer_id: str) -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        root = Path(base) / "BodyRig" / "observation-checkpoints"
    else:
        root = workspace.parent / ".observation-checkpoints"
    performer_hash = hashlib.sha256(performer_id.encode("utf-8")).hexdigest()[:16]
    adapter_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in adapter)[:80]
    target = root / adapter_name / performer_hash
    target.mkdir(parents=True, exist_ok=True)
    probe = target / f".write-probe-{uuid.uuid4().hex}"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        raise ObservationError(f"observation checkpoint store is not writable: {target}") from exc
    return target


def _source_fingerprint(
    *,
    source: Mapping[str, Any],
    performer_id: str,
    performer_count: int,
    adapter: str,
    revision: str,
) -> str:
    path = Path(str(source["path"])).expanduser().resolve()
    try:
        stat = path.stat()
    except OSError as exc:
        raise ObservationError(f"could not stat observation source for checkpointing: {path}") from exc
    payload = {
        "adapter": adapter,
        "revision": revision,
        "performer_id": performer_id,
        "scene_id": str(source["scene_id"]),
        "duration": round(float(source["duration"]), 3),
        "performer_count": int(performer_count),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "path_sha256": hashlib.sha256(os.path.normcase(str(path)).encode("utf-8")).hexdigest(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _observation_rows(observations: Sequence[Observation], source_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in observations:
        rows.append(
            {
                "source_id": source_id,
                "start_seconds": round(item.start_seconds, 3),
                "duration_seconds": round(item.duration_seconds, 3),
                "target_confidence": round(item.target_confidence, 4),
                "target_screen_fraction": round(item.target_screen_fraction, 4),
                "face_visibility": round(item.face_visibility, 4),
                "full_body_visibility": round(item.full_body_visibility, 4),
                "sharpness": round(item.sharpness, 4),
                "occlusion": round(item.occlusion, 4),
                "motion": round(item.motion, 4),
                "view": item.view,
            }
        )
    return rows


def _validate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    source: Mapping[str, Any],
    adapter: str,
    revision: str,
) -> list[Observation]:
    normalized = [dict(row) for row in rows]
    for row in normalized:
        row["source_id"] = str(source["source_id"])
    with tempfile.TemporaryDirectory(prefix="bodyrig-observation-checkpoint-validate-") as temp_name:
        result_path = Path(temp_name) / "observations.json"
        result_path.write_text(
            json.dumps(
                {
                    "format": "bodyrig-observation-analyzer-result",
                    "version": 1,
                    "adapter": adapter,
                    "revision": revision,
                    "observations": normalized,
                },
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return validate_analyzer_result(
            result_path,
            sources=[source],
            expected_adapter=adapter,
            expected_revision=revision,
        )


def _load_checkpoint(
    path: Path,
    *,
    fingerprint: str,
    source: Mapping[str, Any],
    adapter: str,
    revision: str,
) -> list[Observation] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or set(value) != {
        "format",
        "version",
        "adapter",
        "revision",
        "fingerprint_sha256",
        "observations",
    }:
        return None
    if (
        value["format"] != _CHECKPOINT_FORMAT
        or value["version"] != _CHECKPOINT_VERSION
        or value["adapter"] != adapter
        or value["revision"] != revision
        or value["fingerprint_sha256"] != fingerprint
        or not isinstance(value["observations"], list)
    ):
        return None
    try:
        return _validate_rows(
            value["observations"],
            source=source,
            adapter=adapter,
            revision=revision,
        )
    except (OSError, ObservationError, ValueError):
        return None


def _write_checkpoint(
    path: Path,
    *,
    fingerprint: str,
    observations: Sequence[Observation],
    source_id: str,
    adapter: str,
    revision: str,
) -> None:
    value = {
        "format": _CHECKPOINT_FORMAT,
        "version": _CHECKPOINT_VERSION,
        "adapter": adapter,
        "revision": revision,
        "fingerprint_sha256": fingerprint,
        "observations": _observation_rows(observations, source_id),
    }
    temporary = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ObservationError(f"could not persist observation checkpoint: {path}") from exc


def _run_single_source(
    command: Sequence[str],
    *,
    source: Mapping[str, Any],
    performer_id: str,
    source_manifest_sha256: str,
    workspace: Path,
    adapter: str,
    revision: str,
    timeout_seconds: int,
    manifest_value_index: int,
    manifest: Mapping[str, Any],
    manifest_selected_index: int,
) -> list[Observation]:
    request = build_analyzer_request(
        sources=[source],
        performer_id=performer_id,
        source_manifest_sha256=source_manifest_sha256,
    )
    with tempfile.TemporaryDirectory(prefix="bodyrig-observation-source-") as temp_name:
        temp = Path(temp_name)
        request_path = temp / "request.json"
        output_dir = temp / "output"
        log_path = temp / "adapter.log"
        one_source_manifest_path = temp / "stash-manifest.json"
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        output_dir.mkdir()

        one_source_manifest = dict(manifest)
        selected = manifest.get("selected")
        if not isinstance(selected, list) or manifest_selected_index >= len(selected):
            raise ObservationError("observation checkpoint source manifest mapping changed during analysis")
        one_source_manifest["selected"] = [selected[manifest_selected_index]]
        one_source_manifest_path.write_text(
            json.dumps(one_source_manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )

        argv = list(command)
        argv[manifest_value_index] = str(one_source_manifest_path)
        invoke = [
            *argv,
            "--bodyrig-request",
            str(request_path),
            "--bodyrig-workspace",
            str(workspace),
            "--bodyrig-output",
            str(output_dir),
            "--bodyrig-adapter",
            adapter,
            "--bodyrig-revision",
            revision,
            "--bodyrig-source-id",
            str(source["source_id"]),
            "--bodyrig-source-path",
            str(source["path"]),
        ]
        try:
            completed = run_logged_process(
                invoke,
                log_path=log_path,
                timeout_seconds=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            detail = _read_log_tail(log_path)
            suffix = f" | log tail: {detail}" if detail else ""
            raise ObservationError(
                f"observation analyzer timed out after {timeout_seconds} seconds for scene {source['scene_id']}{suffix}"
            ) from exc
        except OSError as exc:
            detail = _read_log_tail(log_path)
            suffix = f" | log tail: {detail}" if detail else ""
            raise ObservationError(
                f"observation analyzer process could not complete for scene {source['scene_id']}: {exc}{suffix}"
            ) from exc
        if completed.returncode != 0:
            detail = _read_log_tail(log_path)
            suffix = f": {detail}" if detail else ""
            raise ObservationError(
                f"observation analyzer failed with exit code {completed.returncode} for scene {source['scene_id']}{suffix}"
            )
        children = list(output_dir.iterdir())
        if {item.name for item in children} != {"observations.json"} or any(not item.is_file() for item in children):
            raise ObservationError("observation analyzer output must contain exactly observations.json")
        return validate_analyzer_result(
            output_dir / "observations.json",
            sources=[source],
            expected_adapter=adapter,
            expected_revision=revision,
        )


def _run_checkpointed_builtin(
    command: Sequence[str],
    *,
    sources: Sequence[Mapping[str, Any]],
    performer_id: str,
    source_manifest_sha256: str,
    workspace: Path,
    adapter: str,
    revision: str,
    timeout_seconds: int,
) -> list[Observation] | None:
    loaded = _load_stash_manifest_for_checkpointing(command, len(sources))
    if loaded is None:
        return None
    manifest_value_index, manifest = loaded
    selected = manifest.get("selected")
    if not isinstance(selected, list):
        return None

    counts: list[int] = []
    for item in selected:
        try:
            count = int(item["performer_count"])
        except (KeyError, TypeError, ValueError):
            return None
        if count < 1:
            return None
        counts.append(count)

    root = _checkpoint_root(workspace, adapter, performer_id)
    effective_timeout = max(timeout_seconds, _BUILTIN_SOURCE_TIMEOUT_SECONDS)
    observations: list[Observation] = []

    for index, source in enumerate(sources):
        performer_count = counts[index]
        fingerprint = _source_fingerprint(
            source=source,
            performer_id=performer_id,
            performer_count=performer_count,
            adapter=adapter,
            revision=revision,
        )
        checkpoint = root / f"{fingerprint}.json"
        cached = _load_checkpoint(
            checkpoint,
            fingerprint=fingerprint,
            source=source,
            adapter=adapter,
            revision=revision,
        )
        if cached is not None:
            observations.extend(cached)
            continue

        # The built-in adapter deliberately skips multi-performer scenes because
        # HOG/Haar cannot prove which detected person is the named performer.
        # Cache that deterministic empty result without launching OpenCV.
        if performer_count != 1:
            _write_checkpoint(
                checkpoint,
                fingerprint=fingerprint,
                observations=[],
                source_id=str(source["source_id"]),
                adapter=adapter,
                revision=revision,
            )
            continue

        current = _run_single_source(
            command,
            source=source,
            performer_id=performer_id,
            source_manifest_sha256=source_manifest_sha256,
            workspace=workspace,
            adapter=adapter,
            revision=revision,
            timeout_seconds=effective_timeout,
            manifest_value_index=manifest_value_index,
            manifest=manifest,
            manifest_selected_index=index,
        )
        _write_checkpoint(
            checkpoint,
            fingerprint=fingerprint,
            observations=current,
            source_id=str(source["source_id"]),
            adapter=adapter,
            revision=revision,
        )
        observations.extend(current)

    if not observations:
        raise ObservationError("OpenCV observation analyzer found no usable single-performer observation")
    return observations


def _run_one_shot(
    command: Sequence[str],
    *,
    sources: Sequence[Mapping[str, Any]],
    performer_id: str,
    source_manifest_sha256: str,
    workspace: Path,
    adapter: str,
    revision: str,
    timeout_seconds: int,
) -> list[Observation]:
    request = build_analyzer_request(
        sources=sources,
        performer_id=performer_id,
        source_manifest_sha256=source_manifest_sha256,
    )
    with tempfile.TemporaryDirectory(prefix="bodyrig-observation-analyzer-") as temp_name:
        temp = Path(temp_name)
        request_path = temp / "request.json"
        output_dir = temp / "output"
        log_path = temp / "adapter.log"
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        output_dir.mkdir()
        invoke = [
            *command,
            "--bodyrig-request",
            str(request_path),
            "--bodyrig-workspace",
            str(workspace),
            "--bodyrig-output",
            str(output_dir),
            "--bodyrig-adapter",
            adapter,
            "--bodyrig-revision",
            revision,
        ]
        for source in sources:
            invoke.extend(
                [
                    "--bodyrig-source-id",
                    str(source["source_id"]),
                    "--bodyrig-source-path",
                    str(source["path"]),
                ]
            )
        try:
            completed = run_logged_process(invoke, log_path=log_path, timeout_seconds=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            detail = _read_log_tail(log_path)
            suffix = f" | log tail: {detail}" if detail else ""
            raise ObservationError(f"observation analyzer timed out after {timeout_seconds} seconds{suffix}") from exc
        except OSError as exc:
            detail = _read_log_tail(log_path)
            suffix = f" | log tail: {detail}" if detail else ""
            raise ObservationError(f"observation analyzer process could not complete: {exc}{suffix}") from exc
        if completed.returncode != 0:
            detail = _read_log_tail(log_path)
            suffix = f": {detail}" if detail else ""
            raise ObservationError(f"observation analyzer failed with exit code {completed.returncode}{suffix}")
        children = list(output_dir.iterdir())
        if {item.name for item in children} != {"observations.json"} or any(not item.is_file() for item in children):
            raise ObservationError("observation analyzer output must contain exactly observations.json")
        return validate_analyzer_result(
            output_dir / "observations.json",
            sources=sources,
            expected_adapter=adapter,
            expected_revision=revision,
        )


def run_external_analyzer(
    command: Sequence[str],
    *,
    sources: Sequence[Mapping[str, Any]],
    performer_id: str,
    source_manifest_sha256: str,
    workspace: str | Path,
    adapter: str,
    revision: str,
    timeout_seconds: int = 3600,
) -> list[Observation]:
    argv = list(command)
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise ObservationError("observation analyzer command must contain non-empty argv entries")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 86400:
        raise ObservationError("observation analyzer timeout_seconds must be in 1..86400")
    if not adapter or len(adapter) > 80 or not all(ch.isalnum() or ch in "._-" for ch in adapter):
        raise ObservationError("observation analyzer adapter id is invalid")
    if not revision or len(revision) > 160:
        raise ObservationError("observation analyzer revision is invalid")
    workspace_path = Path(workspace).expanduser().resolve()
    if not workspace_path.is_dir():
        raise ObservationError(f"observation private workspace not found: {workspace_path}")

    if adapter == _BUILTIN_ADAPTER:
        checkpointed = _run_checkpointed_builtin(
            argv,
            sources=sources,
            performer_id=performer_id,
            source_manifest_sha256=source_manifest_sha256,
            workspace=workspace_path,
            adapter=adapter,
            revision=revision,
            timeout_seconds=timeout_seconds,
        )
        if checkpointed is not None:
            return checkpointed

    return _run_one_shot(
        argv,
        sources=sources,
        performer_id=performer_id,
        source_manifest_sha256=source_manifest_sha256,
        workspace=workspace_path,
        adapter=adapter,
        revision=revision,
        timeout_seconds=timeout_seconds,
    )

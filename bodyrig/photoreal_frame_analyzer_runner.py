from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .logged_process import LoggedProcessError, run_logged_process

CONFIG_FORMAT = "bodyrig-photoreal-frame-analyzer-config"
CONFIG_VERSION = 1
SCAN_FORMAT = "bodyrig-photoreal-scan-plan"
SCAN_VERSION = 1
REQUEST_FORMAT = "bodyrig-photoreal-frame-analyzer-request"
REQUEST_VERSION = 1
RESULT_FORMAT = "bodyrig-photoreal-frame-observations"
RESULT_VERSION = 1


class PhotorealFrameAnalyzerError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealFrameAnalyzerError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealFrameAnalyzerError(f"{label} must be a JSON object")
    return value


def load_analyzer_config(path: str | Path) -> dict[str, Any]:
    value = _read_json(path, label="photoreal frame analyzer config")
    required = {"format", "version", "adapter", "revision", "command", "timeout_seconds"}
    if set(value) != required:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer config fields must match v1 exactly")
    version = value.get("version")
    if value.get("format") != CONFIG_FORMAT or isinstance(version, bool) or version != CONFIG_VERSION:
        raise PhotorealFrameAnalyzerError("unsupported photoreal frame analyzer config format/version")
    adapter = str(value.get("adapter") or "").strip()
    revision = str(value.get("revision") or "").strip()
    if not adapter or len(adapter) > 80 or any(not (ch.isalnum() or ch in "._-") for ch in adapter):
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer adapter is invalid")
    if not revision or len(revision) > 160:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer revision is invalid")
    command = value.get("command")
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 64
        or any(not isinstance(item, str) or not item or len(item) > 4096 for item in command)
    ):
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer command must be a non-empty argv list")
    timeout = value.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer timeout_seconds must be in 1..86400")
    return {
        "format": CONFIG_FORMAT,
        "version": CONFIG_VERSION,
        "adapter": adapter,
        "revision": revision,
        "command": list(command),
        "timeout_seconds": timeout,
    }


def _validate_scan_plan(scan_plan: Mapping[str, Any]) -> None:
    if scan_plan.get("format") != SCAN_FORMAT or scan_plan.get("version") != SCAN_VERSION:
        raise PhotorealFrameAnalyzerError("photoreal scan plan format/version mismatch")
    if scan_plan.get("all_sources_sha256_bound") is not True:
        raise PhotorealFrameAnalyzerError("photoreal scan plan is not byte-bound")
    if scan_plan.get("train_evaluation_assignment_inherited") is not True:
        raise PhotorealFrameAnalyzerError("photoreal scan plan lost train/evaluation assignment")
    if scan_plan.get("frame_analyzer_required") is not True:
        raise PhotorealFrameAnalyzerError("photoreal scan plan does not require frame analysis")
    if scan_plan.get("teacher_training_authorized") is not False:
        raise PhotorealFrameAnalyzerError("frame analyzer cannot accept an already-authorized teacher plan")
    if scan_plan.get("build_only") is not True or scan_plan.get("runtime_dependency") is not False:
        raise PhotorealFrameAnalyzerError("photoreal scan plan authority boundary is invalid")
    if scan_plan.get("production_activation") is not False:
        raise PhotorealFrameAnalyzerError("photoreal scan plan crossed production authority")
    sources = scan_plan.get("sources")
    if not isinstance(sources, list) or not sources:
        raise PhotorealFrameAnalyzerError("photoreal scan plan contains no sources")


def build_analyzer_request(
    scan_plan: Mapping[str, Any],
    *,
    adapter: str,
    revision: str,
) -> dict[str, Any]:
    _validate_scan_plan(scan_plan)
    performer_id = str(scan_plan.get("performer_id") or "").strip()
    if not performer_id:
        raise PhotorealFrameAnalyzerError("photoreal scan plan performer_id is missing")
    return {
        "format": REQUEST_FORMAT,
        "version": REQUEST_VERSION,
        "adapter": adapter,
        "revision": revision,
        "performer_id": performer_id,
        "strategy": str(scan_plan.get("strategy") or ""),
        "sources": scan_plan["sources"],
        "build_only": True,
        "measurement_only": True,
        "train_evaluation_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def _log_tail(path: Path, limit: int = 6000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[-limit:].decode("utf-8", errors="replace").strip()


def validate_analyzer_result(
    value: Mapping[str, Any],
    *,
    performer_id: str,
    adapter: str,
    revision: str,
) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "performer_id",
        "analyzer",
        "analyzer_revision",
        "observations",
        "build_only",
        "production_activation",
    }
    if set(value) != required:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer result fields must match v1 exactly")
    version = value.get("version")
    if value.get("format") != RESULT_FORMAT or isinstance(version, bool) or version != RESULT_VERSION:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer result format/version mismatch")
    if str(value.get("performer_id") or "").strip() != performer_id:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer result performer mismatch")
    if value.get("analyzer") != adapter or value.get("analyzer_revision") != revision:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer result provenance mismatch")
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer returned no observations")
    if value.get("build_only") is not True or value.get("production_activation") is not False:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer crossed its authority boundary")
    return dict(value)


def run_external_frame_analyzer(
    config: Mapping[str, Any],
    scan_plan: Mapping[str, Any],
    *,
    workspace: str | Path,
) -> dict[str, Any]:
    adapter = str(config.get("adapter") or "").strip()
    revision = str(config.get("revision") or "").strip()
    command = config.get("command")
    timeout = config.get("timeout_seconds")
    if not adapter or not revision or not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer config is invalid")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer timeout is invalid")

    request = build_analyzer_request(scan_plan, adapter=adapter, revision=revision)
    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealFrameAnalyzerError(f"photoreal frame analyzer workspace already exists: {root}")
    root.mkdir(parents=True)

    request_path = root / "request.json"
    output_dir = root / "output"
    log_path = root / "adapter.log"
    output_dir.mkdir()
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    invoke = [
        *list(command),
        "--bodyrig-request",
        str(request_path),
        "--bodyrig-output",
        str(output_dir),
        "--bodyrig-adapter",
        adapter,
        "--bodyrig-revision",
        revision,
    ]
    try:
        completed = run_logged_process(invoke, log_path=log_path, timeout_seconds=timeout)
    except subprocess.TimeoutExpired as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealFrameAnalyzerError(
            f"photoreal frame analyzer timed out after {timeout} seconds{suffix}"
        ) from exc
    except (OSError, LoggedProcessError) as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealFrameAnalyzerError(
            f"photoreal frame analyzer process could not complete: {exc}{suffix}"
        ) from exc
    if completed.returncode != 0:
        detail = _log_tail(log_path)
        suffix = f": {detail}" if detail else ""
        raise PhotorealFrameAnalyzerError(
            f"photoreal frame analyzer failed with exit code {completed.returncode}{suffix}"
        )

    children = list(output_dir.iterdir())
    if {item.name for item in children} != {"observations.json"} or any(not item.is_file() for item in children):
        raise PhotorealFrameAnalyzerError(
            "photoreal frame analyzer output must contain exactly observations.json"
        )
    result = _read_json(output_dir / "observations.json", label="photoreal frame analyzer result")
    return validate_analyzer_result(
        result,
        performer_id=str(scan_plan.get("performer_id") or "").strip(),
        adapter=adapter,
        revision=revision,
    )


def run_external_frame_analyzer_files(
    config_path: str | Path,
    scan_plan_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = load_analyzer_config(config_path)
    scan_plan = _read_json(scan_plan_path, label="photoreal scan plan")
    return run_external_frame_analyzer(config, scan_plan, workspace=workspace)

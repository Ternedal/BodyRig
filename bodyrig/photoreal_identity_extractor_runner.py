from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from .logged_process import LoggedProcessError, run_logged_process

CONFIG_FORMAT = "bodyrig-photoreal-identity-extractor-config"
CONFIG_VERSION = 1
BOOTSTRAP_FORMAT = "bodyrig-photoreal-identity-bootstrap-plan"
BOOTSTRAP_VERSION = 1
MODEL_SET_FORMAT = "bodyrig-photoreal-analyzer-model-set"
MODEL_SET_VERSION = 1
REQUEST_FORMAT = "bodyrig-photoreal-identity-extractor-request"
REQUEST_VERSION = 1
RESULT_FORMAT = "bodyrig-photoreal-identity-reference-observations"
RESULT_VERSION = 1


class PhotorealIdentityExtractorError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealIdentityExtractorError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityExtractorError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealIdentityExtractorError(f"{label} is invalid")
    return result


def load_identity_extractor_config(path: str | Path) -> dict[str, Any]:
    value = _read_json(path, label="photoreal identity extractor config")
    required = {"format", "version", "adapter", "revision", "model_set_sha256", "command", "timeout_seconds"}
    if set(value) != required:
        raise PhotorealIdentityExtractorError("photoreal identity extractor config fields must match v1 exactly")
    version = value.get("version")
    if value.get("format") != CONFIG_FORMAT or isinstance(version, bool) or version != CONFIG_VERSION:
        raise PhotorealIdentityExtractorError("unsupported photoreal identity extractor config format/version")
    adapter = str(value.get("adapter") or "").strip()
    revision = str(value.get("revision") or "").strip()
    if not adapter or len(adapter) > 80 or any(not (ch.isalnum() or ch in "._-") for ch in adapter):
        raise PhotorealIdentityExtractorError("photoreal identity extractor adapter is invalid")
    if not revision or len(revision) > 160:
        raise PhotorealIdentityExtractorError("photoreal identity extractor revision is invalid")
    model_set_sha256 = _sha(value.get("model_set_sha256"), label="identity extractor model-set SHA-256")
    command = value.get("command")
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 64
        or any(not isinstance(item, str) or not item or len(item) > 4096 for item in command)
    ):
        raise PhotorealIdentityExtractorError("photoreal identity extractor command must be a non-empty argv list")
    timeout = value.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
        raise PhotorealIdentityExtractorError("photoreal identity extractor timeout_seconds must be in 1..86400")
    return {
        "format": CONFIG_FORMAT,
        "version": CONFIG_VERSION,
        "adapter": adapter,
        "revision": revision,
        "model_set_sha256": model_set_sha256,
        "command": list(command),
        "timeout_seconds": timeout,
    }


def _validate_bootstrap(bootstrap: Mapping[str, Any]) -> None:
    if bootstrap.get("format") != BOOTSTRAP_FORMAT or bootstrap.get("version") != BOOTSTRAP_VERSION:
        raise PhotorealIdentityExtractorError("identity bootstrap format/version mismatch")
    if bootstrap.get("train_only") is not True or bootstrap.get("evaluation_source_count") != 0:
        raise PhotorealIdentityExtractorError("identity extractor requires train-only bootstrap input")
    if bootstrap.get("source_bytes_bound") is not True or bootstrap.get("identity_bank_build_authorized") is not True:
        raise PhotorealIdentityExtractorError("identity bootstrap lacks source/bank authority")
    if bootstrap.get("teacher_training_authorized") is not False:
        raise PhotorealIdentityExtractorError("identity bootstrap crossed teacher-training authority")
    if bootstrap.get("build_only") is not True or bootstrap.get("runtime_dependency") is not False:
        raise PhotorealIdentityExtractorError("identity bootstrap authority boundary is invalid")
    if bootstrap.get("production_activation") is not False:
        raise PhotorealIdentityExtractorError("identity bootstrap crossed production authority")
    sources = bootstrap.get("sources")
    if not isinstance(sources, list) or not sources:
        raise PhotorealIdentityExtractorError("identity bootstrap contains no sources")


def _model_set_sha(model_set: Mapping[str, Any]) -> str:
    if model_set.get("format") != MODEL_SET_FORMAT or model_set.get("version") != MODEL_SET_VERSION:
        raise PhotorealIdentityExtractorError("identity model-set format/version mismatch")
    if model_set.get("build_only") is not True or model_set.get("runtime_dependency") is not False:
        raise PhotorealIdentityExtractorError("identity model-set authority boundary is invalid")
    if model_set.get("production_activation") is not False:
        raise PhotorealIdentityExtractorError("identity model-set crossed production authority")
    return _sha(model_set.get("model_set_sha256"), label="identity model-set SHA-256")


def build_identity_extractor_request(
    bootstrap: Mapping[str, Any],
    model_set: Mapping[str, Any],
    *,
    adapter: str,
    revision: str,
    expected_model_set_sha256: str,
) -> dict[str, Any]:
    _validate_bootstrap(bootstrap)
    model_set_sha256 = _model_set_sha(model_set)
    if model_set_sha256 != expected_model_set_sha256:
        raise PhotorealIdentityExtractorError("identity extractor config targets a different model set")
    return {
        "format": REQUEST_FORMAT,
        "version": REQUEST_VERSION,
        "adapter": adapter,
        "revision": revision,
        "model_set_sha256": model_set_sha256,
        "performer_id": str(bootstrap.get("performer_id") or ""),
        "sources": bootstrap["sources"],
        "measurement_only": True,
        "train_only": True,
        "identity_matching_authority": False,
        "teacher_training_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def _log_tail(path: Path, limit: int = 6000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[-limit:].decode("utf-8", errors="replace").strip()


def validate_identity_extractor_result(
    value: Mapping[str, Any],
    *,
    performer_id: str,
    adapter: str,
    revision: str,
    model_set_sha256: str,
) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "performer_id",
        "extractor",
        "extractor_revision",
        "model_set_sha256",
        "embedding_dimension",
        "observations",
        "build_only",
        "production_activation",
    }
    if set(value) != required:
        raise PhotorealIdentityExtractorError("identity extractor result fields must match v1 exactly")
    version = value.get("version")
    if value.get("format") != RESULT_FORMAT or isinstance(version, bool) or version != RESULT_VERSION:
        raise PhotorealIdentityExtractorError("identity extractor result format/version mismatch")
    if str(value.get("performer_id") or "").strip() != performer_id:
        raise PhotorealIdentityExtractorError("identity extractor result performer mismatch")
    if value.get("extractor") != adapter or value.get("extractor_revision") != revision:
        raise PhotorealIdentityExtractorError("identity extractor result provenance mismatch")
    if _sha(value.get("model_set_sha256"), label="result model-set SHA-256") != model_set_sha256:
        raise PhotorealIdentityExtractorError("identity extractor result model-set mismatch")
    dimension = value.get("embedding_dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or not 32 <= dimension <= 4096:
        raise PhotorealIdentityExtractorError("identity extractor result embedding_dimension is invalid")
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise PhotorealIdentityExtractorError("identity extractor returned no observations")
    if value.get("build_only") is not True or value.get("production_activation") is not False:
        raise PhotorealIdentityExtractorError("identity extractor crossed its authority boundary")
    return dict(value)


def run_external_identity_extractor(
    config: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
    model_set: Mapping[str, Any],
    *,
    workspace: str | Path,
) -> dict[str, Any]:
    adapter = str(config.get("adapter") or "").strip()
    revision = str(config.get("revision") or "").strip()
    model_set_sha256 = _sha(config.get("model_set_sha256"), label="identity extractor config model-set SHA-256")
    command = config.get("command")
    timeout = config.get("timeout_seconds")
    if not adapter or not revision or not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
        raise PhotorealIdentityExtractorError("identity extractor config is invalid")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise PhotorealIdentityExtractorError("identity extractor timeout is invalid")

    request = build_identity_extractor_request(
        bootstrap,
        model_set,
        adapter=adapter,
        revision=revision,
        expected_model_set_sha256=model_set_sha256,
    )
    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealIdentityExtractorError(f"identity extractor workspace already exists: {root}")
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
        "--bodyrig-model-set-sha256",
        model_set_sha256,
    ]
    try:
        completed = run_logged_process(invoke, log_path=log_path, timeout_seconds=timeout)
    except subprocess.TimeoutExpired as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealIdentityExtractorError(
            f"identity extractor timed out after {timeout} seconds{suffix}"
        ) from exc
    except (OSError, LoggedProcessError) as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealIdentityExtractorError(
            f"identity extractor process could not complete: {exc}{suffix}"
        ) from exc
    if completed.returncode != 0:
        detail = _log_tail(log_path)
        suffix = f": {detail}" if detail else ""
        raise PhotorealIdentityExtractorError(
            f"identity extractor failed with exit code {completed.returncode}{suffix}"
        )

    children = list(output_dir.iterdir())
    if {item.name for item in children} != {"identity-observations.json"} or any(not item.is_file() for item in children):
        raise PhotorealIdentityExtractorError(
            "identity extractor output must contain exactly identity-observations.json"
        )
    result = _read_json(output_dir / "identity-observations.json", label="identity extractor result")
    return validate_identity_extractor_result(
        result,
        performer_id=str(bootstrap.get("performer_id") or "").strip(),
        adapter=adapter,
        revision=revision,
        model_set_sha256=model_set_sha256,
    )


def run_external_identity_extractor_files(
    config_path: str | Path,
    bootstrap_path: str | Path,
    model_set_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = load_identity_extractor_config(config_path)
    bootstrap = _read_json(bootstrap_path, label="identity bootstrap plan")
    model_set = _read_json(model_set_path, label="identity model set")
    return run_external_identity_extractor(config, bootstrap, model_set, workspace=workspace)

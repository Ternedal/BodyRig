from __future__ import annotations

import json
import math
import subprocess
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
MAX_OBSERVATIONS = 250_000
_VALID_VIEW_BINS = {
    "front",
    "three-quarter-right",
    "three-quarter-left",
    "profile-right",
    "profile-left",
    "rear",
    "unknown",
}
_MEASUREMENT_UNIT_FIELDS = (
    "face_visibility",
    "full_body_visibility",
    "person_fraction",
    "sharpness",
    "motion",
    "occlusion",
)
_OBSERVATION_FIELDS = frozenset(
    {
        "source_key",
        "source_sha256",
        "kind",
        "timestamp_seconds",
        "eye",
        "projection",
        "frame_sha256",
        "perceptual_hash",
        "candidate_id",
        "person_detected",
        "width",
        "height",
        "view_bin",
        "face_visibility",
        "full_body_visibility",
        "person_fraction",
        "sharpness",
        "motion",
        "occlusion",
        "identity_measurement_status",
        "identity_embedding",
    }
)


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


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealFrameAnalyzerError(f"{label} is invalid")
    return result


def _finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealFrameAnalyzerError(f"{label} is invalid")
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise PhotorealFrameAnalyzerError(f"{label} is invalid") from exc
    if not math.isfinite(numeric):
        raise PhotorealFrameAnalyzerError(f"{label} is not finite")
    return numeric


def _validate_unit_measurement(value: Any, *, label: str) -> None:
    numeric = _finite_number(value, label=label)
    if not 0.0 <= numeric <= 1.0:
        raise PhotorealFrameAnalyzerError(f"{label} is outside 0..1")


def load_analyzer_config(path: str | Path) -> dict[str, Any]:
    value = _read_json(path, label="photoreal frame analyzer config")
    required = {
        "format",
        "version",
        "adapter",
        "revision",
        "model_set_sha256",
        "command",
        "timeout_seconds",
    }
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
    model_set_sha256 = _sha(value.get("model_set_sha256"), label="photoreal analyzer model-set SHA-256")
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
        "model_set_sha256": model_set_sha256,
        "command": list(command),
        "timeout_seconds": timeout,
    }


def _validate_scan_plan(scan_plan: Mapping[str, Any]) -> None:
    version = scan_plan.get("version")
    if scan_plan.get("format") != SCAN_FORMAT or isinstance(version, bool) or version != SCAN_VERSION:
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


def _sample_identity(timestamp: Any, eye: Any, *, kind: str) -> tuple[str, str]:
    eye_value = str(eye or "").strip()
    if eye_value not in {"mono", "left", "right"}:
        raise PhotorealFrameAnalyzerError("photoreal frame sample eye is invalid")
    if kind == "image":
        if timestamp is not None or eye_value != "mono":
            raise PhotorealFrameAnalyzerError("still-image frame sample must be mono without timestamp")
        return "image", eye_value
    if kind != "video":
        raise PhotorealFrameAnalyzerError("photoreal video frame sample timestamp is invalid")
    numeric = _finite_number(timestamp, label="photoreal video frame sample timestamp")
    if numeric < 0.0:
        raise PhotorealFrameAnalyzerError("photoreal video frame sample timestamp is invalid")
    return f"{numeric:.6f}", eye_value


def _expected_scan_samples(scan_plan: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], set[tuple[str, str, str]]]:
    _validate_scan_plan(scan_plan)
    result: dict[str, dict[str, Any]] = {}
    expected_samples: set[tuple[str, str, str]] = set()
    for raw_source in scan_plan["sources"]:
        if not isinstance(raw_source, Mapping):
            raise PhotorealFrameAnalyzerError("photoreal scan plan contains an invalid source")
        source_key = str(raw_source.get("source_key") or "").strip()
        if not source_key or source_key in result:
            raise PhotorealFrameAnalyzerError("photoreal scan plan source_key is missing or repeated")
        kind = str(raw_source.get("kind") or "").strip()
        if kind not in {"video", "image"}:
            raise PhotorealFrameAnalyzerError("photoreal scan plan source kind is invalid")
        projection = str(raw_source.get("projection") or "").strip()
        if not projection or len(projection) > 128:
            raise PhotorealFrameAnalyzerError("photoreal scan plan source projection is invalid")
        source_sha = _sha(raw_source.get("source_sha256"), label="photoreal scan-plan source SHA-256")
        samples = raw_source.get("samples")
        if not isinstance(samples, list) or not samples:
            raise PhotorealFrameAnalyzerError("photoreal scan plan source contains no samples")
        sample_count = raw_source.get("sample_count")
        if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count != len(samples):
            raise PhotorealFrameAnalyzerError("photoreal scan plan source sample_count mismatch")
        source_samples: set[tuple[str, str]] = set()
        for raw_sample in samples:
            if not isinstance(raw_sample, Mapping):
                raise PhotorealFrameAnalyzerError("photoreal scan plan contains an invalid sample")
            sample = _sample_identity(raw_sample.get("timestamp_seconds"), raw_sample.get("eye"), kind=kind)
            if sample in source_samples:
                raise PhotorealFrameAnalyzerError("photoreal scan plan repeats a source sample")
            source_samples.add(sample)
            expected_samples.add((source_key, sample[0], sample[1]))
        result[source_key] = {
            "sha256": source_sha,
            "kind": kind,
            "projection": projection,
            "samples": source_samples,
        }
    return result, expected_samples


def build_analyzer_request(
    scan_plan: Mapping[str, Any],
    *,
    adapter: str,
    revision: str,
    model_set_sha256: str,
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
        "model_set_sha256": _sha(model_set_sha256, label="photoreal analyzer model-set SHA-256"),
        "performer_id": performer_id,
        "strategy": str(scan_plan.get("strategy") or ""),
        "sources": scan_plan["sources"],
        "build_only": True,
        "measurement_only": True,
        "identity_measurement_only": True,
        "identity_matching_authority": False,
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
    model_set_sha256: str,
    scan_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "performer_id",
        "analyzer",
        "analyzer_revision",
        "analyzer_model_set_sha256",
        "identity_embedding_dimension",
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
    observed_model_sha = _sha(
        value.get("analyzer_model_set_sha256"),
        label="photoreal analyzer result model-set SHA-256",
    )
    expected_model_sha = _sha(model_set_sha256, label="photoreal analyzer model-set SHA-256")
    if observed_model_sha != expected_model_sha:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer result model-set provenance mismatch")
    dimension = value.get("identity_embedding_dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or not 32 <= dimension <= 4096:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer identity_embedding_dimension is invalid")
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer returned no observations")
    if len(observations) > MAX_OBSERVATIONS:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer returned too many observations")
    if value.get("build_only") is not True or value.get("production_activation") is not False:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer crossed its authority boundary")

    if scan_plan is None:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer result validation requires the exact scan plan")
    expected_sources, expected_samples = _expected_scan_samples(scan_plan)

    seen_candidates: set[tuple[str, str, str, str]] = set()
    observed_samples: set[tuple[str, str, str]] = set()
    for raw in observations:
        if not isinstance(raw, Mapping):
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer returned a non-object observation")
        if "target_identity_verified" in raw or "identity_confidence" in raw or "identity_authority" in raw:
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer attempted to assert identity authority")
        if set(raw) - _OBSERVATION_FIELDS:
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer observation contains unsupported fields")
        candidate_id = str(raw.get("candidate_id") or "").strip()
        if (
            not candidate_id
            or len(candidate_id) > 128
            or any(not (character.isalnum() or character in "._-") for character in candidate_id)
        ):
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer candidate_id is invalid")
        person_detected = raw.get("person_detected")
        if not isinstance(person_detected, bool):
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer person_detected must be boolean")
        source_key = str(raw.get("source_key") or "").strip()
        eye = str(raw.get("eye") or "").strip()
        timestamp = raw.get("timestamp_seconds")
        frame_sha = _sha(raw.get("frame_sha256"), label="photoreal frame SHA-256")
        expected_source = expected_sources.get(source_key)
        if expected_source is None:
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer returned an unknown scan-plan source")
        if _sha(raw.get("source_sha256"), label="photoreal frame source SHA-256") != expected_source["sha256"]:
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer source SHA-256 differs from scan plan")
        kind = str(raw.get("kind") or "").strip()
        if kind != expected_source["kind"]:
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer source kind differs from scan plan")
        projection = str(raw.get("projection") or "").strip()
        if projection != expected_source["projection"]:
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer projection differs from scan plan")
        sample = _sample_identity(timestamp, eye, kind=kind)
        if sample not in expected_source["samples"]:
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer returned an unplanned source sample")
        observed_samples.add((source_key, sample[0], sample[1]))
        candidate_key = (source_key, sample[0], sample[1], candidate_id)
        if candidate_key in seen_candidates:
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer repeated candidate_id within one sample")
        seen_candidates.add(candidate_key)

        width = raw.get("width")
        height = raw.get("height")
        if isinstance(width, bool) or not isinstance(width, int) or width < 1:
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer width is invalid")
        if isinstance(height, bool) or not isinstance(height, int) or height < 1:
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer height is invalid")

        perceptual_hash = raw.get("perceptual_hash")
        if (
            not isinstance(perceptual_hash, str)
            or len(perceptual_hash) != 16
            or any(character not in "0123456789abcdef" for character in perceptual_hash)
        ):
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer perceptual_hash is invalid")

        view_bin = raw.get("view_bin")
        if not isinstance(view_bin, str) or view_bin not in _VALID_VIEW_BINS:
            raise PhotorealFrameAnalyzerError("photoreal frame analyzer view_bin is invalid")

        for field in _MEASUREMENT_UNIT_FIELDS:
            _validate_unit_measurement(
                raw.get(field),
                label=f"photoreal frame analyzer {field}",
            )

        status = raw.get("identity_measurement_status")
        embedding = raw.get("identity_embedding")
        if status == "available":
            if not person_detected:
                raise PhotorealFrameAnalyzerError("available identity embedding requires a detected person")
            if not isinstance(embedding, list) or len(embedding) != dimension:
                raise PhotorealFrameAnalyzerError("available identity embedding has wrong dimension")
            for component in embedding:
                _finite_number(component, label="available identity embedding component")
        elif status == "unavailable":
            if embedding is not None:
                raise PhotorealFrameAnalyzerError("unavailable identity measurement must have null embedding")
        else:
            raise PhotorealFrameAnalyzerError("identity_measurement_status is invalid")
        if not person_detected and status != "unavailable":
            raise PhotorealFrameAnalyzerError("non-person placeholder cannot expose an identity embedding")
        _ = frame_sha
    if observed_samples != expected_samples:
        missing = len(expected_samples - observed_samples)
        unexpected = len(observed_samples - expected_samples)
        raise PhotorealFrameAnalyzerError(
            f"photoreal frame analyzer did not return exactly the planned sample set (missing={missing}, unexpected={unexpected})"
        )
    return dict(value)


def run_external_frame_analyzer(
    config: Mapping[str, Any],
    scan_plan: Mapping[str, Any],
    *,
    workspace: str | Path,
) -> dict[str, Any]:
    adapter = str(config.get("adapter") or "").strip()
    revision = str(config.get("revision") or "").strip()
    model_set_sha256 = _sha(config.get("model_set_sha256"), label="photoreal analyzer model-set SHA-256")
    command = config.get("command")
    timeout = config.get("timeout_seconds")
    if not adapter or not revision or not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer config is invalid")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise PhotorealFrameAnalyzerError("photoreal frame analyzer timeout is invalid")

    request = build_analyzer_request(
        scan_plan,
        adapter=adapter,
        revision=revision,
        model_set_sha256=model_set_sha256,
    )
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
        "--bodyrig-model-set-sha256",
        model_set_sha256,
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
        model_set_sha256=model_set_sha256,
        scan_plan=scan_plan,
    )


def run_external_frame_analyzer_files(
    config_path: str | Path,
    scan_plan_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = load_analyzer_config(config_path)
    scan_plan = _read_json(scan_plan_path, label="photoreal scan plan")
    return run_external_frame_analyzer(config, scan_plan, workspace=workspace)

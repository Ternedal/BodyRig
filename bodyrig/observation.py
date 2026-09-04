from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ANALYZER_REQUEST_FORMAT = "bodyrig-observation-analyzer-request"
ANALYZER_RESULT_FORMAT = "bodyrig-observation-analyzer-result"
SELECTION_FORMAT = "bodyrig-observation-selection"
SEGMENTS_FORMAT = "bodyrig-observation-segments"
VERSION = 1
VIEWS = {"front", "left_profile", "right_profile", "rear", "unknown"}


class ObservationError(ValueError):
    pass


@dataclass(frozen=True)
class Observation:
    source_id: str
    start_seconds: float
    duration_seconds: float
    target_confidence: float
    target_screen_fraction: float
    face_visibility: float
    full_body_visibility: float
    sharpness: float
    occlusion: float
    motion: float
    view: str
    base_score: float

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + self.duration_seconds

    def to_json(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "start_seconds": round(self.start_seconds, 3),
            "duration_seconds": round(self.duration_seconds, 3),
            "target_confidence": round(self.target_confidence, 4),
            "target_screen_fraction": round(self.target_screen_fraction, 4),
            "face_visibility": round(self.face_visibility, 4),
            "full_body_visibility": round(self.full_body_visibility, 4),
            "sharpness": round(self.sharpness, 4),
            "occlusion": round(self.occlusion, 4),
            "motion": round(self.motion, 4),
            "view": self.view,
            "base_score": round(self.base_score, 4),
        }


def _finite(value: Any, *, label: str, minimum: float = 0.0, maximum: float = 1.0) -> float:
    if isinstance(value, bool):
        raise ObservationError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ObservationError(f"{label} must be a finite number") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ObservationError(f"{label} must be in {minimum}..{maximum}")
    return result


def _positive(value: Any, *, label: str, maximum: float) -> float:
    if isinstance(value, bool):
        raise ObservationError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ObservationError(f"{label} must be a finite number") from exc
    if not math.isfinite(result) or result < 0.0 or result > maximum:
        raise ObservationError(f"{label} must be in 0..{maximum}")
    return result


def load_stash_source_manifest(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise ObservationError(f"Stash source manifest not found: {source_path}")
    raw = source_path.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ObservationError("Stash source manifest is invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise ObservationError("Stash source manifest must be an object")
    if manifest.get("format") != "bodyrig-stash-source-manifest" or manifest.get("version") != 1:
        raise ObservationError("unsupported Stash source manifest format/version")
    if manifest.get("source_kind") != "stash-local":
        raise ObservationError("observation selection currently requires stash-local sources")
    selected = manifest.get("selected")
    if not isinstance(selected, list) or not 1 <= len(selected) <= 10:
        raise ObservationError("Stash source manifest selected must contain 1..10 entries")

    normalized: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, item in enumerate(selected, start=1):
        if not isinstance(item, Mapping):
            raise ObservationError("Stash selected entry must be an object")
        scene_id = str(item.get("scene_id") or "").strip()
        raw_path = str(item.get("path") or "").strip()
        if not scene_id or not raw_path:
            raise ObservationError("Stash selected entry scene_id/path are required")
        file_path = Path(raw_path).expanduser().resolve()
        if not file_path.is_file():
            raise ObservationError(f"Stash selected source is not a local file: {file_path}")
        key = os.path.normcase(str(file_path))
        if key in seen_paths:
            raise ObservationError("Stash source manifest contains duplicate local paths")
        seen_paths.add(key)
        duration = _positive(item.get("duration"), label="source duration", maximum=172800.0)
        if duration < 1.0:
            raise ObservationError("source duration must be at least one second")
        normalized.append(
            {
                "source_id": f"s{index:03d}",
                "scene_id": scene_id,
                "path": str(file_path),
                "duration": duration,
            }
        )
    return manifest, normalized, hashlib.sha256(raw).hexdigest()


def build_analyzer_request(
    *,
    sources: Sequence[Mapping[str, Any]],
    performer_id: str,
    source_manifest_sha256: str,
) -> dict[str, Any]:
    performer_id = str(performer_id).strip()
    if not performer_id:
        raise ObservationError("performer id is required")
    return {
        "format": ANALYZER_REQUEST_FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "source_manifest_sha256": source_manifest_sha256,
        "sources": [
            {
                "source_id": str(source["source_id"]),
                "scene_id": str(source["scene_id"]),
                "duration": round(float(source["duration"]), 3),
            }
            for source in sources
        ],
    }


def _base_score(values: Mapping[str, float]) -> float:
    # Identity confidence and sharpness dominate. Face and full-body visibility
    # deliberately have similar weight: BodyRig needs both appearance and shape.
    positive = (
        0.24 * values["target_confidence"]
        + 0.12 * values["target_screen_fraction"]
        + 0.17 * values["face_visibility"]
        + 0.17 * values["full_body_visibility"]
        + 0.18 * values["sharpness"]
        + 0.12 * values["motion"]
    )
    return max(0.0, min(1.0, positive - 0.22 * values["occlusion"]))


def validate_analyzer_result(
    path: str | Path,
    *,
    sources: Sequence[Mapping[str, Any]],
    expected_adapter: str,
    expected_revision: str,
) -> list[Observation]:
    result_path = Path(path).expanduser().resolve()
    if not result_path.is_file():
        raise ObservationError("observation analyzer did not return observations.json")
    try:
        result = json.loads(
            result_path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ObservationError("observation analyzer result is invalid JSON") from exc
    if not isinstance(result, dict) or set(result) != {"format", "version", "adapter", "revision", "observations"}:
        raise ObservationError("observation analyzer result fields must match v1 exactly")
    if result["format"] != ANALYZER_RESULT_FORMAT or result["version"] != VERSION:
        raise ObservationError("unsupported observation analyzer result format/version")
    if result["adapter"] != expected_adapter or result["revision"] != expected_revision:
        raise ObservationError("observation analyzer adapter/revision mismatch")
    raw_observations = result["observations"]
    if not isinstance(raw_observations, list) or not 1 <= len(raw_observations) <= 5000:
        raise ObservationError("observation analyzer must return 1..5000 observations")

    source_map = {str(item["source_id"]): item for item in sources}
    observations: list[Observation] = []
    required = {
        "source_id",
        "start_seconds",
        "duration_seconds",
        "target_confidence",
        "target_screen_fraction",
        "face_visibility",
        "full_body_visibility",
        "sharpness",
        "occlusion",
        "motion",
        "view",
    }
    for raw in raw_observations:
        if not isinstance(raw, dict) or set(raw) != required:
            raise ObservationError("observation fields must match v1 exactly")
        source_id = str(raw["source_id"])
        source = source_map.get(source_id)
        if source is None:
            raise ObservationError(f"observation references unknown source_id: {source_id}")
        start = _positive(raw["start_seconds"], label="start_seconds", maximum=172800.0)
        duration = _positive(raw["duration_seconds"], label="duration_seconds", maximum=12.0)
        if duration < 1.0:
            raise ObservationError("observation duration must be in 1..12 seconds")
        if start + duration > float(source["duration"]) + 0.25:
            raise ObservationError("observation extends beyond source duration")
        view = str(raw["view"])
        if view not in VIEWS:
            raise ObservationError(f"unsupported observation view: {view}")
        metrics = {
            key: _finite(raw[key], label=key)
            for key in (
                "target_confidence",
                "target_screen_fraction",
                "face_visibility",
                "full_body_visibility",
                "sharpness",
                "occlusion",
                "motion",
            )
        }
        observations.append(
            Observation(
                source_id=source_id,
                start_seconds=start,
                duration_seconds=duration,
                view=view,
                base_score=_base_score(metrics),
                **metrics,
            )
        )
    return observations


def _overlap_ratio(a: Observation, b: Observation) -> float:
    if a.source_id != b.source_id:
        return 0.0
    overlap = max(0.0, min(a.end_seconds, b.end_seconds) - max(a.start_seconds, b.start_seconds))
    shorter = min(a.duration_seconds, b.duration_seconds)
    return overlap / shorter if shorter > 0 else 0.0


def select_observations(
    observations: Sequence[Observation],
    *,
    max_segments: int = 10,
    min_base_score: float = 0.35,
    max_per_source: int = 2,
) -> list[Observation]:
    if isinstance(max_segments, bool) or not 1 <= max_segments <= 10:
        raise ObservationError("max_segments must be in 1..10")
    if isinstance(max_per_source, bool) or not 1 <= max_per_source <= 4:
        raise ObservationError("max_per_source must be in 1..4")
    min_score = _finite(min_base_score, label="min_base_score")
    pool = [item for item in observations if item.base_score >= min_score]
    if not pool:
        raise ObservationError("no observation passed the minimum quality threshold")

    selected: list[Observation] = []
    used_views: set[str] = set()
    source_counts: dict[str, int] = {}
    while pool and len(selected) < max_segments:
        scored: list[tuple[float, Observation]] = []
        for candidate in pool:
            if source_counts.get(candidate.source_id, 0) >= max_per_source:
                continue
            if any(_overlap_ratio(candidate, existing) > 0.45 for existing in selected):
                continue
            diversity = 0.0
            if candidate.view != "unknown" and candidate.view not in used_views:
                diversity += 0.16
            if source_counts.get(candidate.source_id, 0) == 0:
                diversity += 0.10
            # Reward observations that are especially useful for one of the two
            # distinct clone tasks, even if their aggregate score is similar.
            if candidate.face_visibility >= 0.72:
                diversity += 0.05
            if candidate.full_body_visibility >= 0.72:
                diversity += 0.05
            scored.append((candidate.base_score + diversity, candidate))
        if not scored:
            break
        scored.sort(
            key=lambda pair: (
                -pair[0],
                -pair[1].base_score,
                pair[1].source_id,
                pair[1].start_seconds,
            )
        )
        chosen = scored[0][1]
        selected.append(chosen)
        used_views.add(chosen.view)
        source_counts[chosen.source_id] = source_counts.get(chosen.source_id, 0) + 1
        pool = [item for item in pool if item is not chosen]

    if not selected:
        raise ObservationError("no non-overlapping observation could be selected")
    return selected


def build_selection_manifest(
    *,
    source_manifest_sha256: str,
    adapter: str,
    revision: str,
    sources: Sequence[Mapping[str, Any]],
    selected: Sequence[Observation],
) -> dict[str, Any]:
    source_map = {str(item["source_id"]): item for item in sources}
    return {
        "format": SELECTION_FORMAT,
        "version": VERSION,
        "source_manifest_sha256": source_manifest_sha256,
        "adapter": adapter,
        "revision": revision,
        "selected": [
            {
                **item.to_json(),
                "scene_id": str(source_map[item.source_id]["scene_id"]),
            }
            for item in selected
        ],
    }


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
            *argv,
            "--bodyrig-request",
            str(request_path),
            "--bodyrig-workspace",
            str(workspace_path),
            "--bodyrig-output",
            str(output_dir),
            "--bodyrig-adapter",
            adapter,
            "--bodyrig-revision",
            revision,
        ]
        # Source paths are deliberately process arguments, not JSON fields.
        for source in sources:
            invoke.extend(["--bodyrig-source-id", str(source["source_id"]), "--bodyrig-source-path", str(source["path"])])
        try:
            with log_path.open("wb") as log:
                completed = subprocess.run(
                    invoke,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    check=False,
                    timeout=timeout_seconds,
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ObservationError("observation analyzer process could not complete") from exc
        if completed.returncode != 0:
            raise ObservationError(f"observation analyzer failed with exit code {completed.returncode}")
        children = list(output_dir.iterdir())
        if {item.name for item in children} != {"observations.json"} or any(not item.is_file() for item in children):
            raise ObservationError("observation analyzer output must contain exactly observations.json")
        return validate_analyzer_result(
            output_dir / "observations.json",
            sources=sources,
            expected_adapter=adapter,
            expected_revision=revision,
        )


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def materialize_segments(
    *,
    sources: Sequence[Mapping[str, Any]],
    selection_manifest: Mapping[str, Any],
    workspace: str | Path,
    ffmpeg: str = "ffmpeg",
    runner: Callable[[list[str]], int] | None = None,
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise ObservationError(f"segment workspace already exists: {root}")
    root.mkdir(parents=True)
    source_map = {str(item["source_id"]): item for item in sources}
    selected = selection_manifest.get("selected")
    if not isinstance(selected, list) or not 1 <= len(selected) <= 10:
        shutil.rmtree(root, ignore_errors=True)
        raise ObservationError("selection manifest must contain 1..10 selected observations")

    segment_rows: list[dict[str, Any]] = []
    try:
        for index, item in enumerate(selected, start=1):
            if not isinstance(item, Mapping):
                raise ObservationError("selection item must be an object")
            source_id = str(item.get("source_id") or "")
            source = source_map.get(source_id)
            if source is None:
                raise ObservationError(f"selection references unknown source_id: {source_id}")
            start = _positive(item.get("start_seconds"), label="segment start", maximum=172800.0)
            duration = _positive(item.get("duration_seconds"), label="segment duration", maximum=12.0)
            if duration < 1.0:
                raise ObservationError("segment duration must be in 1..12 seconds")
            output = root / f"segment-{index:02d}.mp4"
            argv = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-i",
                str(source["path"]),
                "-t",
                f"{duration:.3f}",
                "-map",
                "0:v:0",
                "-an",
                "-sn",
                "-dn",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output),
            ]
            if runner is None:
                completed = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, shell=False, check=False)
                code = completed.returncode
            else:
                code = runner(argv)
            if code != 0 or not output.is_file() or output.stat().st_size <= 0:
                raise ObservationError(f"FFmpeg failed to materialize observation segment {index}")
            segment_rows.append(
                {
                    "source_id": source_id,
                    "scene_id": str(source["scene_id"]),
                    "path": str(output),
                    "start_seconds": round(start, 3),
                    "duration_seconds": round(duration, 3),
                    "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                }
            )
        manifest = {
            "format": SEGMENTS_FORMAT,
            "version": VERSION,
            "selection_sha256": _canonical_sha256(dict(selection_manifest)),
            "segments": segment_rows,
        }
        manifest_path = root / "bodyrig-observation-segments.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        return manifest
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise

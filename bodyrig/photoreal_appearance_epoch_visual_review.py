from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping

from .photoreal_teacher_input import (
    FRAME_INDEX_FORMAT,
    FRAME_INDEX_VERSION,
    PLAN_FORMAT,
    PLAN_VERSION,
    RECEIPT_FORMAT,
    RECEIPT_VERSION,
    PhotorealTeacherInputError,
    _plan_sources,
    _receipt_sources,
)

PATH_MAP_FORMAT = "bodyrig-photoreal-appearance-epoch-runtime-path-map"
PATH_MAP_VERSION = 1
MANIFEST_FORMAT = "bodyrig-photoreal-appearance-epoch-visual-review-manifest"
MANIFEST_VERSION = 1
PRIVATE_FORMAT = "bodyrig-photoreal-private-appearance-epoch-visual-review-index"
PRIVATE_VERSION = 1
REQUEST_FORMAT = "bodyrig-photoreal-appearance-epoch-visual-review-request"
REQUEST_VERSION = 1


class PhotorealAppearanceEpochVisualReviewError(RuntimeError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealAppearanceEpochVisualReviewError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAppearanceEpochVisualReviewError(f"{label} must be a JSON object")
    return value


def _sha256_file(path: str | Path) -> str:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise PhotorealAppearanceEpochVisualReviewError(f"required file is missing or not regular: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise PhotorealAppearanceEpochVisualReviewError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum or "\n" in result or "\r" in result:
        raise PhotorealAppearanceEpochVisualReviewError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealAppearanceEpochVisualReviewError(f"{label} is invalid")
    return result


def _git_sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=40).lower()
    if len(result) != 40 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealAppearanceEpochVisualReviewError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealAppearanceEpochVisualReviewError(f"{label} format/version mismatch")
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealAppearanceEpochVisualReviewError(f"{label} format/version mismatch")


def _timestamp(value: Any, *, kind: str) -> float | None:
    if value is None:
        if kind == "image":
            return None
        raise PhotorealAppearanceEpochVisualReviewError("video review observation has no timestamp")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealAppearanceEpochVisualReviewError("review observation timestamp is invalid")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise PhotorealAppearanceEpochVisualReviewError("review observation timestamp is invalid")
    return round(number, 6)


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PhotorealAppearanceEpochVisualReviewError("review artifact cannot be canonically serialized") from exc


def _write_or_require_exact(path: Path, value: Mapping[str, Any], *, label: str) -> None:
    path = path.expanduser().resolve()
    if path.is_symlink():
        raise PhotorealAppearanceEpochVisualReviewError(f"{label} may not be a symlink: {path}")
    if path.exists():
        if not path.is_file():
            raise PhotorealAppearanceEpochVisualReviewError(f"{label} is not a regular file: {path}")
        existing = _read_json(path, label=label)
        if _canonical_json(existing) != _canonical_json(value):
            raise PhotorealAppearanceEpochVisualReviewError(f"{label} does not match canonical state: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(dict(value), stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except OSError as exc:
        raise PhotorealAppearanceEpochVisualReviewError(f"failed to persist {label}: {path}") from exc


def _normalized_inputs(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    frame_index: Mapping[str, Any],
) -> tuple[str, dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if plan.get("format") != PLAN_FORMAT:
        raise PhotorealAppearanceEpochVisualReviewError("dataset plan format/version mismatch")
    _strict_v1(plan.get("version"), label="dataset plan")
    if PLAN_VERSION != 1:
        raise PhotorealAppearanceEpochVisualReviewError("unsupported compiled dataset-plan version")
    if receipt.get("format") != RECEIPT_FORMAT:
        raise PhotorealAppearanceEpochVisualReviewError("source receipt format/version mismatch")
    _strict_v1(receipt.get("version"), label="source receipt")
    if RECEIPT_VERSION != 1:
        raise PhotorealAppearanceEpochVisualReviewError("unsupported compiled source-receipt version")
    try:
        planned = _plan_sources(plan)
        bound = _receipt_sources(receipt)
    except PhotorealTeacherInputError as exc:
        raise PhotorealAppearanceEpochVisualReviewError(f"P0 source authority is invalid: {exc}") from exc
    if set(planned) != set(bound):
        raise PhotorealAppearanceEpochVisualReviewError("dataset plan/source receipt source universe mismatch")

    performer_id = _text(plan.get("performer_id"), label="dataset performer id", maximum=256)
    if _text(receipt.get("performer_id"), label="receipt performer id", maximum=256) != performer_id:
        raise PhotorealAppearanceEpochVisualReviewError("dataset plan/source receipt performer mismatch")

    if frame_index.get("format") != FRAME_INDEX_FORMAT:
        raise PhotorealAppearanceEpochVisualReviewError("frame index format/version mismatch")
    _strict_v1(frame_index.get("version"), label="frame index")
    if FRAME_INDEX_VERSION != 1:
        raise PhotorealAppearanceEpochVisualReviewError("unsupported compiled frame-index version")
    if _text(frame_index.get("performer_id"), label="frame-index performer id", maximum=256) != performer_id:
        raise PhotorealAppearanceEpochVisualReviewError("frame index performer mismatch")
    if frame_index.get("teacher_training_authorized") is not True:
        raise PhotorealAppearanceEpochVisualReviewError("frame index does not authorize teacher training")
    if frame_index.get("human_visual_acceptance_required") is not True:
        raise PhotorealAppearanceEpochVisualReviewError("frame index removed human visual acceptance")
    if frame_index.get("photoreal_acceptance_authority") is not False:
        raise PhotorealAppearanceEpochVisualReviewError("frame index crossed photoreal authority")
    if frame_index.get("build_only") is not True or frame_index.get("runtime_dependency") is not False:
        raise PhotorealAppearanceEpochVisualReviewError("frame index build/runtime authority boundary is invalid")
    if frame_index.get("production_activation") is not False:
        raise PhotorealAppearanceEpochVisualReviewError("frame index crossed production authority")

    raw_observations = frame_index.get("observations")
    if not isinstance(raw_observations, list) or not raw_observations:
        raise PhotorealAppearanceEpochVisualReviewError("frame index contains no observations")

    observations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float | None, str]] = set()
    split_counts = {"train": 0, "evaluation": 0}
    for raw in raw_observations:
        if not isinstance(raw, Mapping) or raw.get("eligible_for_teacher") is not True:
            continue
        if raw.get("target_identity_verified") is not True:
            raise PhotorealAppearanceEpochVisualReviewError("teacher-eligible review observation lacks target identity authority")
        source_key = _text(raw.get("source_key"), label="review source key")
        group_id = _text(raw.get("group_id"), label="review group id")
        source = planned.get(source_key)
        receipt_source = bound.get(source_key)
        if source is None or receipt_source is None:
            raise PhotorealAppearanceEpochVisualReviewError("review observation references unknown source")
        if _text(source.get("group_id"), label="planned source group id") != group_id:
            raise PhotorealAppearanceEpochVisualReviewError("review observation group differs from dataset plan")
        split = _text(raw.get("split"), label="review split", maximum=32)
        if split not in split_counts or source.get("split") != split:
            raise PhotorealAppearanceEpochVisualReviewError("review observation split differs from dataset plan")
        kind = _text(source.get("kind"), label="planned source kind", maximum=16)
        if receipt_source.get("kind") != kind:
            raise PhotorealAppearanceEpochVisualReviewError("planned/receipt source kind mismatch")
        frame_sha = _sha(raw.get("frame_sha256"), label="review frame SHA-256")
        timestamp = _timestamp(raw.get("timestamp_seconds"), kind=kind)
        eye = _text(raw.get("eye"), label="review eye", maximum=16)
        view_bin = _text(raw.get("view_bin"), label="review view bin", maximum=64)
        coverage_raw = raw.get("coverage")
        if not isinstance(coverage_raw, list):
            raise PhotorealAppearanceEpochVisualReviewError("review observation coverage is invalid")
        coverage = sorted({_text(item, label="review coverage", maximum=64) for item in coverage_raw})
        key = (source_key, frame_sha, timestamp, eye)
        if key in seen:
            raise PhotorealAppearanceEpochVisualReviewError("frame index repeats an eligible review observation")
        seen.add(key)
        split_counts[split] += 1
        observations.append(
            {
                "source_key": source_key,
                "group_id": group_id,
                "split": split,
                "frame_sha256": frame_sha,
                "timestamp_seconds": timestamp,
                "eye": eye,
                "view_bin": view_bin,
                "coverage": coverage,
            }
        )
    if not observations or min(split_counts.values()) < 1:
        raise PhotorealAppearanceEpochVisualReviewError(
            "appearance review requires eligible train and held-out evaluation observations"
        )
    observations.sort(
        key=lambda item: (
            item["split"],
            item["group_id"],
            item["source_key"],
            -1.0 if item["timestamp_seconds"] is None else item["timestamp_seconds"],
            item["eye"],
            item["frame_sha256"],
        )
    )
    return performer_id, planned, bound, observations


def build_runtime_path_map(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    frame_index: Mapping[str, Any],
    *,
    converter: Callable[[str], str],
    dataset_plan_sha256: str,
    source_receipt_sha256: str,
    frame_index_sha256: str,
) -> dict[str, Any]:
    performer_id, _planned, bound, observations = _normalized_inputs(plan, receipt, frame_index)
    source_keys = sorted({item["source_key"] for item in observations})
    paths: list[dict[str, str]] = []
    for source_key in source_keys:
        converted = converter(_text(bound[source_key].get("resolved_path"), label="receipt resolved path"))
        if not isinstance(converted, str) or not converted.startswith("/") or "\n" in converted or "\r" in converted:
            raise PhotorealAppearanceEpochVisualReviewError(
                f"runtime path converter returned an invalid Linux path for source: {source_key}"
            )
        paths.append({"source_key": source_key, "resolved_path": converted})
    return {
        "format": PATH_MAP_FORMAT,
        "version": PATH_MAP_VERSION,
        "performer_id": performer_id,
        "dataset_plan_sha256": _sha(dataset_plan_sha256, label="dataset plan file SHA-256"),
        "source_receipt_sha256": _sha(source_receipt_sha256, label="source receipt file SHA-256"),
        "frame_index_sha256": _sha(frame_index_sha256, label="frame index file SHA-256"),
        "source_count": len(paths),
        "source_paths": paths,
        "source_paths_private": True,
        "source_media_rehash_performed": False,
        "build_only": True,
        "production_activation": False,
    }


def build_runtime_path_map_files(
    dataset_plan_path: str | Path,
    source_receipt_path: str | Path,
    frame_index_path: str | Path,
    output_path: str | Path,
    *,
    converter: Callable[[str], str],
) -> dict[str, Any]:
    plan_path = Path(dataset_plan_path).expanduser().resolve()
    receipt_path = Path(source_receipt_path).expanduser().resolve()
    index_path = Path(frame_index_path).expanduser().resolve()
    result = build_runtime_path_map(
        _read_json(plan_path, label="dataset plan"),
        _read_json(receipt_path, label="source receipt"),
        _read_json(index_path, label="frame index"),
        converter=converter,
        dataset_plan_sha256=_sha256_file(plan_path),
        source_receipt_sha256=_sha256_file(receipt_path),
        frame_index_sha256=_sha256_file(index_path),
    )
    _write_or_require_exact(Path(output_path), result, label="appearance epoch runtime path map")
    return result


def build_review_request(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    frame_index: Mapping[str, Any],
    runtime_path_map: Mapping[str, Any],
    *,
    bodyrig_revision: str,
    dataset_plan_sha256: str,
    source_receipt_sha256: str,
    frame_index_sha256: str,
) -> dict[str, Any]:
    performer_id, planned, bound, observations = _normalized_inputs(plan, receipt, frame_index)
    revision = _git_sha(bodyrig_revision, label="BodyRig revision")
    if runtime_path_map.get("format") != PATH_MAP_FORMAT:
        raise PhotorealAppearanceEpochVisualReviewError("runtime path map format/version mismatch")
    _strict_v1(runtime_path_map.get("version"), label="runtime path map")
    if _text(runtime_path_map.get("performer_id"), label="runtime path map performer", maximum=256) != performer_id:
        raise PhotorealAppearanceEpochVisualReviewError("runtime path map performer mismatch")
    for field, expected in (
        ("dataset_plan_sha256", dataset_plan_sha256),
        ("source_receipt_sha256", source_receipt_sha256),
        ("frame_index_sha256", frame_index_sha256),
    ):
        if _sha(runtime_path_map.get(field), label=f"runtime path map {field}") != _sha(expected, label=field):
            raise PhotorealAppearanceEpochVisualReviewError(f"runtime path map input binding mismatch: {field}")
    if runtime_path_map.get("source_paths_private") is not True:
        raise PhotorealAppearanceEpochVisualReviewError("runtime path map does not mark source paths private")
    if runtime_path_map.get("source_media_rehash_performed") is not False:
        raise PhotorealAppearanceEpochVisualReviewError("runtime path map unexpectedly claims source media rehash")
    if runtime_path_map.get("build_only") is not True or runtime_path_map.get("production_activation") is not False:
        raise PhotorealAppearanceEpochVisualReviewError("runtime path map crossed authority boundary")

    raw_paths = runtime_path_map.get("source_paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise PhotorealAppearanceEpochVisualReviewError("runtime path map contains no source paths")
    source_count = runtime_path_map.get("source_count")
    if isinstance(source_count, bool) or not isinstance(source_count, int) or source_count != len(raw_paths):
        raise PhotorealAppearanceEpochVisualReviewError("runtime path map source count mismatch")
    path_map: dict[str, str] = {}
    for raw in raw_paths:
        if not isinstance(raw, Mapping):
            raise PhotorealAppearanceEpochVisualReviewError("runtime path map contains an invalid source path")
        source_key = _text(raw.get("source_key"), label="runtime path source key")
        resolved_path = _text(raw.get("resolved_path"), label="runtime Linux path")
        if not resolved_path.startswith("/") or source_key in path_map:
            raise PhotorealAppearanceEpochVisualReviewError("runtime path map source is invalid/duplicated")
        path_map[source_key] = resolved_path
    required_sources = sorted({item["source_key"] for item in observations})
    if sorted(path_map) != required_sources:
        raise PhotorealAppearanceEpochVisualReviewError(
            "runtime path map must contain exactly the eligible review source universe"
        )

    sources: list[dict[str, Any]] = []
    for source_key in required_sources:
        source = planned[source_key]
        receipt_source = bound[source_key]
        projection = str(source.get("projection") or "flat")
        stereo_layout = str(source.get("stereo_layout") or "mono")
        record: dict[str, Any] = {
            "source_key": source_key,
            "source_sha256": _sha(receipt_source.get("sha256"), label="source SHA-256"),
            "kind": _text(source.get("kind"), label="source kind", maximum=16),
            "group_id": _text(source.get("group_id"), label="source group id"),
            "split": _text(source.get("split"), label="source split", maximum=32),
            "resolved_path": path_map[source_key],
            "projection": projection,
            "stereo_layout": stereo_layout,
            "decode_mode": str(source.get("decode_mode") or ""),
        }
        authority = source.get("projection_authority")
        if authority is not None:
            if not isinstance(authority, Mapping):
                raise PhotorealAppearanceEpochVisualReviewError("source projection authority is invalid")
            record["projection_authority"] = dict(authority)
        sources.append(record)

    return {
        "format": REQUEST_FORMAT,
        "version": REQUEST_VERSION,
        "bodyrig_revision": revision,
        "performer_id": performer_id,
        "dataset_plan_sha256": _sha(dataset_plan_sha256, label="dataset plan SHA-256"),
        "source_receipt_sha256": _sha(source_receipt_sha256, label="source receipt SHA-256"),
        "frame_index_sha256": _sha(frame_index_sha256, label="frame index SHA-256"),
        "sources": sources,
        "observations": observations,
        "source_media_rehash_performed": False,
        "review_only": True,
        "human_appearance_epoch_review_required": True,
        "teacher_input_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def _load_adapter(repo_root: Path) -> Any:
    path = repo_root / "tools" / "photoreal_reference_vision_adapter_mesh.py"
    spec = importlib.util.spec_from_file_location("bodyrig_appearance_review_adapter", path)
    if spec is None or spec.loader is None:
        raise PhotorealAppearanceEpochVisualReviewError(f"could not load reference adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_runtime() -> Any:
    try:
        import cv2
        import numpy as np
    except Exception as exc:
        raise PhotorealAppearanceEpochVisualReviewError(
            "appearance epoch visual review requires OpenCV and NumPy in the photoreal runtime"
        ) from exc
    return SimpleNamespace(cv2=cv2, np=np)


def _reproduce_observation(
    adapter: Any,
    runtime: Any,
    source: Mapping[str, Any],
    observation: Mapping[str, Any],
    *,
    mesh_cache: dict[Any, Any] | None = None,
) -> Any:
    expected = _sha(observation.get("frame_sha256"), label="expected review frame SHA-256")
    sample = {
        "timestamp_seconds": observation.get("timestamp_seconds"),
        "eye": observation.get("eye"),
    }
    try:
        image, spatial = adapter._read_frame_sample(runtime, source, sample)
    except Exception as exc:
        raise PhotorealAppearanceEpochVisualReviewError(
            f"could not decode authorized review observation: {source.get('source_key')}"
        ) from exc

    candidates: list[Any] = []
    if not spatial:
        candidates = [image]
    else:
        projection = str(source.get("projection") or "")
        try:
            if projection == "equi":
                candidates = [
                    value for _viewport, value in adapter.base.deproject_equirectangular_views(
                        runtime,
                        image,
                        source.get("projection_authority"),
                    )
                ]
            elif projection == "mshp":
                candidates = [
                    value for _viewport, value in adapter.deproject_mesh_views(
                        runtime,
                        image,
                        source.get("resolved_path"),
                        source.get("projection_authority"),
                        eye=str(observation.get("eye") or ""),
                        cache=mesh_cache if mesh_cache is not None else {},
                    )
                ]
            elif projection == "cbmp":
                candidates = [
                    value for _viewport, value in adapter.deproject_cubemap_views(
                        runtime,
                        image,
                        source.get("projection_authority"),
                    )
                ]
            else:
                candidates = [image]
        except Exception as exc:
            raise PhotorealAppearanceEpochVisualReviewError(
                f"could not deproject authorized review observation: {source.get('source_key')}"
            ) from exc

    matches = [candidate for candidate in candidates if adapter.base._frame_sha(candidate) == expected]
    if len(matches) != 1:
        raise PhotorealAppearanceEpochVisualReviewError(
            "authorized review frame SHA did not reproduce exactly once "
            f"(source={source.get('source_key')}, expected={expected}, matches={len(matches)})"
        )
    return runtime.np.ascontiguousarray(matches[0])


def _safe_frame_id(index: int, frame_sha: str) -> str:
    return f"review-frame-{index:06d}-{frame_sha[:12]}"


def _source_ref(source_key: str) -> str:
    return hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:20]


def _write_review_html(manifest: Mapping[str, Any], output: Path) -> None:
    sections: list[str] = []
    groups = manifest.get("groups")
    if not isinstance(groups, list):
        raise PhotorealAppearanceEpochVisualReviewError("review manifest groups are invalid")
    for group in groups:
        if not isinstance(group, Mapping):
            raise PhotorealAppearanceEpochVisualReviewError("review manifest group is invalid")
        split = html.escape(str(group.get("split") or ""))
        group_id = html.escape(str(group.get("group_id") or ""))
        badge = "HELD-OUT EVALUATION" if split == "evaluation" else "TRAIN"
        cards: list[str] = []
        for frame in group.get("frames") or []:
            if not isinstance(frame, Mapping):
                continue
            relative = html.escape(str(frame.get("relative_path") or ""))
            view_bin = html.escape(str(frame.get("view_bin") or ""))
            eye = html.escape(str(frame.get("eye") or ""))
            timestamp = frame.get("timestamp_seconds")
            timestamp_text = "still" if timestamp is None else f"{float(timestamp):.3f}s"
            coverage = ", ".join(str(item) for item in frame.get("coverage") or [])
            cards.append(
                "<article class=\"card\">"
                f"<img src=\"{relative}\" loading=\"lazy\" alt=\"{group_id} {view_bin}\">"
                f"<div><strong>{html.escape(view_bin)}</strong> · {html.escape(eye)} · {html.escape(timestamp_text)}</div>"
                f"<small>{html.escape(coverage)}</small>"
                "</article>"
            )
        sections.append(
            "<section>"
            f"<h2><span class=\"badge\">{html.escape(badge)}</span> {group_id}</h2>"
            f"<p>{int(group.get('observation_count') or 0)} exact P0-authorized observations.</p>"
            f"<div class=\"grid\">{''.join(cards)}</div>"
            "</section>"
        )
    document = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>BodyRig appearance epoch review</title>
<style>
body{font-family:system-ui,sans-serif;background:#101114;color:#f4f4f4;margin:2rem;line-height:1.4}
.notice{padding:1rem;border:1px solid #8b6f2d;background:#221d10;margin-bottom:2rem}
section{margin:0 0 3rem}.badge{font-size:.72em;padding:.2rem .45rem;border:1px solid #777;border-radius:.3rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:1rem}
.card{background:#181a1f;border:1px solid #343740;padding:.7rem}.card img{width:100%;height:auto;display:block;background:#000;margin-bottom:.5rem}
small{color:#b9bec9}
</style></head><body>
<h1>BodyRig Photoreal V2 — appearance epoch visual review</h1>
<div class="notice"><strong>Human review only.</strong> Choose one coherent appearance state across at least one TRAIN group and one HELD-OUT EVALUATION group. Held-out evaluation images may be inspected by the human reviewer but must never be supplied to the teacher training request. This pack grants no teacher-input, photoreal or production authority.</div>
""" + "\n".join(sections) + """
</body></html>
"""
    output.write_text(document, encoding="utf-8", newline="\n")


def prepare_review(
    request: Mapping[str, Any],
    output_dir: str | Path,
    *,
    adapter: Any | None = None,
    runtime: Any | None = None,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    output = Path(output_dir).expanduser().resolve()
    if request.get("format") != REQUEST_FORMAT:
        raise PhotorealAppearanceEpochVisualReviewError("visual review request format/version mismatch")
    _strict_v1(request.get("version"), label="visual review request")
    revision = _git_sha(request.get("bodyrig_revision"), label="review request BodyRig revision")
    if output.exists():
        if reuse_existing:
            return validate_review_output(output, request=request)
        raise PhotorealAppearanceEpochVisualReviewError(f"review output already exists: {output}")
    sources_raw = request.get("sources")
    observations = request.get("observations")
    if not isinstance(sources_raw, list) or not sources_raw or not isinstance(observations, list) or not observations:
        raise PhotorealAppearanceEpochVisualReviewError("visual review request is incomplete")
    if request.get("source_media_rehash_performed") is not False:
        raise PhotorealAppearanceEpochVisualReviewError("visual review request unexpectedly claims source-media rehash")
    if request.get("review_only") is not True or request.get("human_appearance_epoch_review_required") is not True:
        raise PhotorealAppearanceEpochVisualReviewError("visual review request review boundary is invalid")
    if request.get("teacher_input_authorized") is not False:
        raise PhotorealAppearanceEpochVisualReviewError("visual review request crossed teacher-input authority")
    if request.get("photoreal_acceptance_authority") is not False or request.get("production_activation") is not False:
        raise PhotorealAppearanceEpochVisualReviewError("visual review request crossed downstream authority")

    sources: dict[str, dict[str, Any]] = {}
    for raw in sources_raw:
        if not isinstance(raw, Mapping):
            raise PhotorealAppearanceEpochVisualReviewError("visual review request source is invalid")
        source_key = _text(raw.get("source_key"), label="visual review source key")
        if source_key in sources:
            raise PhotorealAppearanceEpochVisualReviewError("visual review request repeats source")
        resolved_path = _text(raw.get("resolved_path"), label="visual review resolved path")
        if not resolved_path.startswith("/"):
            raise PhotorealAppearanceEpochVisualReviewError("visual review source path is not absolute Linux path")
        split = _text(raw.get("split"), label="visual review source split", maximum=32)
        if split not in {"train", "evaluation"}:
            raise PhotorealAppearanceEpochVisualReviewError("visual review source split is invalid")
        sources[source_key] = dict(raw)

    repo_root = Path(__file__).resolve().parents[1]
    adapter = adapter if adapter is not None else _load_adapter(repo_root)
    runtime = runtime if runtime is not None else _load_runtime()

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        frames_root = stage / "frames"
        frames_root.mkdir(parents=True)
        private_frames: list[dict[str, Any]] = []
        public_frames_by_group: dict[tuple[str, str], list[dict[str, Any]]] = {}
        mesh_caches: dict[str, dict[Any, Any]] = {}
        seen_observations: set[tuple[str, str, float | None, str]] = set()
        for index, raw in enumerate(observations):
            if not isinstance(raw, Mapping):
                raise PhotorealAppearanceEpochVisualReviewError("visual review observation is invalid")
            source_key = _text(raw.get("source_key"), label="visual review observation source key")
            source = sources.get(source_key)
            if source is None:
                raise PhotorealAppearanceEpochVisualReviewError("visual review observation references unknown source")
            split = _text(raw.get("split"), label="visual review split", maximum=32)
            group_id = _text(raw.get("group_id"), label="visual review group id")
            if split != source.get("split") or group_id != source.get("group_id"):
                raise PhotorealAppearanceEpochVisualReviewError(
                    "visual review observation source/group/split binding mismatch"
                )
            expected = _sha(raw.get("frame_sha256"), label="visual review frame SHA-256")
            observation_key = (
                source_key,
                expected,
                raw.get("timestamp_seconds"),
                _text(raw.get("eye"), label="visual review eye", maximum=16),
            )
            if observation_key in seen_observations:
                raise PhotorealAppearanceEpochVisualReviewError("visual review request repeats observation")
            seen_observations.add(observation_key)
            image = _reproduce_observation(
                adapter,
                runtime,
                source,
                raw,
                mesh_cache=mesh_caches.setdefault(source_key, {}),
            )
            frame_id = _safe_frame_id(index, expected)
            frame_path = frames_root / f"{frame_id}.png"
            try:
                ok = runtime.cv2.imwrite(str(frame_path), image, [runtime.cv2.IMWRITE_PNG_COMPRESSION, 3])
            except Exception as exc:
                raise PhotorealAppearanceEpochVisualReviewError(f"could not write review PNG: {frame_path}") from exc
            if not ok or not frame_path.is_file() or frame_path.stat().st_size < 1:
                raise PhotorealAppearanceEpochVisualReviewError(f"review PNG is missing/empty: {frame_path}")
            relative = f"frames/{frame_path.name}"
            public_frame = {
                "frame_id": frame_id,
                "source_ref": _source_ref(source_key),
                "frame_sha256": expected,
                "timestamp_seconds": raw.get("timestamp_seconds"),
                "eye": _text(raw.get("eye"), label="visual review eye", maximum=16),
                "view_bin": _text(raw.get("view_bin"), label="visual review view bin", maximum=64),
                "coverage": list(raw.get("coverage") or []),
                "relative_path": relative,
                "staged_png_sha256": _sha256_file(frame_path),
                "width": int(image.shape[1]),
                "height": int(image.shape[0]),
            }
            public_frames_by_group.setdefault((split, group_id), []).append(public_frame)
            private_frames.append(
                {
                    "frame_id": frame_id,
                    "source_key": source_key,
                    "resolved_path": _text(source.get("resolved_path"), label="private resolved source path"),
                    "source_sha256": _sha(source.get("source_sha256"), label="private source SHA-256"),
                }
            )

        groups: list[dict[str, Any]] = []
        train_groups = 0
        evaluation_groups = 0
        for (split, group_id), frames in sorted(public_frames_by_group.items()):
            frames.sort(
                key=lambda item: (
                    -1.0 if item["timestamp_seconds"] is None else float(item["timestamp_seconds"]),
                    item["eye"],
                    item["frame_sha256"],
                )
            )
            groups.append(
                {
                    "group_id": group_id,
                    "split": split,
                    "observation_count": len(frames),
                    "view_bins": sorted({str(item["view_bin"]) for item in frames}),
                    "frames": frames,
                }
            )
            if split == "train":
                train_groups += 1
            elif split == "evaluation":
                evaluation_groups += 1
        if train_groups < 1 or evaluation_groups < 1:
            raise PhotorealAppearanceEpochVisualReviewError(
                "visual review materialization lost train/evaluation group coverage"
            )

        manifest = {
            "format": MANIFEST_FORMAT,
            "version": MANIFEST_VERSION,
            "bodyrig_revision": revision,
            "performer_id": _text(request.get("performer_id"), label="review request performer", maximum=256),
            "dataset_plan_sha256": _sha(request.get("dataset_plan_sha256"), label="dataset plan SHA-256"),
            "source_receipt_sha256": _sha(request.get("source_receipt_sha256"), label="source receipt SHA-256"),
            "frame_index_sha256": _sha(request.get("frame_index_sha256"), label="frame index SHA-256"),
            "group_count": len(groups),
            "train_group_count": train_groups,
            "evaluation_group_count": evaluation_groups,
            "eligible_observation_count": sum(len(item["frames"]) for item in groups),
            "groups": groups,
            "source_paths_disclosed": False,
            "source_media_rehash_performed": False,
            "exact_p0_frame_hashes_reproduced": True,
            "review_only": True,
            "human_appearance_epoch_review_required": True,
            "teacher_input_authorized": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }
        review_html_path = stage / "review-index.html"
        _write_review_html(manifest, review_html_path)
        manifest["review_index_sha256"] = _sha256_file(review_html_path)
        manifest_path = stage / "appearance-epoch-visual-review-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        private_index = {
            "format": PRIVATE_FORMAT,
            "version": PRIVATE_VERSION,
            "bodyrig_revision": revision,
            "performer_id": manifest["performer_id"],
            "public_manifest_sha256": _sha256_file(manifest_path),
            "frames": private_frames,
            "source_paths_private": True,
            "source_media_rehash_performed": False,
            "production_activation": False,
        }
        (stage / "private-review-index.json").write_text(
            json.dumps(private_index, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return validate_review_output(output, request=request)


def validate_review_output(output_dir: str | Path, *, request: Mapping[str, Any]) -> dict[str, Any]:
    output = Path(output_dir).expanduser().resolve()
    manifest_path = output / "appearance-epoch-visual-review-manifest.json"
    private_path = output / "private-review-index.json"
    review_html = output / "review-index.html"
    manifest = _read_json(manifest_path, label="appearance epoch visual review manifest")
    private = _read_json(private_path, label="private appearance epoch visual review index")
    if not review_html.is_file() or review_html.is_symlink():
        raise PhotorealAppearanceEpochVisualReviewError("appearance epoch review HTML is missing")
    if manifest.get("format") != MANIFEST_FORMAT:
        raise PhotorealAppearanceEpochVisualReviewError("appearance epoch review manifest format/version mismatch")
    _strict_v1(manifest.get("version"), label="appearance epoch review manifest")
    if private.get("format") != PRIVATE_FORMAT:
        raise PhotorealAppearanceEpochVisualReviewError("private appearance epoch review index format/version mismatch")
    _strict_v1(private.get("version"), label="private appearance epoch review index")
    if _sha(manifest.get("review_index_sha256"), label="review HTML SHA-256") != _sha256_file(review_html):
        raise PhotorealAppearanceEpochVisualReviewError("appearance epoch review HTML bytes changed")
    if _git_sha(manifest.get("bodyrig_revision"), label="manifest BodyRig revision") != _git_sha(
        request.get("bodyrig_revision"), label="request BodyRig revision"
    ):
        raise PhotorealAppearanceEpochVisualReviewError("appearance epoch review BodyRig revision mismatch")
    for field in ("performer_id", "dataset_plan_sha256", "source_receipt_sha256", "frame_index_sha256"):
        if manifest.get(field) != request.get(field):
            raise PhotorealAppearanceEpochVisualReviewError(f"appearance epoch review provenance mismatch: {field}")
    for field, expected in (
        ("source_paths_disclosed", False),
        ("source_media_rehash_performed", False),
        ("exact_p0_frame_hashes_reproduced", True),
        ("review_only", True),
        ("human_appearance_epoch_review_required", True),
        ("teacher_input_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if manifest.get(field) is not expected:
            raise PhotorealAppearanceEpochVisualReviewError(f"appearance epoch review authority mismatch: {field}")
    if _git_sha(private.get("bodyrig_revision"), label="private review BodyRig revision") != _git_sha(
        manifest.get("bodyrig_revision"), label="manifest BodyRig revision"
    ):
        raise PhotorealAppearanceEpochVisualReviewError("private appearance epoch review revision mismatch")
    if private.get("performer_id") != manifest.get("performer_id"):
        raise PhotorealAppearanceEpochVisualReviewError("private appearance epoch review performer mismatch")
    if private.get("source_paths_private") is not True or private.get("source_media_rehash_performed") is not False:
        raise PhotorealAppearanceEpochVisualReviewError("private appearance epoch review boundary is invalid")
    if private.get("production_activation") is not False:
        raise PhotorealAppearanceEpochVisualReviewError("private appearance epoch review crossed production authority")
    if _sha(private.get("public_manifest_sha256"), label="public manifest SHA-256") != _sha256_file(manifest_path):
        raise PhotorealAppearanceEpochVisualReviewError("private review index public-manifest binding mismatch")

    groups = manifest.get("groups")
    if not isinstance(groups, list) or not groups:
        raise PhotorealAppearanceEpochVisualReviewError("appearance epoch review manifest has no groups")
    frame_count = 0
    public_frame_ids: set[str] = set()
    split_groups = {"train": 0, "evaluation": 0}
    for group in groups:
        if not isinstance(group, Mapping):
            raise PhotorealAppearanceEpochVisualReviewError("appearance epoch review group is invalid")
        split = _text(group.get("split"), label="appearance epoch review group split", maximum=32)
        if split not in split_groups:
            raise PhotorealAppearanceEpochVisualReviewError("appearance epoch review group split is invalid")
        split_groups[split] += 1
        frames = group.get("frames")
        if not isinstance(frames, list) or not frames:
            raise PhotorealAppearanceEpochVisualReviewError("appearance epoch review group contains no frames")
        for frame in frames:
            if not isinstance(frame, Mapping):
                raise PhotorealAppearanceEpochVisualReviewError("appearance epoch review frame is invalid")
            frame_id = _text(frame.get("frame_id"), label="review frame id", maximum=128)
            if frame_id in public_frame_ids:
                raise PhotorealAppearanceEpochVisualReviewError("appearance epoch review repeats public frame id")
            public_frame_ids.add(frame_id)
            relative = Path(_text(frame.get("relative_path"), label="review frame relative path"))
            if relative.is_absolute() or ".." in relative.parts:
                raise PhotorealAppearanceEpochVisualReviewError("review frame path escapes review root")
            path = (output / relative).resolve()
            try:
                path.relative_to(output)
            except ValueError as exc:
                raise PhotorealAppearanceEpochVisualReviewError("review frame path escapes review root") from exc
            if _sha(frame.get("staged_png_sha256"), label="staged review PNG SHA-256") != _sha256_file(path):
                raise PhotorealAppearanceEpochVisualReviewError("staged review PNG bytes changed")
            frame_count += 1
    if min(split_groups.values()) < 1:
        raise PhotorealAppearanceEpochVisualReviewError("appearance epoch review lost train/evaluation groups")
    group_count = manifest.get("group_count")
    train_group_count = manifest.get("train_group_count")
    evaluation_group_count = manifest.get("evaluation_group_count")
    for value, expected, label in (
        (group_count, len(groups), "group count"),
        (train_group_count, split_groups["train"], "train group count"),
        (evaluation_group_count, split_groups["evaluation"], "evaluation group count"),
        (manifest.get("eligible_observation_count"), frame_count, "observation count"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value != expected:
            raise PhotorealAppearanceEpochVisualReviewError(f"appearance epoch review {label} mismatch")
    private_frames = private.get("frames")
    if not isinstance(private_frames, list) or len(private_frames) != frame_count:
        raise PhotorealAppearanceEpochVisualReviewError("private appearance epoch review frame count mismatch")
    private_frame_ids: set[str] = set()
    for raw in private_frames:
        if not isinstance(raw, Mapping):
            raise PhotorealAppearanceEpochVisualReviewError("private appearance epoch review frame is invalid")
        frame_id = _text(raw.get("frame_id"), label="private review frame id", maximum=128)
        if frame_id in private_frame_ids:
            raise PhotorealAppearanceEpochVisualReviewError("private appearance epoch review repeats frame id")
        private_frame_ids.add(frame_id)
        _text(raw.get("source_key"), label="private review source key")
        resolved_path = _text(raw.get("resolved_path"), label="private review resolved path")
        if not resolved_path.startswith("/"):
            raise PhotorealAppearanceEpochVisualReviewError("private appearance epoch review source path is not Linux absolute")
        _sha(raw.get("source_sha256"), label="private review source SHA-256")
    if private_frame_ids != public_frame_ids:
        raise PhotorealAppearanceEpochVisualReviewError("private/public appearance epoch review frame universe mismatch")
    return manifest


def _build_request_from_files(
    dataset_plan_path: Path,
    source_receipt_path: Path,
    frame_index_path: Path,
    runtime_path_map_path: Path,
    *,
    bodyrig_revision: str,
) -> dict[str, Any]:
    return build_review_request(
        _read_json(dataset_plan_path, label="dataset plan"),
        _read_json(source_receipt_path, label="source receipt"),
        _read_json(frame_index_path, label="frame index"),
        _read_json(runtime_path_map_path, label="appearance epoch runtime path map"),
        bodyrig_revision=bodyrig_revision,
        dataset_plan_sha256=_sha256_file(dataset_plan_path),
        source_receipt_sha256=_sha256_file(source_receipt_path),
        frame_index_sha256=_sha256_file(frame_index_path),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare an exact-frame BodyRig Photoreal V2 appearance-epoch human review pack.")
    sub = parser.add_subparsers(dest="command", required=True)

    path_map = sub.add_parser("path-map", help="Build/revalidate a private WSL runtime path map without hashing source media.")
    path_map.add_argument("--dataset-plan", type=Path, required=True)
    path_map.add_argument("--source-receipt", type=Path, required=True)
    path_map.add_argument("--frame-index", type=Path, required=True)
    path_map.add_argument("--wsl-exe", default="wsl.exe")
    path_map.add_argument("--distribution", default="Ubuntu-22.04")
    path_map.add_argument("--out", type=Path, required=True)

    prepare = sub.add_parser("prepare", help="Decode only exact P0-authorized observations and build the human visual review pack.")
    prepare.add_argument("--dataset-plan", type=Path, required=True)
    prepare.add_argument("--source-receipt", type=Path, required=True)
    prepare.add_argument("--frame-index", type=Path, required=True)
    prepare.add_argument("--runtime-path-map", type=Path, required=True)
    prepare.add_argument("--bodyrig-revision", required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--reuse-existing", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "path-map":
            from .wsl_adapter_bridge import make_wsl_path_converter

            converter = make_wsl_path_converter(args.wsl_exe, args.distribution)
            result = build_runtime_path_map_files(
                args.dataset_plan,
                args.source_receipt,
                args.frame_index,
                args.out,
                converter=converter,
            )
            print(
                json.dumps(
                    {
                        "status": "READY",
                        "source_count": result["source_count"],
                        "source_media_rehash_performed": result["source_media_rehash_performed"],
                        "path_map": str(args.out.expanduser().resolve()),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0

        request = _build_request_from_files(
            args.dataset_plan.expanduser().resolve(),
            args.source_receipt.expanduser().resolve(),
            args.frame_index.expanduser().resolve(),
            args.runtime_path_map.expanduser().resolve(),
            bodyrig_revision=args.bodyrig_revision,
        )
        manifest = prepare_review(
            request,
            args.output_dir,
            reuse_existing=args.reuse_existing,
        )
        print(
            json.dumps(
                {
                    "status": "READY",
                    "group_count": manifest["group_count"],
                    "eligible_observation_count": manifest["eligible_observation_count"],
                    "exact_p0_frame_hashes_reproduced": manifest["exact_p0_frame_hashes_reproduced"],
                    "source_media_rehash_performed": manifest["source_media_rehash_performed"],
                    "review_index": str(args.output_dir.expanduser().resolve() / "review-index.html"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except PhotorealAppearanceEpochVisualReviewError as exc:
        print(f"BodyRig appearance epoch visual review: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

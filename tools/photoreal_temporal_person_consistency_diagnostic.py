from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping

from bodyrig import photoreal_identity_group_review as review


FORMAT = "bodyrig-photoreal-temporal-person-consistency-diagnostic"
VERSION = 1
OFFSETS_SECONDS = (-0.20, -0.10, 0.0, 0.10, 0.20)
MIN_VALID_FRAMES = 3
KEYPOINT_SCORE_MIN = 0.30


class TemporalPersonConsistencyError(RuntimeError):
    pass


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TemporalPersonConsistencyError(f"could not load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TemporalPersonConsistencyError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise TemporalPersonConsistencyError(f"{label} must be a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bbox_iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    ix = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    iy = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = ix * iy
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return 0.0 if union <= 0.0 else intersection / union


def _center_shift(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    *,
    width: int,
    height: int,
) -> float:
    lx = (left[0] + left[2]) * 0.5
    ly = (left[1] + left[3]) * 0.5
    rx = (right[0] + right[2]) * 0.5
    ry = (right[1] + right[3]) * 0.5
    diagonal = math.hypot(max(1, width), max(1, height))
    return math.hypot(lx - rx, ly - ry) / diagonal


def _pose_candidates(adapter: Any, runtime: Any, image: Any) -> list[dict[str, Any]]:
    base = getattr(adapter, "base", adapter)
    predictions = base._pose_predictions(runtime, image)
    result: list[dict[str, Any]] = []
    for prediction in predictions:
        box = base._pose_bbox(prediction)
        if box is None:
            continue
        result.append({"bbox": tuple(float(value) for value in box), "pose": prediction})
    return result


def _keypoints(
    adapter: Any,
    prediction: Mapping[str, Any],
) -> dict[int, tuple[float, float]]:
    base = getattr(adapter, "base", adapter)
    points = base._listish(prediction.get("keypoints"))
    scores = base._listish(prediction.get("keypoint_scores")) or []
    if points is None:
        return {}
    if len(points) == 1:
        nested = base._listish(points[0])
        if nested is not None:
            points = nested
    if len(scores) == 1:
        nested_scores = base._listish(scores[0])
        if nested_scores is not None:
            scores = nested_scores
    result: dict[int, tuple[float, float]] = {}
    for index, raw in enumerate(points[:17]):
        point = base._listish(raw)
        if point is None or len(point) < 2:
            continue
        try:
            score = float(scores[index]) if index < len(scores) else 1.0
            x = float(point[0])
            y = float(point[1])
        except (TypeError, ValueError, OverflowError):
            continue
        if score >= KEYPOINT_SCORE_MIN and math.isfinite(x) and math.isfinite(y):
            result[index] = (x, y)
    return result


def _normalized_pose_distance(
    adapter: Any,
    anchor: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[float | None, int]:
    left = _keypoints(adapter, anchor["pose"])
    right = _keypoints(adapter, candidate["pose"])
    common = sorted(set(left) & set(right))
    if len(common) < 5:
        return None, len(common)
    box = anchor["bbox"]
    scale = max(1.0, math.hypot(box[2] - box[0], box[3] - box[1]))
    distances = [
        math.hypot(left[index][0] - right[index][0], left[index][1] - right[index][1])
        / scale
        for index in common
    ]
    return math.sqrt(sum(value * value for value in distances) / len(distances)), len(common)


def _crop(adapter: Any, image: Any, box: tuple[float, float, float, float]) -> Any:
    base = getattr(adapter, "base", adapter)
    return base._crop(image, box)


def _appearance_histogram(
    adapter: Any,
    runtime: Any,
    image: Any,
    box: tuple[float, float, float, float],
) -> Any:
    crop = _crop(adapter, image, box)
    if crop is None or getattr(crop, "size", 0) == 0:
        raise TemporalPersonConsistencyError("person crop is empty")
    height, width = crop.shape[:2]
    # Trim edges to reduce background leakage while preserving torso/clothing.
    x1 = max(0, int(round(width * 0.12)))
    x2 = min(width, int(round(width * 0.88)))
    y1 = max(0, int(round(height * 0.08)))
    y2 = min(height, int(round(height * 0.92)))
    inner = crop[y1:y2, x1:x2]
    if inner is None or getattr(inner, "size", 0) == 0:
        inner = crop
    hsv = runtime.cv2.cvtColor(inner, runtime.cv2.COLOR_BGR2HSV)
    hist = runtime.cv2.calcHist([hsv], [0, 1], None, [24, 8], [0, 180, 0, 256])
    hist = runtime.np.asarray(hist, dtype=runtime.np.float64).reshape(-1)
    norm = float(runtime.np.linalg.norm(hist))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise TemporalPersonConsistencyError("appearance histogram is degenerate")
    return hist / norm


def _histogram_cosine(np: Any, left: Any, right: Any) -> float:
    value = float(np.dot(left, right))
    if not math.isfinite(value):
        raise TemporalPersonConsistencyError("appearance similarity is non-finite")
    return max(0.0, min(1.0, value))


def _project_anchor_view(
    *,
    representation: Any,
    adapter: Any,
    runtime: Any,
    source: Mapping[str, Any],
    sample: Mapping[str, Any],
    anchor_viewport: Mapping[str, Any] | None,
) -> Any:
    eye_image, spatial = adapter._read_sample(runtime, source, sample)
    if not spatial:
        return eye_image
    if anchor_viewport is None:
        raise TemporalPersonConsistencyError("spatial neighbor lacks anchor viewport")
    if source.get("projection") != "equi":
        raise TemporalPersonConsistencyError(
            "temporal consistency currently supports equirectangular spatial sources only"
        )
    authority = source.get("projection_authority")
    if not isinstance(authority, Mapping):
        raise TemporalPersonConsistencyError("spatial source lacks projection authority")
    height, width = eye_image.shape[:2]
    map_x, map_y = representation.build_equirectangular_remap(
        runtime.np,
        image_width=width,
        image_height=height,
        projection_authority=authority,
        viewport=anchor_viewport,
    )
    image = runtime.cv2.remap(
        eye_image,
        map_x,
        map_y,
        interpolation=runtime.cv2.INTER_LINEAR,
        borderMode=runtime.cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    if image is None or getattr(image, "size", 0) == 0:
        raise TemporalPersonConsistencyError("anchor-view projection produced empty image")
    return runtime.np.ascontiguousarray(image)


def _choose_anchor_candidate(
    adapter: Any,
    runtime: Any,
    image: Any,
) -> dict[str, Any] | None:
    candidates = _pose_candidates(adapter, runtime, image)
    return candidates[0] if len(candidates) == 1 else None


def _choose_neighbor_candidate(
    *,
    anchor: Mapping[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float]:
    if not candidates:
        return None, 0.0
    ranked = sorted(
        ((candidate, _bbox_iou(anchor["bbox"], candidate["bbox"])) for candidate in candidates),
        key=lambda pair: pair[1],
        reverse=True,
    )
    candidate, iou = ranked[0]
    if iou <= 0.0:
        return None, 0.0
    return candidate, iou


def _track_anchor(
    *,
    representation: Any,
    adapter: Any,
    runtime: Any,
    source: Mapping[str, Any],
    sample: Mapping[str, Any],
    anchor_image: Any,
    anchor_viewport: Mapping[str, Any] | None,
    anchor_kind: str,
    anchor_index: int,
    group_id: str | None,
    subject_label: str | None,
) -> dict[str, Any]:
    anchor = _choose_anchor_candidate(adapter, runtime, anchor_image)
    base = {
        "anchor_kind": anchor_kind,
        "anchor_index": anchor_index,
        "group_id": group_id,
        "comparison_subject_label": subject_label,
        "offsets_seconds": list(OFFSETS_SECONDS),
        "minimum_valid_frames": MIN_VALID_FRAMES,
        "uses_face_recognition": False,
        "uses_face_embedding": False,
        "uses_biometric_identity_decision": False,
    }
    if anchor is None:
        return {**base, "status": "anchor-not-single-pose-person", "valid_frame_count": 0}

    timestamp = sample.get("timestamp_seconds")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return {**base, "status": "anchor-timestamp-invalid", "valid_frame_count": 0}

    anchor_hist = _appearance_histogram(adapter, runtime, anchor_image, anchor["bbox"])
    height, width = anchor_image.shape[:2]
    observations: list[dict[str, Any]] = [
        {
            "offset_seconds": 0.0,
            "status": "anchor",
            "bbox_iou": 1.0,
            "center_shift": 0.0,
            "appearance_cosine": 1.0,
            "pose_distance": 0.0,
            "common_keypoint_count": len(_keypoints(adapter, anchor["pose"])),
        }
    ]

    if str(source.get("kind") or "") != "video":
        return {
            **base,
            "status": "not-applicable-non-video",
            "valid_frame_count": 1,
            "observations": observations,
        }

    for offset in OFFSETS_SECONDS:
        if abs(offset) <= 1e-12:
            continue
        target = float(timestamp) + float(offset)
        if target < 0.0:
            observations.append(
                {"offset_seconds": offset, "status": "before-source-start"}
            )
            continue
        neighbor_sample = dict(sample)
        neighbor_sample["timestamp_seconds"] = target
        try:
            image = _project_anchor_view(
                representation=representation,
                adapter=adapter,
                runtime=runtime,
                source=source,
                sample=neighbor_sample,
                anchor_viewport=anchor_viewport,
            )
            candidates = _pose_candidates(adapter, runtime, image)
            candidate, iou = _choose_neighbor_candidate(
                anchor=anchor,
                candidates=candidates,
            )
            if candidate is None:
                observations.append(
                    {
                        "offset_seconds": offset,
                        "status": "no-overlapping-pose-candidate",
                        "pose_candidate_count": len(candidates),
                    }
                )
                continue
            histogram = _appearance_histogram(
                adapter,
                runtime,
                image,
                candidate["bbox"],
            )
            pose_distance, common = _normalized_pose_distance(
                adapter,
                anchor,
                candidate,
            )
            observations.append(
                {
                    "offset_seconds": offset,
                    "status": "available",
                    "pose_candidate_count": len(candidates),
                    "bbox_iou": round(iou, 9),
                    "center_shift": round(
                        _center_shift(
                            anchor["bbox"],
                            candidate["bbox"],
                            width=width,
                            height=height,
                        ),
                        9,
                    ),
                    "appearance_cosine": round(
                        _histogram_cosine(runtime.np, anchor_hist, histogram),
                        9,
                    ),
                    "pose_distance": (
                        None if pose_distance is None else round(pose_distance, 9)
                    ),
                    "common_keypoint_count": common,
                }
            )
        except Exception as exc:  # noqa: BLE001
            observations.append(
                {
                    "offset_seconds": offset,
                    "status": type(exc).__name__,
                }
            )

    available = [
        row
        for row in observations
        if row.get("status") in {"anchor", "available"}
    ]
    neighbor_rows = [row for row in observations if row.get("status") == "available"]
    if len(available) < MIN_VALID_FRAMES:
        status = "insufficient-valid-frames"
    else:
        status = "available"

    def median(field: str) -> float | None:
        values = [
            float(row[field])
            for row in neighbor_rows
            if row.get(field) is not None
        ]
        return None if not values else round(statistics.median(values), 9)

    return {
        **base,
        "status": status,
        "valid_frame_count": len(available),
        "neighbor_available_count": len(neighbor_rows),
        "median_bbox_iou": median("bbox_iou"),
        "median_center_shift": median("center_shift"),
        "median_appearance_cosine": median("appearance_cosine"),
        "median_pose_distance": median("pose_distance"),
        "observations": observations,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    available = [row for row in rows if row.get("status") == "available"]

    def distribution(field: str) -> dict[str, float] | None:
        values = [
            float(row[field])
            for row in available
            if row.get(field) is not None
        ]
        if not values:
            return None
        return {
            "min": round(min(values), 9),
            "median": round(statistics.median(values), 9),
            "max": round(max(values), 9),
        }

    return {
        "anchor_count": len(rows),
        "available_anchor_count": len(available),
        "coverage": round(0.0 if not rows else len(available) / len(rows), 9),
        "median_bbox_iou": distribution("median_bbox_iou"),
        "median_center_shift": distribution("median_center_shift"),
        "median_appearance_cosine": distribution("median_appearance_cosine"),
        "median_pose_distance": distribution("median_pose_distance"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnostic-only short-window person consistency analysis using pose, "
            "bounding boxes and clothing/appearance histograms. It performs no "
            "face recognition, face embedding, or biometric identity decision."
        )
    )
    parser.add_argument("--identity-bank", type=Path, required=True)
    parser.add_argument("--identity-request", type=Path, required=True)
    parser.add_argument("--identity-request-origin", type=Path, required=True)
    parser.add_argument("--calibration-request", type=Path, required=True)
    parser.add_argument("--calibration-request-origin", type=Path, required=True)
    parser.add_argument("--negative-observations", type=Path, required=True)
    parser.add_argument("--review-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.out.expanduser().resolve()
    if output.exists():
        raise TemporalPersonConsistencyError(f"output already exists: {output}")

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    representation = _load_module(
        repo_root / "tools" / "photoreal_identity_representation_diagnostic.py",
        "bodyrig_temporal_consistency_projection_dependency",
    )
    adapter = representation._load_adapter(repo_root)
    adapter_revision = adapter._self_revision()

    bank_path = args.identity_bank.expanduser().resolve()
    bank = _read_json(bank_path, label="anchor bank")
    performer_id, bank_sha = review._validate_bank(
        bank,
        adapter_revision=adapter_revision,
    )

    identity_request = _read_json(
        args.identity_request.expanduser().resolve(),
        label="Stage-7 execution request",
    )
    identity_request_origin = _read_json(
        args.identity_request_origin.expanduser().resolve(),
        label="Stage-7 original request",
    )
    representation._request_transport_equivalent(
        identity_request_origin,
        identity_request,
    )
    identity_sources = review._validate_request(
        identity_request,
        performer_id=performer_id,
        bank=bank,
        adapter_revision=adapter_revision,
    )

    review_root = args.review_root.expanduser().resolve()
    attestation = representation._validate_attestation(
        review_root=review_root,
        bank=bank,
    )

    calibration_request = _read_json(
        args.calibration_request.expanduser().resolve(),
        label="Stage-13 execution request",
    )
    calibration_request_origin = _read_json(
        args.calibration_request_origin.expanduser().resolve(),
        label="Stage-13 original request",
    )
    representation._request_transport_equivalent(
        calibration_request_origin,
        calibration_request,
    )
    calibration_sources_raw = calibration_request.get("sources")
    if not isinstance(calibration_sources_raw, list):
        raise TemporalPersonConsistencyError("Stage-13 request sources are invalid")
    calibration_sources = {
        str(source.get("source_key") or "").strip(): source
        for source in calibration_sources_raw
        if isinstance(source, Mapping)
    }

    negative_document = _read_json(
        args.negative_observations.expanduser().resolve(),
        label="comparison observations",
    )
    raw_negatives = negative_document.get("observations")
    if not isinstance(raw_negatives, list):
        raise TemporalPersonConsistencyError("comparison observations are invalid")

    model_root = args.model_root.expanduser().resolve()
    model_set = adapter.build_model_set(model_root)
    if str(model_set.get("model_set_sha256") or "").strip().lower() != str(
        bank.get("model_set_sha256") or ""
    ).strip().lower():
        raise TemporalPersonConsistencyError("model root does not match anchor bank")
    manifest = adapter._load_model_manifest(model_root)
    runtime = adapter._load_runtime(manifest, device=args.device)

    target_rows: list[dict[str, Any]] = []
    references = bank.get("references")
    if not isinstance(references, list):
        raise TemporalPersonConsistencyError("anchor bank references are invalid")
    for index, raw in enumerate(references):
        if not isinstance(raw, Mapping):
            raise TemporalPersonConsistencyError("anchor reference is invalid")
        source_key = str(raw.get("source_key") or "").strip()
        source = identity_sources.get(source_key)
        if source is None:
            raise TemporalPersonConsistencyError(
                f"anchor source absent from Stage-7 request: {source_key}"
            )
        sample_key = review._sample_key(raw.get("timestamp_seconds"), raw.get("eye"))
        samples = source.get("reference_samples")
        if not isinstance(samples, list):
            raise TemporalPersonConsistencyError("anchor source lacks reference_samples")
        matches = [
            sample
            for sample in samples
            if isinstance(sample, Mapping)
            and review._sample_key(
                sample.get("timestamp_seconds"),
                sample.get("eye"),
            )
            == sample_key
        ]
        if len(matches) != 1:
            raise TemporalPersonConsistencyError(
                "anchor reference did not resolve exactly once"
            )
        sample = matches[0]
        image, _viewport_id, viewport, _eye_image, _spatial = (
            representation._match_exact_viewport(
                adapter=adapter,
                runtime=runtime,
                source=source,
                sample=sample,
                expected_frame_sha=str(raw.get("frame_sha256") or "").strip().lower(),
            )
        )
        target_rows.append(
            _track_anchor(
                representation=representation,
                adapter=adapter,
                runtime=runtime,
                source=source,
                sample=sample,
                anchor_image=image,
                anchor_viewport=viewport,
                anchor_kind="attested-target-anchor",
                anchor_index=index,
                group_id=str(raw.get("group_id") or "").strip(),
                subject_label=None,
            )
        )

    comparison_rows: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_negatives):
        if not isinstance(raw, Mapping):
            raise TemporalPersonConsistencyError("comparison observation is invalid")
        source_key = str(raw.get("source_key") or "").strip()
        source = calibration_sources.get(source_key)
        if source is None:
            raise TemporalPersonConsistencyError(
                f"comparison source absent from Stage-13 request: {source_key}"
            )
        wanted = review._sample_key(raw.get("timestamp_seconds"), raw.get("eye"))
        samples = source.get("samples")
        if not isinstance(samples, list):
            raise TemporalPersonConsistencyError("comparison source lacks samples")
        matches = [
            sample
            for sample in samples
            if isinstance(sample, Mapping)
            and review._sample_key(
                sample.get("timestamp_seconds"),
                sample.get("eye"),
            )
            == wanted
        ]
        if len(matches) != 1:
            raise TemporalPersonConsistencyError(
                "comparison observation did not resolve exactly once"
            )
        sample = matches[0]
        image, spatial = adapter._read_sample(runtime, source, sample)
        if spatial:
            raise TemporalPersonConsistencyError(
                "comparison anchor unexpectedly requires spatial deprojection"
            )
        expected_sha = str(raw.get("frame_sha256") or "").strip().lower()
        if adapter._frame_sha(image) != expected_sha:
            raise TemporalPersonConsistencyError(
                "comparison anchor frame SHA no longer reproduces"
            )
        comparison_rows.append(
            _track_anchor(
                representation=representation,
                adapter=adapter,
                runtime=runtime,
                source=source,
                sample=sample,
                anchor_image=image,
                anchor_viewport=None,
                anchor_kind="comparison-anchor",
                anchor_index=index,
                group_id=None,
                subject_label=str(raw.get("subject_performer_id") or "").strip(),
            )
        )

    revision = str(os.environ.get("BODYRIG_REVISION") or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise TemporalPersonConsistencyError(
            "BODYRIG_REVISION must bind execution to exact Git HEAD"
        )

    result = {
        "format": FORMAT,
        "version": VERSION,
        "bodyrig_revision": revision,
        "performer_id": performer_id,
        "anchor_bank_sha256": bank_sha,
        "anchor_bank_file_sha256": _sha256_file(bank_path),
        "attestation_bodyrig_revision": attestation.get("attestation_bodyrig_revision"),
        "offsets_seconds": list(OFFSETS_SECONDS),
        "minimum_valid_frames": MIN_VALID_FRAMES,
        "target_anchor_summary": _summary(target_rows),
        "comparison_anchor_summary": _summary(comparison_rows),
        "target_anchors": target_rows,
        "comparison_anchors": comparison_rows,
        "uses_face_recognition": False,
        "uses_face_embedding": False,
        "uses_biometric_identity_decision": False,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "diagnostic_only": True,
        "source_rehash_required": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

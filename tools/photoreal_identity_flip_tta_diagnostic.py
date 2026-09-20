from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from bodyrig import photoreal_identity_calibration as calibration
from bodyrig import photoreal_identity_group_review as review


FORMAT = "bodyrig-photoreal-identity-flip-tta-diagnostic"
VERSION = 1
CALIBRATION_REQUEST_FORMAT = "bodyrig-photoreal-identity-calibration-extractor-request"
NEGATIVE_OBSERVATIONS_FORMAT = "bodyrig-photoreal-identity-negative-observations"


class PhotorealIdentityFlipTtaDiagnosticError(RuntimeError):
    pass


def _load_representation_tool(repo_root: Path):
    path = repo_root / "tools" / "photoreal_identity_representation_diagnostic.py"
    spec = importlib.util.spec_from_file_location(
        "bodyrig_identity_flip_tta_representation",
        path,
    )
    if spec is None or spec.loader is None:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            f"could not load representation diagnostic: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            f"{label} is unreadable: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            f"{label} must be a JSON object"
        )
    return value


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotorealIdentityFlipTtaDiagnosticError(
            f"required file is missing: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(
        character not in "0123456789abcdef" for character in result
    ):
        raise PhotorealIdentityFlipTtaDiagnosticError(f"{label} is invalid")
    return result


def _normalize(vector: Any, *, dimension: int, label: str) -> list[float]:
    if not isinstance(vector, (list, tuple)) or len(vector) != dimension:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            f"{label} dimension mismatch"
        )
    try:
        values = [float(item) for item in vector]
    except (TypeError, ValueError, OverflowError) as exc:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            f"{label} contains invalid value"
        ) from exc
    if any(not math.isfinite(item) for item in values):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            f"{label} contains non-finite value"
        )
    norm = math.sqrt(sum(item * item for item in values))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            f"{label} has invalid norm"
        )
    return [item / norm for item in values]


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "cannot build centroid from no embeddings"
        )
    dimension = len(vectors[0])
    if any(len(vector) != dimension for vector in vectors):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "embedding dimensions are inconsistent"
        )
    return _normalize(
        [
            sum(vector[index] for vector in vectors) / len(vectors)
            for index in range(dimension)
        ],
        dimension=dimension,
        label="embedding centroid",
    )


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "embedding dimensions are inconsistent"
        )
    return max(
        -1.0,
        min(
            1.0,
            sum(a * b for a, b in zip(left, right, strict=True)),
        ),
    )


def _tta_mean(
    original: list[float],
    flipped: list[float],
    *,
    dimension: int,
) -> list[float]:
    left = _normalize(
        original,
        dimension=dimension,
        label="original TTA embedding",
    )
    right = _normalize(
        flipped,
        dimension=dimension,
        label="flipped TTA embedding",
    )
    return _normalize(
        [a + b for a, b in zip(left, right, strict=True)],
        dimension=dimension,
        label="flip-TTA mean embedding",
    )


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "cannot summarize empty score set"
        )
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        median = ordered[middle]
    else:
        median = (ordered[middle - 1] + ordered[middle]) / 2.0
    return {
        "min": round(min(values), 9),
        "median": round(median, 9),
        "max": round(max(values), 9),
    }


def _sample_key(timestamp: Any, eye: Any) -> tuple[float | None, str]:
    if timestamp is None:
        normalized_timestamp = None
    else:
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise PhotorealIdentityFlipTtaDiagnosticError(
                "sample timestamp is invalid"
            )
        normalized_timestamp = round(float(timestamp), 6)
    normalized_eye = str(eye or "").strip()
    if normalized_eye not in {"mono", "left", "right"}:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "sample eye is invalid"
        )
    return normalized_timestamp, normalized_eye


def _validate_calibration_request(
    request: Mapping[str, Any],
    *,
    performer_id: str,
    bank: Mapping[str, Any],
    adapter_revision: str,
) -> dict[str, Mapping[str, Any]]:
    if (
        request.get("format") != CALIBRATION_REQUEST_FORMAT
        or request.get("version") != 1
    ):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity calibration request format/version mismatch"
        )
    if str(request.get("target_performer_id") or "") != performer_id:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity calibration request target performer mismatch"
        )
    if _sha(
        request.get("identity_bank_sha256"),
        label="calibration request bank SHA-256",
    ) != _sha(bank.get("identity_bank_sha256"), label="identity bank SHA-256"):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity calibration request targets a different bank"
        )
    if request.get("adapter") != bank.get("extractor"):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity calibration request adapter mismatch"
        )
    if request.get("revision") != adapter_revision:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity calibration request adapter revision mismatch"
        )
    if _sha(
        request.get("model_set_sha256"),
        label="calibration request model-set SHA-256",
    ) != _sha(bank.get("model_set_sha256"), label="identity bank model-set SHA-256"):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity calibration request model set mismatch"
        )
    if request.get("embedding_dimension") != bank.get("embedding_dimension"):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity calibration request embedding dimension mismatch"
        )
    if (
        request.get("measurement_only") is not True
        or request.get("calibration_only") is not True
        or request.get("identity_matching_authority") is not False
        or request.get("teacher_training_authority") is not False
        or request.get("photoreal_acceptance_authority") is not False
        or request.get("production_activation") is not False
    ):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity calibration request authority boundary is invalid"
        )
    raw_sources = request.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity calibration request contains no sources"
        )
    sources: dict[str, Mapping[str, Any]] = {}
    for raw in raw_sources:
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityFlipTtaDiagnosticError(
                "identity calibration request source is invalid"
            )
        source_key = str(raw.get("source_key") or "").strip()
        if not source_key or source_key in sources:
            raise PhotorealIdentityFlipTtaDiagnosticError(
                "identity calibration request source key is invalid/duplicated"
            )
        samples = raw.get("samples")
        if not isinstance(samples, list) or not samples:
            raise PhotorealIdentityFlipTtaDiagnosticError(
                f"identity calibration source has no samples: {source_key}"
            )
        sources[source_key] = raw
    return sources


def _validate_negative_observations(
    observations: Mapping[str, Any],
    *,
    performer_id: str,
    bank: Mapping[str, Any],
    adapter_revision: str,
    sources: Mapping[str, Mapping[str, Any]],
    dimension: int,
) -> list[dict[str, Any]]:
    if (
        observations.get("format") != NEGATIVE_OBSERVATIONS_FORMAT
        or observations.get("version") != 1
    ):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity negative observations format/version mismatch"
        )
    if str(observations.get("target_performer_id") or "") != performer_id:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity negative observations target performer mismatch"
        )
    if _sha(
        observations.get("identity_bank_sha256"),
        label="negative observations bank SHA-256",
    ) != _sha(bank.get("identity_bank_sha256"), label="identity bank SHA-256"):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity negative observations target a different bank"
        )
    if observations.get("extractor") != bank.get("extractor"):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity negative observations extractor mismatch"
        )
    if observations.get("extractor_revision") != adapter_revision:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity negative observations extractor revision mismatch"
        )
    if _sha(
        observations.get("model_set_sha256"),
        label="negative observations model-set SHA-256",
    ) != _sha(bank.get("model_set_sha256"), label="identity bank model-set SHA-256"):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity negative observations model set mismatch"
        )
    if observations.get("embedding_dimension") != dimension:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity negative observations embedding dimension mismatch"
        )
    if (
        observations.get("calibration_only") is not True
        or observations.get("build_only") is not True
        or observations.get("identity_matching_authority", False) is not False
        or observations.get("teacher_training_authorized", False) is not False
        or observations.get("photoreal_acceptance_authority", False) is not False
        or observations.get("production_activation") is not False
    ):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity negative observations authority boundary is invalid"
        )

    raw_observations = observations.get("observations")
    if not isinstance(raw_observations, list) or not raw_observations:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity negative observations are empty"
        )
    result: list[dict[str, Any]] = []
    seen_frames: set[str] = set()
    for index, raw in enumerate(raw_observations):
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityFlipTtaDiagnosticError(
                "identity negative observation is invalid"
            )
        source_key = str(raw.get("source_key") or "").strip()
        source = sources.get(source_key)
        if source is None:
            raise PhotorealIdentityFlipTtaDiagnosticError(
                f"negative observation uses unplanned source: {source_key}"
            )
        if _sha(
            raw.get("source_sha256"),
            label="negative source SHA-256",
        ) != _sha(source.get("source_sha256"), label="planned source SHA-256"):
            raise PhotorealIdentityFlipTtaDiagnosticError(
                f"negative source bytes changed: {source_key}"
            )
        subject = str(raw.get("subject_performer_id") or "").strip()
        if subject != str(source.get("subject_performer_id") or "").strip():
            raise PhotorealIdentityFlipTtaDiagnosticError(
                "negative observation subject performer changed"
            )
        wanted_sample = _sample_key(
            raw.get("timestamp_seconds"),
            raw.get("eye"),
        )
        planned_samples = {
            _sample_key(item.get("timestamp_seconds"), item.get("eye"))
            for item in source.get("samples") or []
            if isinstance(item, Mapping)
        }
        if wanted_sample not in planned_samples:
            raise PhotorealIdentityFlipTtaDiagnosticError(
                f"negative observation sample was not planned: {source_key}"
            )
        frame_sha = _sha(
            raw.get("frame_sha256"),
            label="negative frame SHA-256",
        )
        if frame_sha in seen_frames:
            raise PhotorealIdentityFlipTtaDiagnosticError(
                "negative observation frame is duplicated"
            )
        seen_frames.add(frame_sha)
        result.append(
            {
                "index": index,
                "source_key": source_key,
                "source": source,
                "timestamp_seconds": raw.get("timestamp_seconds"),
                "eye": str(raw.get("eye") or ""),
                "subject_performer_id": subject,
                "frame_sha256": frame_sha,
                "stored_embedding": _normalize(
                    raw.get("embedding"),
                    dimension=dimension,
                    label=f"negative stored embedding[{index}]",
                ),
            }
        )
    return result


def _find_sample(
    source: Mapping[str, Any],
    *,
    field: str,
    timestamp: Any,
    eye: Any,
) -> Mapping[str, Any]:
    wanted = _sample_key(timestamp, eye)
    matches = [
        sample
        for sample in source.get(field) or []
        if isinstance(sample, Mapping)
        and _sample_key(sample.get("timestamp_seconds"), sample.get("eye")) == wanted
    ]
    if len(matches) != 1:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            f"sample did not resolve exactly once in {field}"
        )
    return matches[0]


def _flip_measurement(
    *,
    representation: Any,
    adapter: Any,
    runtime: Any,
    image: Any,
) -> tuple[list[float] | None, dict[str, Any]]:
    flipped = runtime.cv2.flip(image, 1)
    if flipped is None or getattr(flipped, "size", 0) == 0:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "horizontal flip produced an empty image"
        )
    flipped = runtime.np.ascontiguousarray(flipped)
    return representation._single_face_measurement(
        adapter=adapter,
        runtime=runtime,
        image=flipped,
    )


def _aligned_crop_flip_measurement(
    *,
    adapter: Any,
    runtime: Any,
    image: Any,
    original_embedding: list[float],
    dimension: int,
) -> tuple[list[float], dict[str, Any]]:
    candidates = adapter._candidates(runtime, image)
    face_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("face") is not None
    ]
    if len(candidates) != 1 or len(face_candidates) != 1:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "accepted original frame did not reproduce exactly one aligned face candidate"
        )
    face = face_candidates[0]["face"]
    replay_embedding = adapter._embedding(face, dimension)
    if replay_embedding is None:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "accepted original face has no embedding for aligned-crop flip"
        )
    replay_cosine = _cosine(replay_embedding, original_embedding)
    if replay_cosine < 0.999999:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "aligned-crop source face does not match the original replay embedding"
        )

    models = getattr(runtime.face_app, "models", None)
    recognizer = models.get("recognition") if isinstance(models, Mapping) else None
    if recognizer is None or not callable(getattr(recognizer, "get_feat", None)):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "InsightFace recognition model does not expose get_feat"
        )
    input_size = getattr(recognizer, "input_size", None)
    if (
        not isinstance(input_size, (list, tuple))
        or len(input_size) != 2
        or int(input_size[0]) != int(input_size[1])
        or int(input_size[0]) <= 0
    ):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "InsightFace recognition input size is invalid"
        )
    landmarks = getattr(face, "kps", None)
    if landmarks is None:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "accepted original face has no five-point landmarks"
        )

    try:
        from insightface.utils import face_align

        aligned = face_align.norm_crop(
            image,
            landmark=landmarks,
            image_size=int(input_size[0]),
        )
        aligned = runtime.np.ascontiguousarray(aligned)
        aligned_original_raw = recognizer.get_feat(aligned)
        flipped_crop = runtime.cv2.flip(aligned, 1)
        if flipped_crop is None or getattr(flipped_crop, "size", 0) == 0:
            raise ValueError("aligned horizontal flip produced an empty crop")
        flipped_crop = runtime.np.ascontiguousarray(flipped_crop)
        aligned_flip_raw = recognizer.get_feat(flipped_crop)
    except Exception as exc:  # noqa: BLE001
        raise PhotorealIdentityFlipTtaDiagnosticError(
            f"aligned-crop recognition inference failed: {exc}"
        ) from exc

    aligned_original = _normalize(
        runtime.np.asarray(aligned_original_raw).reshape(-1).tolist(),
        dimension=dimension,
        label="aligned original recognition embedding",
    )
    aligned_flip = _normalize(
        runtime.np.asarray(aligned_flip_raw).reshape(-1).tolist(),
        dimension=dimension,
        label="aligned flipped recognition embedding",
    )
    aligned_replay_cosine = _cosine(aligned_original, original_embedding)
    if aligned_replay_cosine < 0.999999:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "direct recognition replay does not match FaceAnalysis embedding"
        )
    return aligned_flip, {
        "status": "available",
        "recognition_input_size": int(input_size[0]),
        "original_face_replay_cosine": round(replay_cosine, 9),
        "aligned_original_replay_cosine": round(aligned_replay_cosine, 9),
    }


def _score_models(
    positives: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
) -> dict[str, Any]:
    if not positives or not negatives:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "scoring requires positive and negative embeddings"
        )
    groups: dict[str, list[list[float]]] = defaultdict(list)
    for item in positives:
        groups[str(item["group_id"])].append(item["embedding"])
    if len(groups) < 2:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "scoring requires at least two positive groups"
        )
    ordered_groups = sorted(groups)
    group_centroids = {
        group_id: _centroid(groups[group_id])
        for group_id in ordered_groups
    }

    reference_weighted_positive: list[float] = []
    all_positive_vectors = [item["embedding"] for item in positives]
    for item in positives:
        others = [
            other["embedding"]
            for other in positives
            if other["group_id"] != item["group_id"]
        ]
        if not others:
            raise PhotorealIdentityFlipTtaDiagnosticError(
                "positive group has no leave-group-out peers"
            )
        reference_weighted_positive.append(
            _cosine(item["embedding"], _centroid(others))
        )
    reference_weighted_target = _centroid(all_positive_vectors)
    reference_weighted_negative = [
        _cosine(item["embedding"], reference_weighted_target)
        for item in negatives
    ]

    group_balanced_positive: list[float] = []
    nearest_positive: list[float] = []
    for group_id in ordered_groups:
        own = group_centroids[group_id]
        other_centroids = [
            group_centroids[other]
            for other in ordered_groups
            if other != group_id
        ]
        group_balanced_positive.append(
            _cosine(own, _centroid(other_centroids))
        )
        nearest_positive.append(
            max(_cosine(own, other) for other in other_centroids)
        )
    group_balanced_target = _centroid(
        [group_centroids[group_id] for group_id in ordered_groups]
    )
    group_balanced_negative = [
        _cosine(item["embedding"], group_balanced_target)
        for item in negatives
    ]
    nearest_negative = [
        max(
            _cosine(item["embedding"], group_centroids[group_id])
            for group_id in ordered_groups
        )
        for item in negatives
    ]

    raw_models = {
        "current-reference-weighted": (
            reference_weighted_positive,
            reference_weighted_negative,
        ),
        "group-balanced-centroid-lgo": (
            group_balanced_positive,
            group_balanced_negative,
        ),
        "nearest-group-prototype": (
            nearest_positive,
            nearest_negative,
        ),
    }
    result: dict[str, Any] = {}
    for name, (positive_scores, negative_scores) in raw_models.items():
        positive_floor = min(positive_scores)
        negative_ceiling = max(negative_scores)
        observed_margin = positive_floor - negative_ceiling
        result[name] = {
            "positive_score_count": len(positive_scores),
            "negative_score_count": len(negative_scores),
            "positive_cosine": _summary(positive_scores),
            "negative_cosine": _summary(negative_scores),
            "positive_floor": round(positive_floor, 9),
            "negative_ceiling": round(negative_ceiling, 9),
            "observed_separation_margin": round(observed_margin, 9),
            "minimum_required_separation_margin": (
                calibration.MIN_COSINE_SEPARATION_MARGIN
            ),
            "would_meet_margin": (
                observed_margin >= calibration.MIN_COSINE_SEPARATION_MARGIN
            ),
            "diagnostic_only": True,
        }
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay the exact human-attested Photoreal identity evidence and "
            "compare original, frame-level flip and aligned-crop flip-TTA "
            "embeddings without changing the identity bank or granting authority."
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
        raise PhotorealIdentityFlipTtaDiagnosticError(
            f"diagnostic output already exists: {output}"
        )

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    representation = _load_representation_tool(repo_root)
    adapter = representation._load_adapter(repo_root)
    adapter_revision = adapter._self_revision()

    bank_path = args.identity_bank.expanduser().resolve()
    identity_request_path = args.identity_request.expanduser().resolve()
    identity_request_origin_path = args.identity_request_origin.expanduser().resolve()
    calibration_request_path = args.calibration_request.expanduser().resolve()
    calibration_request_origin_path = (
        args.calibration_request_origin.expanduser().resolve()
    )
    negative_observations_path = args.negative_observations.expanduser().resolve()
    review_root = args.review_root.expanduser().resolve()
    model_root = args.model_root.expanduser().resolve()

    bank = _read_json(bank_path, label="identity bank")
    performer_id, bank_sha = review._validate_bank(
        bank,
        adapter_revision=adapter_revision,
    )
    dimension = bank.get("embedding_dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity bank embedding dimension is invalid"
        )

    identity_request = _read_json(
        identity_request_path,
        label="Stage-7 identity execution request",
    )
    identity_request_origin = _read_json(
        identity_request_origin_path,
        label="Stage-7 identity original request",
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
    attestation = representation._validate_attestation(
        review_root=review_root,
        bank=bank,
    )

    calibration_request = _read_json(
        calibration_request_path,
        label="Stage-13 calibration execution request",
    )
    calibration_request_origin = _read_json(
        calibration_request_origin_path,
        label="Stage-13 calibration original request",
    )
    representation._request_transport_equivalent(
        calibration_request_origin,
        calibration_request,
    )
    calibration_sources = _validate_calibration_request(
        calibration_request,
        performer_id=performer_id,
        bank=bank,
        adapter_revision=adapter_revision,
    )
    negative_observations = _read_json(
        negative_observations_path,
        label="identity negative observations",
    )
    negatives = _validate_negative_observations(
        negative_observations,
        performer_id=performer_id,
        bank=bank,
        adapter_revision=adapter_revision,
        sources=calibration_sources,
        dimension=dimension,
    )

    model_set = adapter.build_model_set(model_root)
    if _sha(
        model_set.get("model_set_sha256"),
        label="runtime model-set SHA-256",
    ) != _sha(bank.get("model_set_sha256"), label="identity bank model-set SHA-256"):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "model root does not match identity bank model set"
        )
    manifest = adapter._load_model_manifest(model_root)
    runtime = adapter._load_runtime(manifest, device=args.device)
    if runtime.embedding_dimension != dimension:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "runtime embedding dimension does not match identity bank"
        )

    references = bank.get("references")
    if not isinstance(references, list) or not references:
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "identity bank contains no references"
        )

    positive_variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    negative_variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    reference_diagnostics: list[dict[str, Any]] = []

    for index, raw in enumerate(references):
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityFlipTtaDiagnosticError(
                "identity bank reference is invalid"
            )
        source_key = str(raw.get("source_key") or "").strip()
        source = identity_sources.get(source_key)
        if source is None:
            raise PhotorealIdentityFlipTtaDiagnosticError(
                f"identity bank reference source is absent from Stage-7 request: {source_key}"
            )
        sample = _find_sample(
            source,
            field="reference_samples",
            timestamp=raw.get("timestamp_seconds"),
            eye=raw.get("eye"),
        )
        expected_frame_sha = _sha(
            raw.get("frame_sha256"),
            label="identity bank frame SHA-256",
        )
        image, _viewport_id, _viewport, _eye_image, _spatial = (
            representation._match_exact_viewport(
                adapter=adapter,
                runtime=runtime,
                source=source,
                sample=sample,
                expected_frame_sha=expected_frame_sha,
            )
        )
        original, original_quality = representation._single_face_measurement(
            adapter=adapter,
            runtime=runtime,
            image=image,
        )
        if original is None:
            raise PhotorealIdentityFlipTtaDiagnosticError(
                f"accepted bank reference no longer replays as one identity: {source_key}"
            )
        stored = _normalize(
            raw.get("embedding"),
            dimension=dimension,
            label=f"identity bank embedding[{index}]",
        )
        flipped, flip_quality = _flip_measurement(
            representation=representation,
            adapter=adapter,
            runtime=runtime,
            image=image,
        )
        aligned_flipped, aligned_flip_quality = _aligned_crop_flip_measurement(
            adapter=adapter,
            runtime=runtime,
            image=image,
            original_embedding=original,
            dimension=dimension,
        )

        group_id = str(raw.get("group_id") or "").strip()
        if not group_id:
            raise PhotorealIdentityFlipTtaDiagnosticError(
                "identity bank reference lacks group id"
            )
        positive_variants["bank-original"].append(
            {"group_id": group_id, "embedding": stored}
        )
        positive_variants["replay-original"].append(
            {"group_id": group_id, "embedding": original}
        )

        row: dict[str, Any] = {
            "reference_index": index,
            "group_id": group_id,
            "source_key_sha256": hashlib.sha256(
                source_key.encode("utf-8")
            ).hexdigest(),
            "frame_sha256": expected_frame_sha,
            "timestamp_seconds": raw.get("timestamp_seconds"),
            "eye": str(raw.get("eye") or ""),
            "replay_to_bank_cosine": round(_cosine(original, stored), 9),
            "original_quality": original_quality,
            "flip_status": flip_quality.get("status"),
            "flip_quality": flip_quality,
        }
        if flipped is not None:
            tta = _tta_mean(original, flipped, dimension=dimension)
            positive_variants["horizontal-flip"].append(
                {"group_id": group_id, "embedding": flipped}
            )
            positive_variants["flip-tta-mean"].append(
                {"group_id": group_id, "embedding": tta}
            )
            row.update(
                {
                    "replay_to_flip_cosine": round(
                        _cosine(original, flipped),
                        9,
                    ),
                    "tta_to_bank_cosine": round(_cosine(tta, stored), 9),
                    "tta_to_replay_cosine": round(_cosine(tta, original), 9),
                }
            )
        aligned_tta = _tta_mean(
            original,
            aligned_flipped,
            dimension=dimension,
        )
        positive_variants["aligned-crop-flip"].append(
            {"group_id": group_id, "embedding": aligned_flipped}
        )
        positive_variants["aligned-crop-flip-tta-mean"].append(
            {"group_id": group_id, "embedding": aligned_tta}
        )
        row.update(
            {
                "aligned_flip_quality": aligned_flip_quality,
                "replay_to_aligned_flip_cosine": round(
                    _cosine(original, aligned_flipped),
                    9,
                ),
                "aligned_tta_to_bank_cosine": round(
                    _cosine(aligned_tta, stored),
                    9,
                ),
                "aligned_tta_to_replay_cosine": round(
                    _cosine(aligned_tta, original),
                    9,
                ),
            }
        )
        reference_diagnostics.append(row)

    negative_diagnostics: list[dict[str, Any]] = []
    for item in negatives:
        source = item["source"]
        sample = _find_sample(
            source,
            field="samples",
            timestamp=item["timestamp_seconds"],
            eye=item["eye"],
        )
        image, spatial = adapter._read_sample(runtime, source, sample)
        if spatial:
            raise PhotorealIdentityFlipTtaDiagnosticError(
                "persisted negative observation unexpectedly requires spatial deprojection"
            )
        observed_frame_sha = adapter._frame_sha(image)
        if observed_frame_sha != item["frame_sha256"]:
            raise PhotorealIdentityFlipTtaDiagnosticError(
                "persisted negative frame SHA no longer reproduces"
            )
        original, original_quality = representation._single_face_measurement(
            adapter=adapter,
            runtime=runtime,
            image=image,
        )
        if original is None:
            raise PhotorealIdentityFlipTtaDiagnosticError(
                "persisted negative no longer replays as one identity"
            )
        flipped, flip_quality = _flip_measurement(
            representation=representation,
            adapter=adapter,
            runtime=runtime,
            image=image,
        )
        aligned_flipped, aligned_flip_quality = _aligned_crop_flip_measurement(
            adapter=adapter,
            runtime=runtime,
            image=image,
            original_embedding=original,
            dimension=dimension,
        )
        stored = item["stored_embedding"]
        negative_variants["bank-original"].append(
            {
                "subject_performer_id": item["subject_performer_id"],
                "embedding": stored,
            }
        )
        negative_variants["replay-original"].append(
            {
                "subject_performer_id": item["subject_performer_id"],
                "embedding": original,
            }
        )
        row = {
            "negative_index": item["index"],
            "subject_performer_id": item["subject_performer_id"],
            "frame_sha256": item["frame_sha256"],
            "replay_to_stored_cosine": round(_cosine(original, stored), 9),
            "original_quality": original_quality,
            "flip_status": flip_quality.get("status"),
            "flip_quality": flip_quality,
        }
        if flipped is not None:
            tta = _tta_mean(original, flipped, dimension=dimension)
            negative_variants["horizontal-flip"].append(
                {
                    "subject_performer_id": item["subject_performer_id"],
                    "embedding": flipped,
                }
            )
            negative_variants["flip-tta-mean"].append(
                {
                    "subject_performer_id": item["subject_performer_id"],
                    "embedding": tta,
                }
            )
            row.update(
                {
                    "replay_to_flip_cosine": round(
                        _cosine(original, flipped),
                        9,
                    ),
                    "tta_to_stored_cosine": round(_cosine(tta, stored), 9),
                    "tta_to_replay_cosine": round(_cosine(tta, original), 9),
                }
            )
        aligned_tta = _tta_mean(
            original,
            aligned_flipped,
            dimension=dimension,
        )
        negative_variants["aligned-crop-flip"].append(
            {
                "subject_performer_id": item["subject_performer_id"],
                "embedding": aligned_flipped,
            }
        )
        negative_variants["aligned-crop-flip-tta-mean"].append(
            {
                "subject_performer_id": item["subject_performer_id"],
                "embedding": aligned_tta,
            }
        )
        row.update(
            {
                "aligned_flip_quality": aligned_flip_quality,
                "replay_to_aligned_flip_cosine": round(
                    _cosine(original, aligned_flipped),
                    9,
                ),
                "aligned_tta_to_stored_cosine": round(
                    _cosine(aligned_tta, stored),
                    9,
                ),
                "aligned_tta_to_replay_cosine": round(
                    _cosine(aligned_tta, original),
                    9,
                ),
            }
        )
        negative_diagnostics.append(row)

    variant_results: dict[str, Any] = {}
    for name in (
        "bank-original",
        "replay-original",
        "horizontal-flip",
        "flip-tta-mean",
        "aligned-crop-flip",
        "aligned-crop-flip-tta-mean",
    ):
        positives = positive_variants.get(name, [])
        variant_negatives = negative_variants.get(name, [])
        if not positives or not variant_negatives:
            variant_results[name] = {
                "positive_measurement_count": len(positives),
                "negative_measurement_count": len(variant_negatives),
                "positive_reference_coverage": round(
                    len(positives) / len(references),
                    9,
                ),
                "negative_observation_coverage": round(
                    len(variant_negatives) / len(negatives),
                    9,
                ),
                "scoring_status": "insufficient-flip-coverage",
                "scoring_models": None,
                "diagnostic_only": True,
            }
            continue
        variant_results[name] = {
            "positive_measurement_count": len(positives),
            "negative_measurement_count": len(variant_negatives),
            "positive_reference_coverage": round(
                len(positives) / len(references),
                9,
            ),
            "negative_observation_coverage": round(
                len(variant_negatives) / len(negatives),
                9,
            ),
            "positive_group_count": len(
                {item["group_id"] for item in positives}
            ),
            "negative_performer_count": len(
                {
                    item["subject_performer_id"]
                    for item in variant_negatives
                }
            ),
            "scoring_status": "available",
            "scoring_models": _score_models(positives, variant_negatives),
            "diagnostic_only": True,
        }

    diagnostic_revision = str(
        os.environ.get("BODYRIG_REVISION") or ""
    ).strip().lower()
    if (
        len(diagnostic_revision) != 40
        or any(
            character not in "0123456789abcdef"
            for character in diagnostic_revision
        )
    ):
        raise PhotorealIdentityFlipTtaDiagnosticError(
            "BODYRIG_REVISION must bind diagnostic execution to exact Git HEAD"
        )

    result = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "diagnostic_bodyrig_revision": diagnostic_revision,
        "adapter_revision": adapter_revision,
        "model_set_sha256": str(bank.get("model_set_sha256") or ""),
        "identity_bank_sha256": bank_sha,
        "identity_bank_file_sha256": _sha256_file(bank_path),
        "identity_request_sha256": _sha256_file(identity_request_origin_path),
        "identity_request_transport_sha256": _sha256_file(identity_request_path),
        "calibration_request_sha256": _sha256_file(
            calibration_request_origin_path
        ),
        "calibration_request_transport_sha256": _sha256_file(
            calibration_request_path
        ),
        "negative_observations_sha256": _sha256_file(
            negative_observations_path
        ),
        "identity_group_attestation_sha256": _sha256_file(
            review_root / "identity-group-attestation.json"
        ),
        "review_bodyrig_revision": attestation.get("review_bodyrig_revision"),
        "attestation_bodyrig_revision": attestation.get(
            "attestation_bodyrig_revision"
        ),
        "positive_reference_count": len(references),
        "human_attested_group_count": len(
            attestation.get("accepted_group_ids") or []
        ),
        "negative_observation_count": len(negatives),
        "negative_performer_count": len(
            {item["subject_performer_id"] for item in negatives}
        ),
        "normalization": {
            "source_embedding_normalization": "l2",
            "frame_flip_tta_formula": (
                "l2-normalize(l2(original)+l2(horizontal-flip-frame))"
            ),
            "aligned_crop_flip_tta_formula": (
                "l2-normalize(l2(original)+l2(horizontal-flip-aligned-face-crop))"
            ),
            "aligned_crop_detection_reused": True,
            "production_adapter_changed": False,
        },
        "variants": variant_results,
        "positive_reference_diagnostics": reference_diagnostics,
        "negative_observation_diagnostics": negative_diagnostics,
        "diagnostic_only": True,
        "identity_group_selection_authority": False,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "format": FORMAT,
                "performer_id": performer_id,
                "positive_reference_count": len(references),
                "negative_observation_count": len(negatives),
                "variants": variant_results,
                "diagnostic_only": True,
                "production_activation": False,
                "output": str(output),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

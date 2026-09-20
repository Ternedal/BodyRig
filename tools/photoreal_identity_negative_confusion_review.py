from __future__ import annotations

import argparse
import html
import importlib.util
import json
import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from bodyrig import photoreal_identity_group_review as review


FORMAT = "bodyrig-photoreal-identity-negative-confusion-review"
VERSION = 1


class PhotorealIdentityNegativeConfusionReviewError(RuntimeError):
    pass


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PhotorealIdentityNegativeConfusionReviewError(
            f"could not load diagnostic dependency: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-")
    return slug[:96] or "group"


def _write_png(runtime: Any, path: Path, image: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = runtime.cv2.imwrite(str(path), image)
    if not ok:
        raise PhotorealIdentityNegativeConfusionReviewError(
            f"could not write review crop: {path}"
        )


def _face_crop_and_embeddings(
    *,
    ab: Any,
    adapter: Any,
    runtime: Any,
    representation: Any,
    alternate_recognizer: Any,
    image: Any,
    dimension: int,
) -> tuple[Any, list[float], list[float], dict[str, Any]]:
    candidates = adapter._candidates(runtime, image)
    faces = [
        item.get("face")
        for item in candidates
        if item.get("face") is not None
    ]
    if len(candidates) != 1 or len(faces) != 1:
        raise PhotorealIdentityNegativeConfusionReviewError(
            "review frame did not reproduce exactly one face candidate"
        )
    face = faces[0]
    landmarks = getattr(face, "kps", None)
    if landmarks is None:
        raise PhotorealIdentityNegativeConfusionReviewError(
            "review face has no five-point landmarks"
        )

    current_models = getattr(runtime.face_app, "models", None)
    current_recognizer = (
        current_models.get("recognition")
        if isinstance(current_models, Mapping)
        else None
    )
    if (
        current_recognizer is None
        or not callable(getattr(current_recognizer, "get_feat", None))
    ):
        raise PhotorealIdentityNegativeConfusionReviewError(
            "current InsightFace recognizer does not expose get_feat"
        )

    try:
        from insightface.utils import face_align

        aligned = face_align.norm_crop(
            image,
            landmark=landmarks,
            image_size=112,
        )
        aligned = runtime.np.ascontiguousarray(aligned)
        current = ab._normalize(
            current_recognizer.get_feat(aligned),
            dimension=dimension,
            label="current aligned review embedding",
        )
        alternate = ab._normalize(
            alternate_recognizer.get_feat(aligned),
            dimension=dimension,
            label="alternate aligned review embedding",
        )
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, PhotorealIdentityNegativeConfusionReviewError):
            raise
        raise PhotorealIdentityNegativeConfusionReviewError(
            f"review recognition inference failed: {exc}"
        ) from exc

    face_embedding = adapter._embedding(face, dimension)
    if face_embedding is None:
        raise PhotorealIdentityNegativeConfusionReviewError(
            "current FaceAnalysis face has no identity embedding"
        )
    current_replay_cosine = ab._cosine(current, face_embedding)
    if current_replay_cosine < 0.999999:
        raise PhotorealIdentityNegativeConfusionReviewError(
            "aligned current recognizer does not reproduce FaceAnalysis embedding"
        )

    return aligned, current, alternate, {
        "current_replay_cosine": round(current_replay_cosine, 9),
        "face_quality": representation._face_quality(
            adapter,
            runtime,
            image,
            face,
        ),
    }


def _nearest(
    *,
    ab: Any,
    vector: list[float],
    positives: list[dict[str, Any]],
    group_centroids: Mapping[str, list[float]],
) -> dict[str, Any]:
    group_scores = [
        (group_id, ab._cosine(vector, centroid))
        for group_id, centroid in group_centroids.items()
    ]
    group_scores.sort(key=lambda item: item[1], reverse=True)
    nearest_group_id, nearest_group_cosine = group_scores[0]

    reference_scores = [
        (
            int(item["reference_index"]),
            str(item["group_id"]),
            ab._cosine(vector, item["embedding"]),
        )
        for item in positives
    ]
    reference_scores.sort(key=lambda item: item[2], reverse=True)
    nearest_reference_index, nearest_reference_group_id, nearest_reference_cosine = (
        reference_scores[0]
    )
    return {
        "nearest_group_id": nearest_group_id,
        "nearest_group_cosine": round(nearest_group_cosine, 9),
        "nearest_reference_index": nearest_reference_index,
        "nearest_reference_group_id": nearest_reference_group_id,
        "nearest_reference_cosine": round(nearest_reference_cosine, 9),
        "top_group_scores": [
            {
                "group_id": group_id,
                "cosine": round(score, 9),
            }
            for group_id, score in group_scores[:5]
        ],
    }


def _build_html(
    *,
    performer_id: str,
    rows: list[dict[str, Any]],
    positive_images: Mapping[int, str],
) -> str:
    body_rows: list[str] = []
    for row in rows:
        current = row["current"]
        alternate = row["alternate"]
        current_ref = int(current["nearest_reference_index"])
        alternate_ref = int(alternate["nearest_reference_index"])
        body_rows.append(
            "<tr>"
            f"<td><strong>{row['negative_index']}</strong><br>"
            f"subject={html.escape(str(row['subject_performer_id']))}<br>"
            f"{html.escape(str(row['timestamp_seconds']))}s / {html.escape(str(row['eye']))}</td>"
            f"<td><img src=\"{html.escape(row['negative_image'])}\" alt=\"negative {row['negative_index']}\"></td>"
            f"<td><strong>{html.escape(current['nearest_group_id'])}</strong><br>"
            f"group cos={current['nearest_group_cosine']:.6f}<br>"
            f"ref cos={current['nearest_reference_cosine']:.6f}<br>"
            f"<img src=\"{html.escape(positive_images[current_ref])}\" alt=\"current nearest positive\"></td>"
            f"<td><strong>{html.escape(alternate['nearest_group_id'])}</strong><br>"
            f"group cos={alternate['nearest_group_cosine']:.6f}<br>"
            f"ref cos={alternate['nearest_reference_cosine']:.6f}<br>"
            f"<img src=\"{html.escape(positive_images[alternate_ref])}\" alt=\"alternate nearest positive\"></td>"
            f"<td>w600k target={row['current_target_cosine']:.6f}<br>"
            f"glintr100 target={row['alternate_target_cosine']:.6f}<br>"
            f"source={html.escape(str(row['source_key']))}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BodyRig identity negative confusion review</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #111; color: #eee; }}
h1, h2 {{ margin-bottom: 8px; }}
.notice {{ padding: 12px; border: 1px solid #666; background: #1c1c1c; margin-bottom: 18px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border: 1px solid #444; padding: 10px; vertical-align: top; }}
th {{ background: #222; position: sticky; top: 0; }}
img {{ width: 160px; height: 160px; object-fit: contain; image-rendering: auto; background: #000; }}
code {{ color: #ddd; }}
.small {{ color: #aaa; }}
</style>
</head>
<body>
<h1>BodyRig negative identity confusion review</h1>
<div class="notice">
<strong>Target performer:</strong> {html.escape(performer_id)}<br>
<strong>Purpose:</strong> visually verify that every persisted calibration negative is truly a non-target face.<br>
<strong>Comparison:</strong> current <code>w600k_r50</code> versus diagnostic <code>antelopev2/glintr100</code>.<br>
<strong>Authority:</strong> diagnostic only. This page grants no matching, training, photoreal or production authority.
</div>
<p class="small">Rows are sorted by the strongest antelopev2 nearest-group confusion first. The center crop is the exact aligned 112x112 face crop used by both recognizers.</p>
<table>
<thead>
<tr>
<th>Negative evidence</th>
<th>Aligned negative crop</th>
<th>Current w600k_r50 nearest positive</th>
<th>Antelopev2 glintr100 nearest positive</th>
<th>Target-centroid / source</th>
</tr>
</thead>
<tbody>
{''.join(body_rows)}
</tbody>
</table>
</body>
</html>
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a diagnostic-only human review of persisted negative identity "
            "observations and their strongest positive-group confusions under the "
            "current and alternate recognizers."
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
    parser.add_argument("--diagnostic-recognizer-root", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_root = args.out.expanduser().resolve()
    if output_root.exists():
        raise PhotorealIdentityNegativeConfusionReviewError(
            f"negative confusion review output already exists: {output_root}"
        )

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    ab = _load_module(
        repo_root / "tools" / "photoreal_identity_recognizer_ab_diagnostic.py",
        "bodyrig_negative_confusion_ab_dependency",
    )
    flip = _load_module(
        repo_root / "tools" / "photoreal_identity_flip_tta_diagnostic.py",
        "bodyrig_negative_confusion_flip_dependency",
    )
    representation = flip._load_representation_tool(repo_root)
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
    diagnostic_recognizer_root = (
        args.diagnostic_recognizer_root.expanduser().resolve()
    )

    bank = ab._read_json(bank_path, label="identity bank")
    performer_id, bank_sha = review._validate_bank(
        bank,
        adapter_revision=adapter_revision,
    )
    dimension = bank.get("embedding_dimension")
    if dimension != 512:
        raise PhotorealIdentityNegativeConfusionReviewError(
            "negative confusion review requires the pinned 512-dimensional identity bank"
        )

    identity_request = ab._read_json(
        identity_request_path,
        label="Stage-7 identity execution request",
    )
    identity_request_origin = ab._read_json(
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

    calibration_request = ab._read_json(
        calibration_request_path,
        label="Stage-13 calibration execution request",
    )
    calibration_request_origin = ab._read_json(
        calibration_request_origin_path,
        label="Stage-13 calibration original request",
    )
    representation._request_transport_equivalent(
        calibration_request_origin,
        calibration_request,
    )
    calibration_sources = flip._validate_calibration_request(
        calibration_request,
        performer_id=performer_id,
        bank=bank,
        adapter_revision=adapter_revision,
    )
    negative_document = ab._read_json(
        negative_observations_path,
        label="identity negative observations",
    )
    negatives = flip._validate_negative_observations(
        negative_document,
        performer_id=performer_id,
        bank=bank,
        adapter_revision=adapter_revision,
        sources=calibration_sources,
        dimension=dimension,
    )

    model_set = adapter.build_model_set(model_root)
    if flip._sha(
        model_set.get("model_set_sha256"),
        label="runtime model-set SHA-256",
    ) != flip._sha(
        bank.get("model_set_sha256"),
        label="identity bank model-set SHA-256",
    ):
        raise PhotorealIdentityNegativeConfusionReviewError(
            "current model root does not match identity bank model set"
        )
    manifest = adapter._load_model_manifest(model_root)
    runtime = adapter._load_runtime(manifest, device=args.device)
    alternate_path, alternate_provenance = ab._validate_alternate_provenance(
        root=diagnostic_recognizer_root,
    )
    alternate_recognizer = ab._load_alternate_recognizer(
        alternate_path,
        device=args.device,
    )

    references = bank.get("references")
    if not isinstance(references, list) or not references:
        raise PhotorealIdentityNegativeConfusionReviewError(
            "identity bank contains no references"
        )

    output_root.mkdir(parents=True, exist_ok=False)
    positive_dir = output_root / "positive"
    negative_dir = output_root / "negative"

    current_positives: list[dict[str, Any]] = []
    alternate_positives: list[dict[str, Any]] = []
    positive_images: dict[int, str] = {}

    for index, raw in enumerate(references):
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityNegativeConfusionReviewError(
                "identity bank reference is invalid"
            )
        source_key = str(raw.get("source_key") or "").strip()
        source = identity_sources.get(source_key)
        if source is None:
            raise PhotorealIdentityNegativeConfusionReviewError(
                f"identity bank reference source missing: {source_key}"
            )
        sample = flip._find_sample(
            source,
            field="reference_samples",
            timestamp=raw.get("timestamp_seconds"),
            eye=raw.get("eye"),
        )
        expected_frame_sha = flip._sha(
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
        crop, current, alternate, _quality = _face_crop_and_embeddings(
            ab=ab,
            adapter=adapter,
            runtime=runtime,
            representation=representation,
            alternate_recognizer=alternate_recognizer,
            image=image,
            dimension=dimension,
        )
        stored = ab._normalize(
            raw.get("embedding"),
            dimension=dimension,
            label=f"identity bank embedding[{index}]",
        )
        if ab._cosine(current, stored) < 0.999999:
            raise PhotorealIdentityNegativeConfusionReviewError(
                "current recognizer review replay does not match persisted bank embedding"
            )
        group_id = str(raw.get("group_id") or "").strip()
        if not group_id:
            raise PhotorealIdentityNegativeConfusionReviewError(
                "identity bank reference lacks group id"
            )

        filename = f"positive-{index:02d}-{_safe_slug(group_id)}.png"
        _write_png(runtime, positive_dir / filename, crop)
        positive_images[index] = f"positive/{filename}"
        current_positives.append(
            {
                "reference_index": index,
                "group_id": group_id,
                "embedding": current,
            }
        )
        alternate_positives.append(
            {
                "reference_index": index,
                "group_id": group_id,
                "embedding": alternate,
            }
        )

    accepted_groups = sorted(attestation.get("accepted_group_ids") or [])
    observed_groups = sorted(
        {str(item["group_id"]) for item in current_positives}
    )
    if observed_groups != accepted_groups:
        raise PhotorealIdentityNegativeConfusionReviewError(
            "positive review groups do not match human attestation"
        )

    def build_group_centroids(
        positives: list[dict[str, Any]],
    ) -> dict[str, list[float]]:
        grouped: dict[str, list[list[float]]] = defaultdict(list)
        for item in positives:
            grouped[str(item["group_id"])].append(item["embedding"])
        return {
            group_id: flip._centroid(vectors)
            for group_id, vectors in grouped.items()
        }

    current_group_centroids = build_group_centroids(current_positives)
    alternate_group_centroids = build_group_centroids(alternate_positives)
    current_target = flip._centroid(
        [
            current_group_centroids[group_id]
            for group_id in sorted(current_group_centroids)
        ]
    )
    alternate_target = flip._centroid(
        [
            alternate_group_centroids[group_id]
            for group_id in sorted(alternate_group_centroids)
        ]
    )

    rows: list[dict[str, Any]] = []
    for item in negatives:
        source = item["source"]
        sample = flip._find_sample(
            source,
            field="samples",
            timestamp=item["timestamp_seconds"],
            eye=item["eye"],
        )
        image, spatial = adapter._read_sample(runtime, source, sample)
        if spatial:
            raise PhotorealIdentityNegativeConfusionReviewError(
                "persisted negative unexpectedly requires spatial deprojection"
            )
        if adapter._frame_sha(image) != item["frame_sha256"]:
            raise PhotorealIdentityNegativeConfusionReviewError(
                "persisted negative frame SHA no longer reproduces"
            )

        crop, current, alternate, quality = _face_crop_and_embeddings(
            ab=ab,
            adapter=adapter,
            runtime=runtime,
            representation=representation,
            alternate_recognizer=alternate_recognizer,
            image=image,
            dimension=dimension,
        )
        stored = item["stored_embedding"]
        if ab._cosine(current, stored) < 0.999999:
            raise PhotorealIdentityNegativeConfusionReviewError(
                "current recognizer review replay does not match persisted negative embedding"
            )

        index = int(item["index"])
        filename = f"negative-{index:02d}.png"
        _write_png(runtime, negative_dir / filename, crop)

        current_match = _nearest(
            ab=ab,
            vector=current,
            positives=current_positives,
            group_centroids=current_group_centroids,
        )
        alternate_match = _nearest(
            ab=ab,
            vector=alternate,
            positives=alternate_positives,
            group_centroids=alternate_group_centroids,
        )
        rows.append(
            {
                "negative_index": index,
                "subject_performer_id": item["subject_performer_id"],
                "source_key": item["source_key"],
                "timestamp_seconds": item["timestamp_seconds"],
                "eye": item["eye"],
                "frame_sha256": item["frame_sha256"],
                "negative_image": f"negative/{filename}",
                "current_target_cosine": round(
                    ab._cosine(current, current_target),
                    9,
                ),
                "alternate_target_cosine": round(
                    ab._cosine(alternate, alternate_target),
                    9,
                ),
                "current": current_match,
                "alternate": alternate_match,
                "quality": quality,
            }
        )

    rows.sort(
        key=lambda row: (
            float(row["alternate"]["nearest_group_cosine"]),
            float(row["alternate_target_cosine"]),
        ),
        reverse=True,
    )

    bodyrig_revision = str(os.environ.get("BODYRIG_REVISION") or "").strip().lower()
    if (
        len(bodyrig_revision) != 40
        or any(character not in "0123456789abcdef" for character in bodyrig_revision)
    ):
        raise PhotorealIdentityNegativeConfusionReviewError(
            "BODYRIG_REVISION must bind review generation to exact Git HEAD"
        )

    result = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "diagnostic_bodyrig_revision": bodyrig_revision,
        "adapter_revision": adapter_revision,
        "identity_bank_sha256": bank_sha,
        "identity_bank_file_sha256": ab._sha256_file(bank_path),
        "identity_request_sha256": ab._sha256_file(identity_request_origin_path),
        "identity_request_transport_sha256": ab._sha256_file(identity_request_path),
        "calibration_request_sha256": ab._sha256_file(calibration_request_origin_path),
        "calibration_request_transport_sha256": ab._sha256_file(calibration_request_path),
        "negative_observations_sha256": ab._sha256_file(
            negative_observations_path
        ),
        "identity_group_attestation_sha256": ab._sha256_file(
            review_root / "identity-group-attestation.json"
        ),
        "alternate_recognizer": {
            "package": ab.ALTERNATE_PACKAGE,
            "recognizer_file": ab.ALTERNATE_RECOGNIZER_FILE,
            "recognizer_sha256": ab.ALTERNATE_RECOGNIZER_SHA256,
            "architecture": alternate_provenance.get(
                "recognition_architecture"
            ),
            "training_set": alternate_provenance.get(
                "recognition_training_set"
            ),
        },
        "positive_reference_count": len(references),
        "human_attested_group_count": len(accepted_groups),
        "negative_observation_count": len(negatives),
        "negative_reviews": rows,
        "review_required": True,
        "diagnostic_only": True,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }

    json_path = output_root / "negative-confusion-review.json"
    json_path.write_text(
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
    html_path = output_root / "review-index.html"
    html_path.write_text(
        _build_html(
            performer_id=performer_id,
            rows=rows,
            positive_images=positive_images,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "format": FORMAT,
                "performer_id": performer_id,
                "positive_reference_count": len(references),
                "negative_observation_count": len(negatives),
                "highest_confusions": [
                    {
                        "negative_index": row["negative_index"],
                        "subject_performer_id": row[
                            "subject_performer_id"
                        ],
                        "current_target_cosine": row[
                            "current_target_cosine"
                        ],
                        "alternate_target_cosine": row[
                            "alternate_target_cosine"
                        ],
                        "current_nearest_group_id": row["current"][
                            "nearest_group_id"
                        ],
                        "current_nearest_group_cosine": row["current"][
                            "nearest_group_cosine"
                        ],
                        "alternate_nearest_group_id": row["alternate"][
                            "nearest_group_id"
                        ],
                        "alternate_nearest_group_cosine": row["alternate"][
                            "nearest_group_cosine"
                        ],
                    }
                    for row in rows
                ],
                "review_root": str(output_root),
                "review_html": str(html_path),
                "diagnostic_only": True,
                "production_activation": False,
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

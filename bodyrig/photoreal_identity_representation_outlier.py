from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping


FORMAT = "bodyrig-photoreal-identity-representation-outlier-analysis"
VERSION = 1
DIAGNOSTIC_FORMAT = "bodyrig-photoreal-identity-representation-diagnostic"
BANK_FORMAT = "bodyrig-photoreal-identity-bank"


class PhotorealIdentityRepresentationOutlierError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealIdentityRepresentationOutlierError(
            f"{label} is unreadable: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityRepresentationOutlierError(
            f"{label} must be a JSON object"
        )
    return value


def _vector(value: Any, *, dimension: int, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != dimension:
        raise PhotorealIdentityRepresentationOutlierError(
            f"{label} dimension mismatch"
        )
    result = [float(item) for item in value]
    if any(not math.isfinite(item) for item in result):
        raise PhotorealIdentityRepresentationOutlierError(
            f"{label} contains non-finite value"
        )
    norm = math.sqrt(sum(item * item for item in result))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise PhotorealIdentityRepresentationOutlierError(
            f"{label} has invalid norm"
        )
    return [item / norm for item in result]


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        raise PhotorealIdentityRepresentationOutlierError(
            "cannot build centroid from zero vectors"
        )
    dimension = len(vectors[0])
    if any(len(vector) != dimension for vector in vectors):
        raise PhotorealIdentityRepresentationOutlierError(
            "embedding dimensions are inconsistent"
        )
    mean = [
        sum(vector[index] for vector in vectors) / len(vectors)
        for index in range(dimension)
    ]
    norm = math.sqrt(sum(item * item for item in mean))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise PhotorealIdentityRepresentationOutlierError(
            "embedding centroid collapsed"
        )
    return [item / norm for item in mean]


def _cosine(left: list[float], right: list[float]) -> float:
    return max(
        -1.0,
        min(1.0, sum(a * b for a, b in zip(left, right, strict=True))),
    )


def _median(values: list[float]) -> float | None:
    return None if not values else round(float(statistics.median(values)), 9)


def _rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    result = [0.0] * len(values)
    index = 0
    while index < len(indexed):
        end = index + 1
        while end < len(indexed) and indexed[end][1] == indexed[index][1]:
            end += 1
        average_rank = (index + 1 + end) * 0.5
        for cursor in range(index, end):
            result[indexed[cursor][0]] = average_rank
        index = end
    return result


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    left_norm = math.sqrt(sum(value * value for value in left_delta))
    right_norm = math.sqrt(sum(value * value for value in right_delta))
    if left_norm <= 1e-12 or right_norm <= 1e-12:
        return None
    value = sum(a * b for a, b in zip(left_delta, right_delta, strict=True))
    return round(max(-1.0, min(1.0, value / (left_norm * right_norm))), 9)


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    return _pearson(_rank(left), _rank(right))


def _numeric_path(row: Mapping[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = row
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _correlation(
    rows: list[dict[str, Any]],
    *,
    x_path: tuple[str, ...],
    y_key: str,
) -> dict[str, Any]:
    x_values: list[float] = []
    y_values: list[float] = []
    for row in rows:
        x = _numeric_path(row, x_path)
        y_raw = row.get(y_key)
        if x is None or y_raw is None:
            continue
        y = float(y_raw)
        if not math.isfinite(y):
            continue
        x_values.append(x)
        y_values.append(y)
    return {
        "count": len(x_values),
        "pearson": _pearson(x_values, y_values),
        "spearman": _spearman(x_values, y_values),
    }


def _pose_abs(row: Mapping[str, Any], key: str) -> float | None:
    pose = row.get("current_quality", {}).get("pose") if isinstance(
        row.get("current_quality"), Mapping
    ) else None
    if not isinstance(pose, Mapping):
        return None
    value = pose.get(key)
    if value is None or isinstance(value, bool):
        return None
    number = float(value)
    return abs(number) if math.isfinite(number) else None


def _validate(
    bank: Mapping[str, Any],
    diagnostic: Mapping[str, Any],
) -> tuple[int, list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    if bank.get("format") != BANK_FORMAT or bank.get("version") != 1:
        raise PhotorealIdentityRepresentationOutlierError(
            "identity bank format/version mismatch"
        )
    if (
        diagnostic.get("format") != DIAGNOSTIC_FORMAT
        or diagnostic.get("version") != 1
        or diagnostic.get("diagnostic_only") is not True
        or diagnostic.get("production_activation") is not False
    ):
        raise PhotorealIdentityRepresentationOutlierError(
            "identity representation diagnostic authority/format mismatch"
        )
    if diagnostic.get("identity_matching_authorized") is not False:
        raise PhotorealIdentityRepresentationOutlierError(
            "identity representation diagnostic crossed matching authority"
        )
    if diagnostic.get("teacher_training_authorized") is not False:
        raise PhotorealIdentityRepresentationOutlierError(
            "identity representation diagnostic crossed training authority"
        )
    if diagnostic.get("photoreal_acceptance_authority") is not False:
        raise PhotorealIdentityRepresentationOutlierError(
            "identity representation diagnostic crossed photoreal authority"
        )
    if diagnostic.get("identity_bank_sha256") != bank.get("identity_bank_sha256"):
        raise PhotorealIdentityRepresentationOutlierError(
            "representation diagnostic targets a different identity bank"
        )
    if diagnostic.get("performer_id") != bank.get("performer_id"):
        raise PhotorealIdentityRepresentationOutlierError(
            "representation diagnostic performer mismatch"
        )
    dimension_raw = bank.get("embedding_dimension")
    if isinstance(dimension_raw, bool) or not isinstance(dimension_raw, int):
        raise PhotorealIdentityRepresentationOutlierError(
            "identity bank embedding dimension is invalid"
        )
    references = bank.get("references")
    diagnostic_rows = diagnostic.get("references")
    if not isinstance(references, list) or not isinstance(diagnostic_rows, list):
        raise PhotorealIdentityRepresentationOutlierError(
            "identity bank/diagnostic references are invalid"
        )
    if len(references) != len(diagnostic_rows):
        raise PhotorealIdentityRepresentationOutlierError(
            "identity bank/diagnostic reference count mismatch"
        )
    return dimension_raw, references, diagnostic_rows


def analyze(
    bank: Mapping[str, Any],
    diagnostic: Mapping[str, Any],
    *,
    worst_count: int = 12,
) -> dict[str, Any]:
    dimension, references, diagnostic_rows = _validate(bank, diagnostic)

    joined: list[dict[str, Any]] = []
    embeddings: list[list[float]] = []
    for index, (raw, measured) in enumerate(
        zip(references, diagnostic_rows, strict=True)
    ):
        if not isinstance(raw, Mapping) or not isinstance(measured, Mapping):
            raise PhotorealIdentityRepresentationOutlierError(
                "identity reference row is invalid"
            )
        group_id = str(raw.get("group_id") or "").strip()
        if (
            measured.get("reference_index") != index
            or measured.get("group_id") != group_id
            or measured.get("frame_sha256") != raw.get("frame_sha256")
            or measured.get("eye") != raw.get("eye")
        ):
            raise PhotorealIdentityRepresentationOutlierError(
                f"identity bank/diagnostic reference binding mismatch at index {index}"
            )
        embedding = _vector(
            raw.get("embedding"),
            dimension=dimension,
            label=f"identity reference[{index}] embedding",
        )
        embeddings.append(embedding)
        joined.append(
            {
                **dict(measured),
                "_embedding": embedding,
                "group_id": group_id,
            }
        )

    for row in joined:
        others = [
            item["_embedding"]
            for item in joined
            if item["group_id"] != row["group_id"]
        ]
        if not others:
            raise PhotorealIdentityRepresentationOutlierError(
                "leave-group-out analysis has no independent group"
            )
        row["baseline_leave_group_out_cosine"] = round(
            _cosine(row["_embedding"], _centroid(others)),
            9,
        )
        row["abs_yaw_degrees"] = _pose_abs(row, "yaw_degrees")
        row["abs_pitch_degrees"] = _pose_abs(row, "pitch_degrees")
        row["abs_roll_degrees"] = _pose_abs(row, "roll_degrees")

    quality_fields = {
        "face_min_dimension_pixels": (
            "current_quality",
            "bbox_min_dimension_pixels",
        ),
        "face_detection_score": ("current_quality", "det_score"),
        "face_crop_sharpness": ("current_quality", "face_crop_sharpness"),
        "frame_sharpness": ("current_quality", "frame_sharpness"),
        "face_center_offset_fraction": (
            "current_quality",
            "face_center_offset_fraction",
        ),
        "abs_yaw_degrees": ("abs_yaw_degrees",),
        "abs_pitch_degrees": ("abs_pitch_degrees",),
        "abs_roll_degrees": ("abs_roll_degrees",),
    }
    correlations: dict[str, Any] = {}
    for name, path in quality_fields.items():
        correlations[name] = {
            "vs_leave_group_out": _correlation(
                joined,
                x_path=path,
                y_key="baseline_leave_group_out_cosine",
            ),
            "vs_profile_cosine": _correlation(
                joined,
                x_path=path,
                y_key="current_profile_cosine",
            ),
        }

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in joined:
        groups[row["group_id"]].append(row)
    group_summary = []
    for group_id, rows in sorted(groups.items()):
        lgo = [float(row["baseline_leave_group_out_cosine"]) for row in rows]
        profile = [
            float(row["current_profile_cosine"])
            for row in rows
            if row.get("current_profile_cosine") is not None
        ]
        face_size = [
            value
            for row in rows
            if (
                value := _numeric_path(
                    row,
                    ("current_quality", "bbox_min_dimension_pixels"),
                )
            )
            is not None
        ]
        group_summary.append(
            {
                "group_id": group_id,
                "reference_count": len(rows),
                "leave_group_out_min": round(min(lgo), 9),
                "leave_group_out_median": _median(lgo),
                "profile_cosine_median": _median(profile),
                "face_min_dimension_pixels_median": _median(face_size),
            }
        )
    group_summary.sort(
        key=lambda row: (
            float(row["leave_group_out_min"]),
            str(row["group_id"]),
        )
    )

    failure_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    centered_delta: dict[str, list[float]] = defaultdict(list)
    for row in joined:
        centered = row.get("centered_variants")
        if not isinstance(centered, Mapping):
            continue
        for variant, raw_variant in centered.items():
            if not isinstance(raw_variant, Mapping):
                continue
            status = str(raw_variant.get("status") or "missing")
            failure_counts[str(variant)][status] += 1
            to_bank = raw_variant.get("to_bank_reference_cosine")
            if to_bank is not None:
                centered_delta[str(variant)].append(float(to_bank))

    stereo_pairs = diagnostic.get("stereo_pairs")
    if not isinstance(stereo_pairs, list):
        stereo_pairs = []
    stereo_summary: dict[str, dict[str, float | int | None]] = {}
    variant_values: dict[str, list[float]] = defaultdict(list)
    for pair in stereo_pairs:
        if not isinstance(pair, Mapping):
            continue
        values = pair.get("variant_cosines")
        if not isinstance(values, Mapping):
            continue
        for variant, value in values.items():
            if value is not None:
                variant_values[str(variant)].append(float(value))
    for variant, values in sorted(variant_values.items()):
        stereo_summary[variant] = {
            "count": len(values),
            "min": round(min(values), 9),
            "median": _median(values),
            "max": round(max(values), 9),
        }

    public_rows = []
    for row in sorted(
        joined,
        key=lambda item: (
            float(item["baseline_leave_group_out_cosine"]),
            int(item["reference_index"]),
        ),
    )[:worst_count]:
        quality = row.get("current_quality")
        centered = row.get("centered_variants")
        public_rows.append(
            {
                "reference_index": row["reference_index"],
                "group_id": row["group_id"],
                "timestamp_seconds": row.get("timestamp_seconds"),
                "eye": row.get("eye"),
                "baseline_leave_group_out_cosine": row[
                    "baseline_leave_group_out_cosine"
                ],
                "profile_cosine": row.get("current_profile_cosine"),
                "quality": quality,
                "abs_yaw_degrees": row.get("abs_yaw_degrees"),
                "abs_pitch_degrees": row.get("abs_pitch_degrees"),
                "centered_variants": centered,
            }
        )

    lgo_values = [
        float(row["baseline_leave_group_out_cosine"])
        for row in joined
    ]
    result = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": bank.get("performer_id"),
        "identity_bank_sha256": bank.get("identity_bank_sha256"),
        "diagnostic_bodyrig_revision": diagnostic.get(
            "diagnostic_bodyrig_revision"
        ),
        "reference_count": len(joined),
        "group_count": len(groups),
        "baseline_leave_group_out": {
            "min": round(min(lgo_values), 9),
            "median": _median(lgo_values),
            "max": round(max(lgo_values), 9),
        },
        "quality_correlations": correlations,
        "groups_weakest_first": group_summary,
        "worst_references": public_rows,
        "centered_status_counts": {
            variant: dict(sorted(counts.items()))
            for variant, counts in sorted(failure_counts.items())
        },
        "centered_to_bank_cosine": {
            variant: {
                "count": len(values),
                "min": round(min(values), 9),
                "median": _median(values),
                "max": round(max(values), 9),
            }
            for variant, values in sorted(centered_delta.items())
            if values
        },
        "stereo_pair_cosine": stereo_summary,
        "diagnostic_only": True,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze outliers in an existing BodyRig Photoreal identity "
            "representation diagnostic without rerunning GPU inference."
        )
    )
    parser.add_argument("--identity-bank", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worst-count", type=int, default=12)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.worst_count <= 100:
        raise PhotorealIdentityRepresentationOutlierError(
            "--worst-count must be in 1..100"
        )
    output = args.out.expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityRepresentationOutlierError(
            f"output already exists: {output}"
        )
    bank = _read_json(
        args.identity_bank.expanduser().resolve(),
        label="identity bank",
    )
    diagnostic = _read_json(
        args.diagnostic.expanduser().resolve(),
        label="identity representation diagnostic",
    )
    result = analyze(
        bank,
        diagnostic,
        worst_count=args.worst_count,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

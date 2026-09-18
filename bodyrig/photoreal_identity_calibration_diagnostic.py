from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Mapping

from .photoreal_identity_calibration import (
    MIN_COSINE_SEPARATION_MARGIN,
    PhotorealIdentityCalibrationError,
    _centroid,
    _cosine,
    _embedding,
    build_identity_calibration,
)

FORMAT = "bodyrig-photoreal-identity-calibration-diagnostic"
VERSION = 1


class PhotorealIdentityCalibrationDiagnosticError(
    PhotorealIdentityCalibrationError
):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealIdentityCalibrationDiagnosticError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityCalibrationDiagnosticError(
            f"{label} must be a JSON object"
        )
    return value


def _planned_sample_count(source: Mapping[str, Any]) -> int:
    value = source.get("sample_count")
    samples = source.get("samples")

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise PhotorealIdentityCalibrationDiagnosticError(
            "calibration plan source sample_count is invalid"
        )
    if not isinstance(samples, list) or len(samples) != value:
        raise PhotorealIdentityCalibrationDiagnosticError(
            "calibration plan source samples/sample_count mismatch"
        )
    return value


def build_identity_calibration_diagnostic(
    bank: Mapping[str, Any],
    plan: Mapping[str, Any],
    negative_observations: Mapping[str, Any],
    *,
    top_matches: int = 10,
) -> dict[str, Any]:
    if (
        isinstance(top_matches, bool)
        or not isinstance(top_matches, int)
        or not 1 <= top_matches <= 100
    ):
        raise PhotorealIdentityCalibrationDiagnosticError(
            "top_matches must be an integer in 1..100"
        )

    try:
        core = build_identity_calibration(
            bank,
            plan,
            negative_observations,
        )
    except PhotorealIdentityCalibrationError as exc:
        raise PhotorealIdentityCalibrationDiagnosticError(
            f"Stage-13 calibration input is invalid: {exc}"
        ) from exc

    dimension = int(bank["embedding_dimension"])
    references = list(bank["references"])

    target_centroid = _embedding(
        bank["centroid_embedding"],
        dimension=dimension,
        label="diagnostic target centroid",
    )

    positive_rows_raw: list[tuple[float, dict[str, Any]]] = []
    for reference in references:
        independent = [
            _embedding(
                other["embedding"],
                dimension=dimension,
                label="diagnostic independent positive embedding",
            )
            for other in references
            if other["group_id"] != reference["group_id"]
        ]
        score = _cosine(
            _embedding(
                reference["embedding"],
                dimension=dimension,
                label="diagnostic positive embedding",
            ),
            _centroid(independent),
        )
        positive_rows_raw.append(
            (
                score,
                {
                    "cosine": round(score, 9),
                    "group_id": reference["group_id"],
                    "source_key": reference["source_key"],
                    "timestamp_seconds": reference.get("timestamp_seconds"),
                    "eye": reference["eye"],
                    "frame_sha256": reference["frame_sha256"],
                },
            )
        )

    positive_rows_raw.sort(key=lambda item: item[0])
    positive_floor = positive_rows_raw[0][0]

    reference_vectors = [
        (
            reference,
            _embedding(
                reference["embedding"],
                dimension=dimension,
                label="diagnostic positive reference embedding",
            ),
        )
        for reference in references
    ]

    reference_to_target_scores = [
        _cosine(vector, target_centroid)
        for _, vector in reference_vectors
    ]

    positive_group_summaries: list[dict[str, Any]] = []
    group_centroids: dict[str, list[float]] = {}
    group_ids = sorted(
        {
            str(reference["group_id"])
            for reference in references
        }
    )
    for group_id in group_ids:
        group_rows = [
            (reference, vector)
            for reference, vector in reference_vectors
            if str(reference["group_id"]) == group_id
        ]
        group_vectors = [
            vector
            for _, vector in group_rows
        ]
        group_centroid = _centroid(group_vectors)
        group_centroids[group_id] = group_centroid

        pairwise_scores = [
            _cosine(group_vectors[left], group_vectors[right])
            for left in range(len(group_vectors))
            for right in range(left + 1, len(group_vectors))
        ]
        leave_group_out_scores = [
            score
            for score, row in positive_rows_raw
            if str(row["group_id"]) == group_id
        ]

        positive_group_summaries.append(
            {
                "group_id": group_id,
                "reference_count": len(group_rows),
                "source_count": len(
                    {
                        str(reference["source_key"])
                        for reference, _ in group_rows
                    }
                ),
                "centroid_to_target_cosine": round(
                    _cosine(group_centroid, target_centroid),
                    9,
                ),
                "leave_group_out_cosine_min": round(
                    min(leave_group_out_scores),
                    9,
                ),
                "leave_group_out_cosine_median": round(
                    statistics.median(leave_group_out_scores),
                    9,
                ),
                "leave_group_out_cosine_max": round(
                    max(leave_group_out_scores),
                    9,
                ),
                "within_group_pairwise_cosine_min":
                    None
                    if not pairwise_scores
                    else round(min(pairwise_scores), 9),
                "within_group_pairwise_cosine_median":
                    None
                    if not pairwise_scores
                    else round(
                        statistics.median(pairwise_scores),
                        9,
                    ),
                "within_group_pairwise_cosine_max":
                    None
                    if not pairwise_scores
                    else round(max(pairwise_scores), 9),
            }
        )

    positive_cross_group_pairs: list[dict[str, Any]] = []
    for left_index, left_group in enumerate(group_ids):
        for right_group in group_ids[left_index + 1:]:
            positive_cross_group_pairs.append(
                {
                    "left_group_id": left_group,
                    "right_group_id": right_group,
                    "centroid_cosine": round(
                        _cosine(
                            group_centroids[left_group],
                            group_centroids[right_group],
                        ),
                        9,
                    ),
                }
            )

    cross_group_scores = [
        float(item["centroid_cosine"])
        for item in positive_cross_group_pairs
    ]

    planned_sources = {
        source["source_key"]: source
        for source in plan["sources"]
    }

    negative_rows_raw: list[tuple[float, dict[str, Any]]] = []
    for observation in negative_observations["observations"]:
        source = planned_sources[observation["source_key"]]
        negative_vector = _embedding(
            observation["embedding"],
            dimension=dimension,
            label="diagnostic negative embedding",
        )
        score = _cosine(
            negative_vector,
            target_centroid,
        )

        positive_group_matches = [
            {
                "group_id": group_id,
                "cosine": round(
                    _cosine(
                        negative_vector,
                        group_centroids[group_id],
                    ),
                    9,
                ),
            }
            for group_id in group_ids
        ]
        positive_group_matches.sort(
            key=lambda item: float(item["cosine"]),
            reverse=True,
        )

        positive_reference_matches = [
            {
                "group_id": reference["group_id"],
                "source_key": reference["source_key"],
                "timestamp_seconds":
                    reference.get("timestamp_seconds"),
                "eye": reference["eye"],
                "frame_sha256": reference["frame_sha256"],
                "cosine": round(
                    _cosine(negative_vector, vector),
                    9,
                ),
            }
            for reference, vector in reference_vectors
        ]
        positive_reference_matches.sort(
            key=lambda item: float(item["cosine"]),
            reverse=True,
        )

        row = {
            "cosine": round(score, 9),
            "subject_performer_id":
                observation["subject_performer_id"],
            "subject_performer_name":
                source.get("subject_performer_name", ""),
            "source_key": observation["source_key"],
            "resolved_path":
                str(source.get("resolved_path") or ""),
            "timestamp_seconds":
                observation.get("timestamp_seconds"),
            "eye": observation["eye"],
            "frame_sha256": observation["frame_sha256"],
            "positive_group_matches": positive_group_matches,
            "closest_positive_group":
                positive_group_matches[0],
            "positive_reference_matches":
                positive_reference_matches,
            "closest_positive_reference":
                positive_reference_matches[0],
        }

        if len(positive_group_matches) >= 2:
            row["closest_positive_group_margin"] = round(
                float(positive_group_matches[0]["cosine"])
                - float(positive_group_matches[1]["cosine"]),
                9,
            )
        else:
            row["closest_positive_group_margin"] = None

        negative_rows_raw.append((score, row))

    negative_rows_raw.sort(
        key=lambda item: item[0],
        reverse=True,
    )
    negative_ceiling = negative_rows_raw[0][0]
    observed_margin = positive_floor - negative_ceiling
    stage13_margin = float(core["observed_separation_margin"])

    if round(observed_margin, 9) != round(stage13_margin, 9):
        raise PhotorealIdentityCalibrationDiagnosticError(
            "diagnostic separation does not reproduce Stage-13 calibration"
        )

    maximum_allowed_negative = (
        positive_floor - MIN_COSINE_SEPARATION_MARGIN
    )

    performer_summaries: list[dict[str, Any]] = []
    performer_ids = sorted(
        {
            str(item[1]["subject_performer_id"])
            for item in negative_rows_raw
        }
    )
    for performer_id in performer_ids:
        rows = [
            item
            for item in negative_rows_raw
            if str(item[1]["subject_performer_id"]) == performer_id
        ]
        scores = [item[0] for item in rows]
        performer_summaries.append(
            {
                "subject_performer_id": performer_id,
                "subject_performer_name":
                    rows[0][1]["subject_performer_name"],
                "observation_count": len(rows),
                "source_count":
                    len({item[1]["source_key"] for item in rows}),
                "cosine_min": round(min(scores), 9),
                "cosine_median":
                    round(statistics.median(scores), 9),
                "cosine_max": round(max(scores), 9),
                "violating_observation_count": sum(
                    score > maximum_allowed_negative
                    for score in scores
                ),
            }
        )

    performer_summaries.sort(
        key=lambda item: float(item["cosine_max"]),
        reverse=True,
    )

    source_summaries: list[dict[str, Any]] = []
    source_keys = sorted(
        {
            str(item[1]["source_key"])
            for item in negative_rows_raw
        }
    )
    for source_key in source_keys:
        rows = [
            item
            for item in negative_rows_raw
            if str(item[1]["source_key"]) == source_key
        ]
        scores = [item[0] for item in rows]
        source_summaries.append(
            {
                "source_key": source_key,
                "subject_performer_id":
                    rows[0][1]["subject_performer_id"],
                "subject_performer_name":
                    rows[0][1]["subject_performer_name"],
                "resolved_path":
                    rows[0][1]["resolved_path"],
                "observation_count": len(rows),
                "cosine_min": round(min(scores), 9),
                "cosine_median":
                    round(statistics.median(scores), 9),
                "cosine_max": round(max(scores), 9),
                "violating_observation_count": sum(
                    score > maximum_allowed_negative
                    for score in scores
                ),
            }
        )

    source_summaries.sort(
        key=lambda item: float(item["cosine_max"]),
        reverse=True,
    )

    source_yield_summaries: list[dict[str, Any]] = []
    for source_key in sorted(planned_sources):
        source = planned_sources[source_key]
        planned_sample_count = _planned_sample_count(source)
        rows = [
            item
            for item in negative_rows_raw
            if str(item[1]["source_key"]) == str(source_key)
        ]
        observation_count = len(rows)
        source_yield_summaries.append(
            {
                "source_key": source_key,
                "subject_performer_id":
                    source["subject_performer_id"],
                "subject_performer_name":
                    source.get("subject_performer_name", ""),
                "resolved_path":
                    str(source.get("resolved_path") or ""),
                "planned_sample_count": planned_sample_count,
                "observation_count": observation_count,
                "extraction_yield_fraction": round(
                    observation_count / planned_sample_count,
                    9,
                ),
            }
        )

    source_yield_summaries.sort(
        key=lambda item: (
            float(item["extraction_yield_fraction"]),
            str(item["source_key"]),
        )
    )

    planned_performer_ids = sorted(
        {
            str(source["subject_performer_id"])
            for source in planned_sources.values()
        }
    )
    performer_yield_summaries: list[dict[str, Any]] = []
    for performer_id in planned_performer_ids:
        performer_sources = [
            source
            for source in planned_sources.values()
            if str(source["subject_performer_id"]) == performer_id
        ]
        planned_sample_count = sum(
            _planned_sample_count(source)
            for source in performer_sources
        )
        rows = [
            item
            for item in negative_rows_raw
            if str(item[1]["subject_performer_id"])
            == performer_id
        ]
        observed_source_count = len(
            {
                str(item[1]["source_key"])
                for item in rows
            }
        )
        observation_count = len(rows)
        performer_yield_summaries.append(
            {
                "subject_performer_id": performer_id,
                "subject_performer_name":
                    performer_sources[0].get(
                        "subject_performer_name",
                        "",
                    ),
                "planned_source_count": len(performer_sources),
                "observed_source_count": observed_source_count,
                "planned_sample_count": planned_sample_count,
                "observation_count": observation_count,
                "extraction_yield_fraction": round(
                    observation_count / planned_sample_count,
                    9,
                ),
            }
        )

    performer_yield_summaries.sort(
        key=lambda item: (
            float(item["extraction_yield_fraction"]),
            str(item["subject_performer_id"]),
        )
    )

    planned_negative_observation_count = sum(
        _planned_sample_count(source)
        for source in planned_sources.values()
    )

    positive_scores = [
        item[0]
        for item in positive_rows_raw
    ]
    negative_scores = [
        item[0]
        for item in negative_rows_raw
    ]
    violating_negative_rows = [
        item
        for item in negative_rows_raw
        if item[0] > maximum_allowed_negative
    ]

    violating_closest_group_counts: dict[str, int] = {}
    for _, row in violating_negative_rows:
        group_id = str(
            row["closest_positive_group"]["group_id"]
        )
        violating_closest_group_counts[group_id] = (
            violating_closest_group_counts.get(group_id, 0) + 1
        )

    violating_closest_group_summaries = [
        {
            "group_id": group_id,
            "observation_count": count,
            "observation_fraction": round(
                count / len(violating_negative_rows),
                9,
            ),
        }
        for group_id, count in sorted(
            violating_closest_group_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]

    positive_rows = [item[1] for item in positive_rows_raw]
    negative_rows = [item[1] for item in negative_rows_raw]

    return {
        "format": FORMAT,
        "version": VERSION,
        "target_performer_id": bank["performer_id"],
        "identity_bank_sha256": bank["identity_bank_sha256"],
        "positive_reference_count": len(positive_rows),
        "negative_observation_count": len(negative_rows),
        "negative_performer_count": len(performer_summaries),
        "planned_negative_observation_count":
            planned_negative_observation_count,
        "planned_negative_performer_count":
            len(planned_performer_ids),
        "planned_negative_source_count": len(planned_sources),
        "observed_negative_source_count": len(
            {
                str(item[1]["source_key"])
                for item in negative_rows_raw
            }
        ),
        "negative_extraction_yield_fraction": round(
            len(negative_rows)
            / planned_negative_observation_count,
            9,
        ),
        "positive_floor": round(positive_floor, 9),
        "positive_cosine_median":
            round(statistics.median(positive_scores), 9),
        "positive_cosine_max": round(max(positive_scores), 9),
        "positive_reference_to_target_cosine_min": round(
            min(reference_to_target_scores),
            9,
        ),
        "positive_reference_to_target_cosine_median": round(
            statistics.median(reference_to_target_scores),
            9,
        ),
        "positive_reference_to_target_cosine_max": round(
            max(reference_to_target_scores),
            9,
        ),
        "positive_group_count": len(positive_group_summaries),
        "positive_group_summaries": positive_group_summaries,
        "weakest_positive_group": min(
            positive_group_summaries,
            key=lambda item: float(
                item["leave_group_out_cosine_min"]
            ),
        ),
        "positive_cross_group_pair_count":
            len(positive_cross_group_pairs),
        "positive_cross_group_centroid_cosine_min": round(
            min(cross_group_scores),
            9,
        ),
        "positive_cross_group_centroid_cosine_median": round(
            statistics.median(cross_group_scores),
            9,
        ),
        "positive_cross_group_centroid_cosine_max": round(
            max(cross_group_scores),
            9,
        ),
        "positive_cross_group_pairs":
            positive_cross_group_pairs,
        "negative_ceiling": round(negative_ceiling, 9),
        "negative_cosine_median":
            round(statistics.median(negative_scores), 9),
        "negative_cosine_min": round(min(negative_scores), 9),
        "minimum_required_separation_margin":
            MIN_COSINE_SEPARATION_MARGIN,
        "maximum_allowed_negative_cosine":
            round(maximum_allowed_negative, 9),
        "observed_separation_margin": round(observed_margin, 9),
        "stage13_observed_separation_margin":
            round(stage13_margin, 9),
        "stage13_identity_matching_authorized":
            core["identity_matching_authorized"],
        "stage13_calibration_blockers":
            core["calibration_blockers"],
        "lowest_positive_reference": positive_rows[0],
        "highest_negative_match": negative_rows[0],
        "violating_negative_observation_count":
            len(violating_negative_rows),
        "violating_negative_observation_fraction": round(
            len(violating_negative_rows)
            / len(negative_rows_raw),
            9,
        ),
        "violating_negative_performer_count": len(
            {
                str(item[1]["subject_performer_id"])
                for item in violating_negative_rows
            }
        ),
        "violating_negative_source_count": len(
            {
                str(item[1]["source_key"])
                for item in violating_negative_rows
            }
        ),
        "violating_closest_positive_group_summaries":
            violating_closest_group_summaries,
        "negative_performer_summaries": performer_summaries,
        "negative_source_summaries": source_summaries,
        "highest_collision_negative_performer":
            performer_summaries[0],
        "highest_collision_negative_source":
            source_summaries[0],
        "negative_performer_yield_summaries":
            performer_yield_summaries,
        "negative_source_yield_summaries":
            source_yield_summaries,
        "lowest_yield_negative_performer":
            performer_yield_summaries[0],
        "lowest_yield_negative_source":
            source_yield_summaries[0],
        "top_negative_matches": negative_rows[:top_matches],
        "diagnostic_only": True,
        "identity_matching_authority": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def build_identity_calibration_diagnostic_files(
    bank_path: str | Path,
    plan_path: str | Path,
    negative_observations_path: str | Path,
    output_path: str | Path,
    *,
    top_matches: int = 10,
) -> dict[str, Any]:
    result = build_identity_calibration_diagnostic(
        _read_json(bank_path, label="identity bank"),
        _read_json(
            plan_path,
            label="identity calibration plan",
        ),
        _read_json(
            negative_observations_path,
            label="identity negative observations",
        ),
        top_matches=top_matches,
    )

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityCalibrationDiagnosticError(
            f"identity calibration diagnostic already exists: {output}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )
    return result

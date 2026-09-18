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

    planned_sources = {
        source["source_key"]: source
        for source in plan["sources"]
    }

    negative_rows_raw: list[tuple[float, dict[str, Any]]] = []
    for observation in negative_observations["observations"]:
        source = planned_sources[observation["source_key"]]
        score = _cosine(
            _embedding(
                observation["embedding"],
                dimension=dimension,
                label="diagnostic negative embedding",
            ),
            target_centroid,
        )
        negative_rows_raw.append(
            (
                score,
                {
                    "cosine": round(score, 9),
                    "subject_performer_id":
                        observation["subject_performer_id"],
                    "subject_performer_name":
                        source.get("subject_performer_name", ""),
                    "source_key": observation["source_key"],
                    "timestamp_seconds":
                        observation.get("timestamp_seconds"),
                    "eye": observation["eye"],
                    "frame_sha256": observation["frame_sha256"],
                },
            )
        )

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
        planned_sample_count = int(
            source.get(
                "sample_count",
                len(source.get("samples", [])),
            )
        )
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
            int(
                source.get(
                    "sample_count",
                    len(source.get("samples", [])),
                )
            )
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
        int(
            source.get(
                "sample_count",
                len(source.get("samples", [])),
            )
        )
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
        "negative_performer_summaries": performer_summaries,
        "negative_source_summaries": source_summaries,
        "negative_performer_yield_summaries":
            performer_yield_summaries,
        "negative_source_yield_summaries":
            source_yield_summaries,
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

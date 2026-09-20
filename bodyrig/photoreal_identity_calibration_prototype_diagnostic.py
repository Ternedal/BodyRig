from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping

from bodyrig import photoreal_identity_calibration as calibration


FORMAT = "bodyrig-photoreal-identity-calibration-prototype-diagnostic"
VERSION = 1
ATTESTATION_FORMAT = "bodyrig-photoreal-identity-group-attestation"


class PhotorealIdentityCalibrationPrototypeDiagnosticError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            f"{label} is unreadable: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            f"{label} must be a JSON object"
        )
    return value


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "cannot summarize empty score set"
        )
    return {
        "min": round(min(values), 9),
        "median": round(float(statistics.median(values)), 9),
        "max": round(max(values), 9),
    }


def _validate_attestation(
    attestation: Mapping[str, Any],
    *,
    bank: Mapping[str, Any],
    group_ids: set[str],
) -> None:
    if (
        attestation.get("format") != ATTESTATION_FORMAT
        or attestation.get("version") != 1
    ):
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "identity group attestation format/version mismatch"
        )
    if attestation.get("human_identity_attested") is not True:
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "identity group attestation lacks human identity confirmation"
        )
    if attestation.get("identity_group_selection_authority") is not True:
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "identity group attestation lacks group-selection authority"
        )
    if str(attestation.get("identity_bank_sha256") or "").strip().lower() != str(
        bank.get("identity_bank_sha256") or ""
    ).strip().lower():
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "identity group attestation targets a different bank"
        )
    accepted = {
        str(value or "").strip()
        for value in attestation.get("accepted_group_ids") or []
    }
    rejected = {
        str(value or "").strip()
        for value in attestation.get("rejected_group_ids") or []
    }
    if accepted != group_ids or rejected:
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "prototype diagnostic requires every bank group human-attested as target"
        )
    for field in (
        "identity_matching_authorized",
        "teacher_training_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        if attestation.get(field) is not False:
            raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
                f"identity group attestation crossed downstream authority: {field}"
            )


def _negative_vectors(
    *,
    bank: Mapping[str, Any],
    plan: Mapping[str, Any],
    negative_observations: Mapping[str, Any],
    dimension: int,
) -> list[dict[str, Any]]:
    sources = calibration._validate_plan(plan, bank, dimension)
    if (
        negative_observations.get("format") != calibration.OBSERVATIONS_FORMAT
        or negative_observations.get("version") != calibration.OBSERVATIONS_VERSION
    ):
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "identity negative observations format/version mismatch"
        )
    if str(negative_observations.get("target_performer_id") or "") != str(
        bank.get("performer_id") or ""
    ):
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "identity negative observations target performer mismatch"
        )
    if calibration._sha(
        negative_observations.get("identity_bank_sha256"),
        label="negative observations bank SHA-256",
    ) != bank["identity_bank_sha256"]:
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "identity negative observations target different bank"
        )
    if (
        negative_observations.get("extractor") != bank.get("extractor")
        or negative_observations.get("extractor_revision")
        != bank.get("extractor_revision")
    ):
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "identity negative observations extractor provenance mismatch"
        )
    if calibration._sha(
        negative_observations.get("model_set_sha256"),
        label="negative observations model-set SHA-256",
    ) != bank["model_set_sha256"]:
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "identity negative observations target different model set"
        )
    if negative_observations.get("embedding_dimension") != dimension:
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "identity negative observations embedding dimension mismatch"
        )
    if (
        negative_observations.get("calibration_only") is not True
        or negative_observations.get("build_only") is not True
        or negative_observations.get("production_activation") is not False
    ):
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "identity negative observations authority boundary is invalid"
        )

    raw_values = negative_observations.get("observations")
    if not isinstance(raw_values, list) or not raw_values:
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            "identity negative observations are empty"
        )

    result: list[dict[str, Any]] = []
    seen_frames: set[str] = set()
    for index, raw in enumerate(raw_values):
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
                "identity negative observation is invalid"
            )
        source_key = calibration._text(
            raw.get("source_key"),
            label="negative observation source key",
        )
        source = sources.get(source_key)
        if source is None:
            raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
                f"identity negative observation uses unplanned source: {source_key}"
            )
        if calibration._sha(
            raw.get("source_sha256"),
            label="negative observation source SHA-256",
        ) != source["source_sha256"]:
            raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
                f"identity negative source bytes changed: {source_key}"
            )
        subject = calibration._text(
            raw.get("subject_performer_id"),
            label="negative observation subject",
            maximum=256,
        )
        if subject != source["subject_performer_id"]:
            raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
                "identity negative observation subject changed"
            )
        timestamp_raw = raw.get("timestamp_seconds")
        timestamp = None if timestamp_raw is None else round(float(timestamp_raw), 6)
        eye = calibration._text(
            raw.get("eye"),
            label="negative observation eye",
            maximum=16,
        )
        if (timestamp, eye) not in source["samples"]:
            raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
                f"identity negative observation sample was not planned: {source_key}"
            )
        frame_sha = calibration._sha(
            raw.get("frame_sha256"),
            label="negative observation frame SHA-256",
        )
        if frame_sha in seen_frames:
            raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
                "identity negative observation frame is duplicated"
            )
        seen_frames.add(frame_sha)
        vector = calibration._embedding(
            raw.get("embedding"),
            dimension=dimension,
            label=f"negative identity embedding[{index}]",
        )
        result.append(
            {
                "subject_performer_id": subject,
                "frame_sha256": frame_sha,
                "embedding": vector,
            }
        )
    return result


def analyze(
    *,
    bank: Mapping[str, Any],
    plan: Mapping[str, Any],
    negative_observations: Mapping[str, Any],
    attestation: Mapping[str, Any],
) -> dict[str, Any]:
    dimension, positive_references, bank_centroid = calibration._validate_bank(bank)
    groups: dict[str, list[list[float]]] = {}
    for reference in positive_references:
        groups.setdefault(reference["group_id"], []).append(reference["embedding"])
    group_ids = set(groups)
    _validate_attestation(attestation, bank=bank, group_ids=group_ids)
    negatives = _negative_vectors(
        bank=bank,
        plan=plan,
        negative_observations=negative_observations,
        dimension=dimension,
    )

    group_centroids = {
        group_id: calibration._centroid(vectors)
        for group_id, vectors in groups.items()
    }
    group_balanced_target = calibration._centroid(
        [group_centroids[group_id] for group_id in sorted(group_centroids)]
    )

    current_positive_scores = []
    for reference in positive_references:
        others = [
            item["embedding"]
            for item in positive_references
            if item["group_id"] != reference["group_id"]
        ]
        current_positive_scores.append(
            calibration._cosine(
                reference["embedding"],
                calibration._centroid(others),
            )
        )
    current_negative_scores = [
        calibration._cosine(item["embedding"], bank_centroid)
        for item in negatives
    ]

    group_balanced_positive_scores: list[float] = []
    nearest_positive_scores: list[float] = []
    per_group: list[dict[str, Any]] = []
    ordered_groups = sorted(group_centroids)
    for group_id in ordered_groups:
        own = group_centroids[group_id]
        other_groups = [
            group_centroids[other]
            for other in ordered_groups
            if other != group_id
        ]
        lgo_score = calibration._cosine(
            own,
            calibration._centroid(other_groups),
        )
        similarities = sorted(
            (
                (
                    other,
                    calibration._cosine(own, group_centroids[other]),
                )
                for other in ordered_groups
                if other != group_id
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        nearest_group_id, nearest_score = similarities[0]
        group_balanced_positive_scores.append(lgo_score)
        nearest_positive_scores.append(nearest_score)
        per_group.append(
            {
                "group_id": group_id,
                "reference_count": len(groups[group_id]),
                "group_balanced_leave_group_out_cosine": round(lgo_score, 9),
                "nearest_other_group_id": nearest_group_id,
                "nearest_other_group_cosine": round(nearest_score, 9),
            }
        )

    group_balanced_negative_scores = [
        calibration._cosine(item["embedding"], group_balanced_target)
        for item in negatives
    ]
    nearest_prototype_negative_scores = [
        max(
            calibration._cosine(item["embedding"], prototype)
            for prototype in group_centroids.values()
        )
        for item in negatives
    ]

    variants = {
        "current-reference-weighted": {
            "positive": current_positive_scores,
            "negative": current_negative_scores,
        },
        "group-balanced-centroid-lgo": {
            "positive": group_balanced_positive_scores,
            "negative": group_balanced_negative_scores,
        },
        "nearest-group-prototype": {
            "positive": nearest_positive_scores,
            "negative": nearest_prototype_negative_scores,
        },
    }

    variant_results: dict[str, Any] = {}
    for name, values in variants.items():
        positive_floor = min(values["positive"])
        negative_ceiling = max(values["negative"])
        margin = positive_floor - negative_ceiling
        variant_results[name] = {
            "positive_score_count": len(values["positive"]),
            "negative_score_count": len(values["negative"]),
            "positive_cosine": _summary(values["positive"]),
            "negative_cosine": _summary(values["negative"]),
            "positive_floor": round(positive_floor, 9),
            "negative_ceiling": round(negative_ceiling, 9),
            "observed_separation_margin": round(margin, 9),
            "minimum_required_separation_margin": calibration.MIN_COSINE_SEPARATION_MARGIN,
            "would_meet_margin": margin >= calibration.MIN_COSINE_SEPARATION_MARGIN,
            "diagnostic_only": True,
        }

    per_group.sort(
        key=lambda item: (
            item["group_balanced_leave_group_out_cosine"],
            item["group_id"],
        )
    )

    negative_rows: list[dict[str, Any]] = []
    for index, item in enumerate(negatives):
        negative_rows.append(
            {
                "negative_index": index,
                "subject_performer_id": item["subject_performer_id"],
                "frame_sha256": item["frame_sha256"],
                "current_target_cosine": round(
                    current_negative_scores[index],
                    9,
                ),
                "group_balanced_target_cosine": round(
                    group_balanced_negative_scores[index],
                    9,
                ),
                "nearest_group_prototype_cosine": round(
                    nearest_prototype_negative_scores[index],
                    9,
                ),
            }
        )
    negative_rows.sort(
        key=lambda item: item["nearest_group_prototype_cosine"],
        reverse=True,
    )

    return {
        "format": FORMAT,
        "version": VERSION,
        "target_performer_id": str(bank.get("performer_id") or ""),
        "identity_bank_sha256": str(bank.get("identity_bank_sha256") or ""),
        "positive_reference_count": len(positive_references),
        "positive_group_count": len(group_centroids),
        "negative_observation_count": len(negatives),
        "negative_performer_count": len(
            {item["subject_performer_id"] for item in negatives}
        ),
        "variants": variant_results,
        "groups_weakest_first": per_group,
        "negatives_highest_collision_first": negative_rows,
        "diagnostic_only": True,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare current and prototype/group-balanced identity calibration "
            "scoring without granting any calibration authority."
        )
    )
    parser.add_argument("--identity-bank", type=Path, required=True)
    parser.add_argument("--calibration-plan", type=Path, required=True)
    parser.add_argument("--negative-observations", type=Path, required=True)
    parser.add_argument("--identity-attestation", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.out.expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityCalibrationPrototypeDiagnosticError(
            f"diagnostic output already exists: {output}"
        )
    result = analyze(
        bank=_read_json(
            args.identity_bank.expanduser().resolve(),
            label="identity bank",
        ),
        plan=_read_json(
            args.calibration_plan.expanduser().resolve(),
            label="identity calibration plan",
        ),
        negative_observations=_read_json(
            args.negative_observations.expanduser().resolve(),
            label="identity negative observations",
        ),
        attestation=_read_json(
            args.identity_attestation.expanduser().resolve(),
            label="identity group attestation",
        ),
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

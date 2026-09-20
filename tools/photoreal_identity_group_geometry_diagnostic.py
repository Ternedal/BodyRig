from __future__ import annotations

import argparse
import html
import importlib.util
import json
import math
import os
import sys
from itertools import combinations
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from bodyrig import photoreal_identity_group_review as review


FORMAT = "bodyrig-photoreal-identity-group-geometry-diagnostic"
VERSION = 1


class PhotorealIdentityGroupGeometryDiagnosticError(RuntimeError):
    pass


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            f"could not load diagnostic dependency: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2.0
    )
    return {
        "min": round(ordered[0], 9),
        "median": round(median, 9),
        "max": round(ordered[-1], 9),
    }


def _analyze_variant(
    *,
    flip: Any,
    positives: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
) -> dict[str, Any]:
    if not positives or not negatives:
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "group geometry requires positive and negative embeddings"
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in positives:
        group_id = str(item.get("group_id") or "").strip()
        if not group_id:
            raise PhotorealIdentityGroupGeometryDiagnosticError(
                "positive item lacks group id"
            )
        grouped[group_id].append(item)
    if len(grouped) < 2:
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "group geometry requires at least two positive groups"
        )

    ordered_groups = sorted(grouped)
    group_centroids = {
        group_id: flip._centroid(
            [item["embedding"] for item in grouped[group_id]]
        )
        for group_id in ordered_groups
    }
    group_balanced_target = flip._centroid(
        [group_centroids[group_id] for group_id in ordered_groups]
    )

    pairwise_groups: list[dict[str, Any]] = []
    for left_index, left_group in enumerate(ordered_groups):
        for right_group in ordered_groups[left_index + 1 :]:
            pairwise_groups.append(
                {
                    "left_group_id": left_group,
                    "right_group_id": right_group,
                    "cosine": round(
                        flip._cosine(
                            group_centroids[left_group],
                            group_centroids[right_group],
                        ),
                        9,
                    ),
                }
            )
    pairwise_groups.sort(
        key=lambda item: (
            float(item["cosine"]),
            str(item["left_group_id"]),
            str(item["right_group_id"]),
        )
    )

    negative_group_edges: list[dict[str, Any]] = []
    for negative in negatives:
        for group_id in ordered_groups:
            negative_group_edges.append(
                {
                    "negative_index": int(negative["negative_index"]),
                    "subject_performer_id": str(
                        negative["subject_performer_id"]
                    ),
                    "group_id": group_id,
                    "cosine": round(
                        flip._cosine(
                            negative["embedding"],
                            group_centroids[group_id],
                        ),
                        9,
                    ),
                }
            )
    negative_group_edges.sort(
        key=lambda item: (
            -float(item["cosine"]),
            int(item["negative_index"]),
            str(item["group_id"]),
        )
    )

    group_rows: list[dict[str, Any]] = []
    for group_id in ordered_groups:
        rows = grouped[group_id]
        centroid = group_centroids[group_id]
        other_group_ids = [
            other for other in ordered_groups if other != group_id
        ]
        other_centroids = [
            group_centroids[other] for other in other_group_ids
        ]
        leave_group_out_target = flip._centroid(other_centroids)
        centroid_lgo = flip._cosine(centroid, leave_group_out_target)

        reference_lgo = [
            flip._cosine(item["embedding"], leave_group_out_target)
            for item in rows
        ]
        within_group: list[float] = []
        for left_index, left in enumerate(rows):
            for right in rows[left_index + 1 :]:
                within_group.append(
                    flip._cosine(left["embedding"], right["embedding"])
                )

        positive_neighbors = sorted(
            (
                (
                    other,
                    flip._cosine(centroid, group_centroids[other]),
                )
                for other in other_group_ids
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        nearest_positive_group, nearest_positive_cosine = positive_neighbors[0]
        farthest_positive_group, farthest_positive_cosine = positive_neighbors[-1]

        negative_scores = sorted(
            (
                (
                    int(negative["negative_index"]),
                    str(negative["subject_performer_id"]),
                    flip._cosine(negative["embedding"], centroid),
                )
                for negative in negatives
            ),
            key=lambda item: item[2],
            reverse=True,
        )
        negative_index, negative_subject, negative_ceiling = negative_scores[0]

        group_rows.append(
            {
                "group_id": group_id,
                "reference_count": len(rows),
                "reference_indices": sorted(
                    int(item["reference_index"]) for item in rows
                ),
                "within_group_cosine": _summary(within_group),
                "reference_leave_group_out_cosine": _summary(reference_lgo),
                "centroid_to_group_balanced_target_cosine": round(
                    flip._cosine(centroid, group_balanced_target),
                    9,
                ),
                "centroid_to_leave_group_out_target_cosine": round(
                    centroid_lgo,
                    9,
                ),
                "nearest_positive_group_id": nearest_positive_group,
                "nearest_positive_group_cosine": round(
                    nearest_positive_cosine,
                    9,
                ),
                "farthest_positive_group_id": farthest_positive_group,
                "farthest_positive_group_cosine": round(
                    farthest_positive_cosine,
                    9,
                ),
                "highest_negative_index": negative_index,
                "highest_negative_subject_performer_id": negative_subject,
                "highest_negative_group_cosine": round(
                    negative_ceiling,
                    9,
                ),
                "local_group_separation_margin": round(
                    centroid_lgo - negative_ceiling,
                    9,
                ),
            }
        )

    group_rows.sort(
        key=lambda item: (
            float(item["local_group_separation_margin"]),
            float(item["centroid_to_leave_group_out_target_cosine"]),
            str(item["group_id"]),
        )
    )

    reference_lgo_all: list[dict[str, Any]] = []
    for item in positives:
        group_id = str(item["group_id"])
        other_centroids = [
            group_centroids[other]
            for other in ordered_groups
            if other != group_id
        ]
        score = flip._cosine(
            item["embedding"],
            flip._centroid(other_centroids),
        )
        reference_lgo_all.append(
            {
                "reference_index": int(item["reference_index"]),
                "group_id": group_id,
                "cosine": round(score, 9),
            }
        )
    reference_lgo_all.sort(
        key=lambda item: (
            float(item["cosine"]),
            int(item["reference_index"]),
        )
    )

    return {
        "positive_reference_count": len(positives),
        "positive_group_count": len(grouped),
        "negative_observation_count": len(negatives),
        "group_balanced_target_reference": True,
        "group_rows": group_rows,
        "pairwise_positive_group_cosines": pairwise_groups,
        "negative_to_positive_group_cosines": negative_group_edges,
        "reference_leave_group_out": reference_lgo_all,
        "diagnostic_only": True,
    }


def _compare_variants(
    *,
    current: dict[str, Any],
    alternate: dict[str, Any],
) -> list[dict[str, Any]]:
    current_rows = {
        str(item["group_id"]): item
        for item in current["group_rows"]
    }
    alternate_rows = {
        str(item["group_id"]): item
        for item in alternate["group_rows"]
    }
    if set(current_rows) != set(alternate_rows):
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "recognizer variants produced different positive groups"
        )

    result: list[dict[str, Any]] = []
    for group_id in sorted(current_rows):
        left = current_rows[group_id]
        right = alternate_rows[group_id]
        result.append(
            {
                "group_id": group_id,
                "reference_count": int(left["reference_count"]),
                "current_centroid_lgo": left[
                    "centroid_to_leave_group_out_target_cosine"
                ],
                "alternate_centroid_lgo": right[
                    "centroid_to_leave_group_out_target_cosine"
                ],
                "delta_centroid_lgo": round(
                    float(
                        right[
                            "centroid_to_leave_group_out_target_cosine"
                        ]
                    )
                    - float(
                        left[
                            "centroid_to_leave_group_out_target_cosine"
                        ]
                    ),
                    9,
                ),
                "current_highest_negative_group_cosine": left[
                    "highest_negative_group_cosine"
                ],
                "alternate_highest_negative_group_cosine": right[
                    "highest_negative_group_cosine"
                ],
                "delta_highest_negative_group_cosine": round(
                    float(right["highest_negative_group_cosine"])
                    - float(left["highest_negative_group_cosine"]),
                    9,
                ),
                "current_local_group_separation_margin": left[
                    "local_group_separation_margin"
                ],
                "alternate_local_group_separation_margin": right[
                    "local_group_separation_margin"
                ],
                "delta_local_group_separation_margin": round(
                    float(right["local_group_separation_margin"])
                    - float(left["local_group_separation_margin"]),
                    9,
                ),
                "current_highest_negative_index": left[
                    "highest_negative_index"
                ],
                "alternate_highest_negative_index": right[
                    "highest_negative_index"
                ],
                "current_nearest_positive_group_id": left[
                    "nearest_positive_group_id"
                ],
                "alternate_nearest_positive_group_id": right[
                    "nearest_positive_group_id"
                ],
            }
        )
    result.sort(
        key=lambda item: (
            float(item["alternate_local_group_separation_margin"]),
            float(item["alternate_centroid_lgo"]),
            str(item["group_id"]),
        )
    )
    return result



def _ablation_search(
    *,
    flip: Any,
    positives: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
    max_removed_groups: int = 3,
) -> dict[str, Any]:
    group_ids = sorted({str(item["group_id"]) for item in positives})
    if len(group_ids) < 4:
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "group ablation requires at least four positive groups"
        )
    if max_removed_groups < 1 or max_removed_groups >= len(group_ids) - 1:
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "group ablation maximum removal count is invalid"
        )

    records: list[dict[str, Any]] = []
    for remove_count in range(0, max_removed_groups + 1):
        for removed in combinations(group_ids, remove_count):
            removed_set = set(removed)
            remaining = [
                item
                for item in positives
                if str(item["group_id"]) not in removed_set
            ]
            remaining_groups = sorted(
                {str(item["group_id"]) for item in remaining}
            )
            if len(remaining_groups) < 2:
                continue

            models = flip._score_models(remaining, negatives)
            margins = {
                name: float(model["observed_separation_margin"])
                for name, model in models.items()
            }
            passes = {
                name: bool(model["would_meet_margin"])
                for name, model in models.items()
            }
            records.append(
                {
                    "removed_group_ids": list(removed),
                    "removed_group_count": remove_count,
                    "removed_reference_count": len(positives) - len(remaining),
                    "remaining_group_count": len(remaining_groups),
                    "remaining_reference_count": len(remaining),
                    "scoring_models": models,
                    "minimum_margin_across_models": round(
                        min(margins.values()),
                        9,
                    ),
                    "maximum_margin_across_models": round(
                        max(margins.values()),
                        9,
                    ),
                    "all_models_meet_margin": all(passes.values()),
                    "any_model_meets_margin": any(passes.values()),
                    "diagnostic_only": True,
                }
            )

    def rank_key(item: dict[str, Any]) -> tuple[float, float, float, int, tuple[str, ...]]:
        models = item["scoring_models"]
        return (
            -float(item["minimum_margin_across_models"]),
            -float(
                models["current-reference-weighted"][
                    "observed_separation_margin"
                ]
            ),
            -float(
                models["group-balanced-centroid-lgo"][
                    "observed_separation_margin"
                ]
            ),
            int(item["removed_reference_count"]),
            tuple(str(value) for value in item["removed_group_ids"]),
        )

    by_removed_count: dict[str, list[dict[str, Any]]] = {}
    for remove_count in range(0, max_removed_groups + 1):
        subset = [
            item
            for item in records
            if item["removed_group_count"] == remove_count
        ]
        subset.sort(key=rank_key)
        by_removed_count[str(remove_count)] = subset

    all_models_pass = [
        item for item in records if item["all_models_meet_margin"]
    ]
    all_models_pass.sort(
        key=lambda item: (
            int(item["removed_group_count"]),
            *rank_key(item),
        )
    )
    any_model_pass = [
        item for item in records if item["any_model_meets_margin"]
    ]
    any_model_pass.sort(
        key=lambda item: (
            int(item["removed_group_count"]),
            *rank_key(item),
        )
    )

    candidate = None
    candidate_set = {"scene:805", "scene:889", "scene:978"}
    for item in records:
        if set(item["removed_group_ids"]) == candidate_set:
            candidate = item
            break

    return {
        "max_removed_groups": max_removed_groups,
        "combination_count": len(records),
        "ranking_objective": (
            "maximize the minimum observed separation margin across all three "
            "diagnostic scoring models; ties favor current-reference-weighted "
            "then group-balanced margin, then fewer removed references"
        ),
        "by_removed_count": by_removed_count,
        "first_all_models_pass": (
            all_models_pass[0] if all_models_pass else None
        ),
        "first_any_model_pass": (
            any_model_pass[0] if any_model_pass else None
        ),
        "candidate_scene_805_889_978": candidate,
        "counterfactual_only": True,
        "valid_human_attested_groups_are_not_rejected": True,
        "identity_bank_mutation_authority": False,
        "diagnostic_only": True,
    }



def _score_model_witnesses(
    *,
    flip: Any,
    positives: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
) -> dict[str, Any]:
    if not positives or not negatives:
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "boundary witness scoring requires positive and negative embeddings"
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in positives:
        group_id = str(item.get("group_id") or "").strip()
        if not group_id:
            raise PhotorealIdentityGroupGeometryDiagnosticError(
                "boundary witness positive lacks group id"
            )
        grouped[group_id].append(item)
    if len(grouped) < 2:
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "boundary witness scoring requires at least two positive groups"
        )

    ordered_groups = sorted(grouped)
    group_centroids = {
        group_id: flip._centroid(
            [item["embedding"] for item in grouped[group_id]]
        )
        for group_id in ordered_groups
    }

    current_positive: list[dict[str, Any]] = []
    for item in positives:
        others = [
            other["embedding"]
            for other in positives
            if str(other["group_id"]) != str(item["group_id"])
        ]
        if not others:
            raise PhotorealIdentityGroupGeometryDiagnosticError(
                "boundary witness positive group has no leave-group-out peers"
            )
        current_positive.append(
            {
                "reference_index": int(item["reference_index"]),
                "group_id": str(item["group_id"]),
                "score": flip._cosine(
                    item["embedding"],
                    flip._centroid(others),
                ),
            }
        )
    current_target = flip._centroid(
        [item["embedding"] for item in positives]
    )
    current_negative = [
        {
            "negative_index": int(item["negative_index"]),
            "subject_performer_id": str(item["subject_performer_id"]),
            "score": flip._cosine(item["embedding"], current_target),
        }
        for item in negatives
    ]

    balanced_positive: list[dict[str, Any]] = []
    prototype_positive: list[dict[str, Any]] = []
    for group_id in ordered_groups:
        own = group_centroids[group_id]
        other_group_ids = [
            other for other in ordered_groups if other != group_id
        ]
        other_centroids = [
            group_centroids[other] for other in other_group_ids
        ]
        balanced_positive.append(
            {
                "group_id": group_id,
                "score": flip._cosine(
                    own,
                    flip._centroid(other_centroids),
                ),
            }
        )
        nearest = max(
            (
                {
                    "neighbor_group_id": other,
                    "score": flip._cosine(
                        own,
                        group_centroids[other],
                    ),
                }
                for other in other_group_ids
            ),
            key=lambda item: float(item["score"]),
        )
        prototype_positive.append(
            {
                "group_id": group_id,
                "neighbor_group_id": nearest["neighbor_group_id"],
                "score": nearest["score"],
            }
        )

    balanced_target = flip._centroid(
        [group_centroids[group_id] for group_id in ordered_groups]
    )
    balanced_negative = [
        {
            "negative_index": int(item["negative_index"]),
            "subject_performer_id": str(item["subject_performer_id"]),
            "score": flip._cosine(item["embedding"], balanced_target),
        }
        for item in negatives
    ]
    prototype_negative: list[dict[str, Any]] = []
    for item in negatives:
        nearest = max(
            (
                {
                    "group_id": group_id,
                    "score": flip._cosine(
                        item["embedding"],
                        group_centroids[group_id],
                    ),
                }
                for group_id in ordered_groups
            ),
            key=lambda value: float(value["score"]),
        )
        prototype_negative.append(
            {
                "negative_index": int(item["negative_index"]),
                "subject_performer_id": str(item["subject_performer_id"]),
                "nearest_group_id": nearest["group_id"],
                "score": nearest["score"],
            }
        )

    raw = {
        "current-reference-weighted": (
            current_positive,
            current_negative,
        ),
        "group-balanced-centroid-lgo": (
            balanced_positive,
            balanced_negative,
        ),
        "nearest-group-prototype": (
            prototype_positive,
            prototype_negative,
        ),
    }

    result: dict[str, Any] = {}
    for name, (positive_rows, negative_rows) in raw.items():
        floor = min(
            positive_rows,
            key=lambda item: (
                float(item["score"]),
                int(item.get("reference_index", -1)),
                str(item.get("group_id", "")),
            ),
        )
        ceiling = max(
            negative_rows,
            key=lambda item: (
                float(item["score"]),
                -int(item["negative_index"]),
            ),
        )
        result[name] = {
            "positive_floor_witness": {
                **floor,
                "score": round(float(floor["score"]), 9),
            },
            "negative_ceiling_witness": {
                **ceiling,
                "score": round(float(ceiling["score"]), 9),
            },
            "observed_separation_margin": round(
                float(floor["score"]) - float(ceiling["score"]),
                9,
            ),
            "diagnostic_only": True,
        }
    return result


def _reference_ablation_after_removed_groups(
    *,
    flip: Any,
    positives: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
    removed_group_ids: list[str],
) -> dict[str, Any]:
    removed_set = set(removed_group_ids)
    remaining = [
        item
        for item in positives
        if str(item["group_id"]) not in removed_set
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in remaining:
        grouped[str(item["group_id"])].append(item)

    baseline_models = flip._score_models(remaining, negatives)
    baseline_witnesses = _score_model_witnesses(
        flip=flip,
        positives=remaining,
        negatives=negatives,
    )

    removable = [
        item
        for item in remaining
        if len(grouped[str(item["group_id"])]) >= 2
    ]
    records: list[dict[str, Any]] = []
    for item in removable:
        reference_index = int(item["reference_index"])
        subset = [
            other
            for other in remaining
            if int(other["reference_index"]) != reference_index
        ]
        models = flip._score_models(subset, negatives)
        margins = [
            float(model["observed_separation_margin"])
            for model in models.values()
        ]
        records.append(
            {
                "removed_reference_index": reference_index,
                "removed_group_id": str(item["group_id"]),
                "remaining_reference_count": len(subset),
                "remaining_group_count": len(
                    {str(other["group_id"]) for other in subset}
                ),
                "scoring_models": models,
                "minimum_margin_across_models": round(min(margins), 9),
                "all_models_meet_margin": all(
                    bool(model["would_meet_margin"])
                    for model in models.values()
                ),
                "witnesses": _score_model_witnesses(
                    flip=flip,
                    positives=subset,
                    negatives=negatives,
                ),
                "counterfactual_only": True,
                "diagnostic_only": True,
            }
        )

    records.sort(
        key=lambda item: (
            -float(item["minimum_margin_across_models"]),
            int(item["removed_reference_index"]),
        )
    )
    first_all_pass = next(
        (
            item
            for item in records
            if item["all_models_meet_margin"]
        ),
        None,
    )

    return {
        "removed_group_ids": list(removed_group_ids),
        "baseline_remaining_reference_count": len(remaining),
        "baseline_remaining_group_count": len(grouped),
        "baseline_scoring_models": baseline_models,
        "baseline_witnesses": baseline_witnesses,
        "removable_reference_count": len(removable),
        "ranked_single_reference_ablation": records,
        "best_single_reference_ablation": (
            records[0] if records else None
        ),
        "first_all_models_pass": first_all_pass,
        "counterfactual_only": True,
        "human_attested_valid_reference_is_not_rejected": True,
        "identity_bank_mutation_authority": False,
        "diagnostic_only": True,
    }



def _write_boundary_witness_review(
    *,
    confusion: Any,
    runtime: Any,
    output_root: Path,
    current_boundary: dict[str, Any],
    alternate_boundary: dict[str, Any],
    current_positives: list[dict[str, Any]],
    alternate_positives: list[dict[str, Any]],
    review_media: Mapping[int, dict[str, Any]],
) -> dict[str, Any]:
    current_floor = current_boundary["baseline_witnesses"][
        "current-reference-weighted"
    ]["positive_floor_witness"]
    alternate_floor = alternate_boundary["baseline_witnesses"][
        "current-reference-weighted"
    ]["positive_floor_witness"]
    witness_indices = {
        "w600k-r50": int(current_floor["reference_index"]),
        "antelopev2-glintr100": int(alternate_floor["reference_index"]),
    }
    witness_groups = sorted(
        {
            str(current_floor["group_id"]),
            str(alternate_floor["group_id"]),
        }
    )

    current_by_index = {
        int(item["reference_index"]): item
        for item in current_positives
    }
    alternate_by_index = {
        int(item["reference_index"]): item
        for item in alternate_positives
    }

    selected_indices = sorted(
        int(item["reference_index"])
        for item in current_positives
        if str(item["group_id"]) in witness_groups
    )
    if not selected_indices:
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "boundary witness review resolved no positive references"
        )

    output_root.mkdir(parents=True, exist_ok=False)
    media_root = output_root / "media"
    rows: list[dict[str, Any]] = []

    for reference_index in selected_indices:
        current = current_by_index[reference_index]
        alternate = alternate_by_index[reference_index]
        media = review_media.get(reference_index)
        if media is None:
            raise PhotorealIdentityGroupGeometryDiagnosticError(
                f"boundary witness review media missing for reference {reference_index}"
            )

        group_id = str(current["group_id"])
        sibling_indices = sorted(
            int(item["reference_index"])
            for item in current_positives
            if str(item["group_id"]) == group_id
            and int(item["reference_index"]) != reference_index
        )
        current_sibling = [
            {
                "reference_index": sibling_index,
                "cosine": round(
                    float(
                        sum(
                            a * b
                            for a, b in zip(
                                current["embedding"],
                                current_by_index[sibling_index]["embedding"],
                                strict=True,
                            )
                        )
                    ),
                    9,
                ),
            }
            for sibling_index in sibling_indices
        ]
        alternate_sibling = [
            {
                "reference_index": sibling_index,
                "cosine": round(
                    float(
                        sum(
                            a * b
                            for a, b in zip(
                                alternate["embedding"],
                                alternate_by_index[sibling_index]["embedding"],
                                strict=True,
                            )
                        )
                    ),
                    9,
                ),
            }
            for sibling_index in sibling_indices
        ]

        frame_name = f"ref-{reference_index:02d}-frame.png"
        crop_name = f"ref-{reference_index:02d}-aligned.png"
        confusion._write_png(
            runtime,
            media_root / frame_name,
            media["frame"],
        )
        confusion._write_png(
            runtime,
            media_root / crop_name,
            media["aligned"],
        )

        same_timestamp_siblings = [
            sibling_index
            for sibling_index in sibling_indices
            if current_by_index[sibling_index]["timestamp_seconds"]
            == current["timestamp_seconds"]
        ]
        opposite_eye_same_timestamp_siblings = [
            sibling_index
            for sibling_index in same_timestamp_siblings
            if str(current_by_index[sibling_index]["eye"])
            != str(current["eye"])
        ]
        witness_for = [
            variant
            for variant, index in witness_indices.items()
            if index == reference_index
        ]
        rows.append(
            {
                "reference_index": reference_index,
                "group_id": group_id,
                "witness_for": witness_for,
                "source_key": current["source_key"],
                "timestamp_seconds": current["timestamp_seconds"],
                "eye": current["eye"],
                "frame_sha256": current["frame_sha256"],
                "viewport_id": media.get("viewport_id"),
                "quality": current["quality"],
                "frame_image": f"media/{frame_name}",
                "aligned_image": f"media/{crop_name}",
                "sibling_reference_indices": sibling_indices,
                "same_timestamp_sibling_reference_indices": same_timestamp_siblings,
                "opposite_eye_same_timestamp_sibling_reference_indices": (
                    opposite_eye_same_timestamp_siblings
                ),
                "w600k_sibling_cosines": current_sibling,
                "glintr100_sibling_cosines": alternate_sibling,
            }
        )

    rows.sort(
        key=lambda item: (
            str(item["group_id"]),
            int(item["reference_index"]),
        )
    )

    def _fmt_quality(quality: Mapping[str, Any]) -> str:
        pose = quality.get("pose")
        pose_text = ""
        if isinstance(pose, Mapping):
            pose_text = (
                f"yaw={html.escape(str(pose.get('yaw_degrees')))} "
                f"pitch={html.escape(str(pose.get('pitch_degrees')))} "
                f"roll={html.escape(str(pose.get('roll_degrees')))}"
            )
        return (
            f"det={html.escape(str(quality.get('det_score')))}<br>"
            f"view={html.escape(str(quality.get('view_bin')))}<br>"
            f"{pose_text}<br>"
            f"facepx={html.escape(str(quality.get('bbox_min_dimension_pixels')))}<br>"
            f"offset={html.escape(str(quality.get('face_center_offset_fraction')))}<br>"
            f"frame sharp={html.escape(str(quality.get('frame_sharpness')))}<br>"
            f"crop sharp={html.escape(str(quality.get('face_crop_sharpness')))}"
        )

    html_rows: list[str] = []
    for row in rows:
        marker = (
            ", ".join(row["witness_for"])
            if row["witness_for"]
            else "sibling/control"
        )
        current_siblings = ", ".join(
            f"ref {item['reference_index']}: {item['cosine']:.6f}"
            for item in row["w600k_sibling_cosines"]
        ) or "none"
        alternate_siblings = ", ".join(
            f"ref {item['reference_index']}: {item['cosine']:.6f}"
            for item in row["glintr100_sibling_cosines"]
        ) or "none"
        html_rows.append(
            "<tr>"
            f"<td><strong>ref {row['reference_index']}</strong><br>"
            f"{html.escape(row['group_id'])}<br>"
            f"<strong>{html.escape(marker)}</strong><br>"
            f"t={html.escape(str(row['timestamp_seconds']))}s<br>"
            f"eye={html.escape(str(row['eye']))}<br>"
            f"viewport={html.escape(str(row['viewport_id']))}<br>"
            f"same-t sibling={html.escape(str(row['same_timestamp_sibling_reference_indices']))}<br>"
            f"stereo sibling={html.escape(str(row['opposite_eye_same_timestamp_sibling_reference_indices']))}</td>"
            f"<td><img class=\"frame\" src=\"{html.escape(row['frame_image'])}\"></td>"
            f"<td><img class=\"crop\" src=\"{html.escape(row['aligned_image'])}\"></td>"
            f"<td>{_fmt_quality(row['quality'])}</td>"
            f"<td>w600k: {html.escape(current_siblings)}<br><br>"
            f"glintr100: {html.escape(alternate_siblings)}</td>"
            f"<td>{html.escape(str(row['source_key']))}<br><small>{html.escape(str(row['frame_sha256']))}</small></td>"
            "</tr>"
        )

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BodyRig identity boundary witness review</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; background:#111; color:#eee; margin:24px; }}
.notice {{ border:1px solid #666; background:#1b1b1b; padding:12px; margin-bottom:16px; }}
table {{ border-collapse:collapse; width:100%; }}
th, td {{ border:1px solid #444; padding:9px; vertical-align:top; }}
th {{ background:#222; position:sticky; top:0; }}
img.frame {{ width:300px; max-height:300px; object-fit:contain; background:#000; }}
img.crop {{ width:180px; height:180px; object-fit:contain; background:#000; }}
small {{ color:#aaa; word-break:break-all; }}
</style>
</head>
<body>
<h1>BodyRig identity boundary witness review</h1>
<div class="notice">
<strong>Purpose:</strong> compare the exact boundary-setting positive references with every sibling reference in the same human-attested group.<br>
<strong>w600k witness:</strong> ref {witness_indices['w600k-r50']} / {html.escape(str(current_floor['group_id']))}<br>
<strong>glintr100 witness:</strong> ref {witness_indices['antelopev2-glintr100']} / {html.escape(str(alternate_floor['group_id']))}<br>
<strong>Authority:</strong> diagnostic only. No reference is rejected and no identity bank is changed.
</div>
<table>
<thead><tr>
<th>Reference</th><th>Exact replay frame</th><th>Aligned 112x112 crop</th>
<th>Quality / pose</th><th>Same-group cosine</th><th>Source / frame SHA</th>
</tr></thead>
<tbody>
{''.join(html_rows)}
</tbody>
</table>
</body>
</html>
"""
    html_path = output_root / "review-index.html"
    html_path.write_text(document, encoding="utf-8")
    json_path = output_root / "boundary-witness-review.json"
    json_path.write_text(
        json.dumps(
            {
                "witness_indices": witness_indices,
                "witness_groups": witness_groups,
                "rows": rows,
                "diagnostic_only": True,
                "reference_rejection_authority": False,
                "identity_bank_mutation_authority": False,
                "production_activation": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "root": str(output_root),
        "html": str(html_path),
        "json": str(json_path),
        "witness_indices": witness_indices,
        "witness_groups": witness_groups,
        "row_count": len(rows),
        "diagnostic_only": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Quantify positive-group geometry and negative overlap for the "
            "human-attested Photoreal identity bank under the current and "
            "alternate recognizers. Diagnostic only."
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
    output = args.out.expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            f"group geometry output already exists: {output}"
        )

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    confusion = _load_module(
        repo_root / "tools" / "photoreal_identity_negative_confusion_review.py",
        "bodyrig_group_geometry_confusion_dependency",
    )
    ab = _load_module(
        repo_root / "tools" / "photoreal_identity_recognizer_ab_diagnostic.py",
        "bodyrig_group_geometry_ab_dependency",
    )
    flip = _load_module(
        repo_root / "tools" / "photoreal_identity_flip_tta_diagnostic.py",
        "bodyrig_group_geometry_flip_dependency",
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
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "group geometry requires the pinned 512-dimensional identity bank"
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
        raise PhotorealIdentityGroupGeometryDiagnosticError(
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
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "identity bank contains no references"
        )

    current_positives: list[dict[str, Any]] = []
    alternate_positives: list[dict[str, Any]] = []
    review_media: dict[int, dict[str, Any]] = {}
    for index, raw in enumerate(references):
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityGroupGeometryDiagnosticError(
                "identity bank reference is invalid"
            )
        source_key = str(raw.get("source_key") or "").strip()
        source = identity_sources.get(source_key)
        if source is None:
            raise PhotorealIdentityGroupGeometryDiagnosticError(
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
        aligned_crop, current, alternate, quality = (
            confusion._face_crop_and_embeddings(
                ab=ab,
                adapter=adapter,
                runtime=runtime,
                representation=representation,
                alternate_recognizer=alternate_recognizer,
                image=image,
                dimension=dimension,
            )
        )
        stored = ab._normalize(
            raw.get("embedding"),
            dimension=dimension,
            label=f"identity bank embedding[{index}]",
        )
        if ab._cosine(current, stored) < 0.999999:
            raise PhotorealIdentityGroupGeometryDiagnosticError(
                "current recognizer replay does not match persisted bank embedding"
            )
        group_id = str(raw.get("group_id") or "").strip()
        if not group_id:
            raise PhotorealIdentityGroupGeometryDiagnosticError(
                "identity bank reference lacks group id"
            )
        review_media[index] = {
            "frame": image.copy(),
            "aligned": aligned_crop.copy(),
            "viewport_id": _viewport_id,
        }
        base = {
            "reference_index": index,
            "group_id": group_id,
            "source_key": source_key,
            "timestamp_seconds": raw.get("timestamp_seconds"),
            "eye": str(raw.get("eye") or ""),
            "frame_sha256": expected_frame_sha,
            "quality": quality,
        }
        current_positives.append({**base, "embedding": current})
        alternate_positives.append({**base, "embedding": alternate})

    accepted_groups = sorted(attestation.get("accepted_group_ids") or [])
    observed_groups = sorted(
        {str(item["group_id"]) for item in current_positives}
    )
    if observed_groups != accepted_groups:
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "positive geometry groups do not match human attestation"
        )

    current_negatives: list[dict[str, Any]] = []
    alternate_negatives: list[dict[str, Any]] = []
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
            raise PhotorealIdentityGroupGeometryDiagnosticError(
                "persisted negative unexpectedly requires spatial deprojection"
            )
        if adapter._frame_sha(image) != item["frame_sha256"]:
            raise PhotorealIdentityGroupGeometryDiagnosticError(
                "persisted negative frame SHA no longer reproduces"
            )
        _crop, current, alternate, quality = (
            confusion._face_crop_and_embeddings(
                ab=ab,
                adapter=adapter,
                runtime=runtime,
                representation=representation,
                alternate_recognizer=alternate_recognizer,
                image=image,
                dimension=dimension,
            )
        )
        if ab._cosine(current, item["stored_embedding"]) < 0.999999:
            raise PhotorealIdentityGroupGeometryDiagnosticError(
                "current recognizer replay does not match persisted negative embedding"
            )
        base = {
            "negative_index": int(item["index"]),
            "subject_performer_id": str(item["subject_performer_id"]),
            "source_key": item["source_key"],
            "timestamp_seconds": item["timestamp_seconds"],
            "eye": item["eye"],
            "frame_sha256": item["frame_sha256"],
            "quality": quality,
        }
        current_negatives.append({**base, "embedding": current})
        alternate_negatives.append({**base, "embedding": alternate})

    if len(current_positives) != len(references) or len(current_negatives) != len(negatives):
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "current recognizer lost evidence coverage"
        )
    if len(alternate_positives) != len(references) or len(alternate_negatives) != len(negatives):
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "alternate recognizer lost evidence coverage"
        )

    current_geometry = _analyze_variant(
        flip=flip,
        positives=current_positives,
        negatives=current_negatives,
    )
    alternate_geometry = _analyze_variant(
        flip=flip,
        positives=alternate_positives,
        negatives=alternate_negatives,
    )
    comparison = _compare_variants(
        current=current_geometry,
        alternate=alternate_geometry,
    )

    current_ablation = _ablation_search(
        flip=flip,
        positives=current_positives,
        negatives=current_negatives,
        max_removed_groups=3,
    )
    alternate_ablation = _ablation_search(
        flip=flip,
        positives=alternate_positives,
        negatives=alternate_negatives,
        max_removed_groups=3,
    )

    candidate_removed_groups = [
        "scene:805",
        "scene:889",
        "scene:978",
    ]
    current_boundary = _reference_ablation_after_removed_groups(
        flip=flip,
        positives=current_positives,
        negatives=current_negatives,
        removed_group_ids=candidate_removed_groups,
    )
    alternate_boundary = _reference_ablation_after_removed_groups(
        flip=flip,
        positives=alternate_positives,
        negatives=alternate_negatives,
        removed_group_ids=candidate_removed_groups,
    )

    witness_review_root = output.parent / (
        output.stem + "-witness-review"
    )
    witness_review = _write_boundary_witness_review(
        confusion=confusion,
        runtime=runtime,
        output_root=witness_review_root,
        current_boundary=current_boundary,
        alternate_boundary=alternate_boundary,
        current_positives=current_positives,
        alternate_positives=alternate_positives,
        review_media=review_media,
    )

    bodyrig_revision = str(os.environ.get("BODYRIG_REVISION") or "").strip().lower()
    if (
        len(bodyrig_revision) != 40
        or any(character not in "0123456789abcdef" for character in bodyrig_revision)
    ):
        raise PhotorealIdentityGroupGeometryDiagnosticError(
            "BODYRIG_REVISION must bind diagnostic execution to exact Git HEAD"
        )

    result = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "diagnostic_bodyrig_revision": bodyrig_revision,
        "adapter_revision": adapter_revision,
        "identity_bank_sha256": bank_sha,
        "identity_bank_file_sha256": ab._sha256_file(bank_path),
        "identity_request_sha256": ab._sha256_file(
            identity_request_origin_path
        ),
        "identity_request_transport_sha256": ab._sha256_file(
            identity_request_path
        ),
        "calibration_request_sha256": ab._sha256_file(
            calibration_request_origin_path
        ),
        "calibration_request_transport_sha256": ab._sha256_file(
            calibration_request_path
        ),
        "negative_observations_sha256": ab._sha256_file(
            negative_observations_path
        ),
        "identity_group_attestation_sha256": ab._sha256_file(
            review_root / "identity-group-attestation.json"
        ),
        "positive_reference_count": len(references),
        "human_attested_group_count": len(accepted_groups),
        "negative_observation_count": len(negatives),
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
        "variants": {
            "w600k-r50": current_geometry,
            "antelopev2-glintr100": alternate_geometry,
        },
        "group_comparison": comparison,
        "counterfactual_group_ablation": {
            "w600k-r50": current_ablation,
            "antelopev2-glintr100": alternate_ablation,
        },
        "candidate_boundary_witness": {
            "removed_group_ids": candidate_removed_groups,
            "w600k-r50": current_boundary,
            "antelopev2-glintr100": alternate_boundary,
        },
        "boundary_witness_review": witness_review,
        "diagnostic_only": True,
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
                "group_comparison": comparison,
                "weakest_current_pair": (
                    current_geometry["pairwise_positive_group_cosines"][0]
                ),
                "weakest_alternate_pair": (
                    alternate_geometry["pairwise_positive_group_cosines"][0]
                ),
                "ablation_summary": {
                    "w600k-r50": {
                        "combination_count": current_ablation["combination_count"],
                        "best_remove_1": current_ablation["by_removed_count"]["1"][0],
                        "best_remove_2": current_ablation["by_removed_count"]["2"][0],
                        "best_remove_3": current_ablation["by_removed_count"]["3"][0],
                        "first_all_models_pass": current_ablation["first_all_models_pass"],
                        "candidate_scene_805_889_978": current_ablation[
                            "candidate_scene_805_889_978"
                        ],
                    },
                    "antelopev2-glintr100": {
                        "combination_count": alternate_ablation["combination_count"],
                        "best_remove_1": alternate_ablation["by_removed_count"]["1"][0],
                        "best_remove_2": alternate_ablation["by_removed_count"]["2"][0],
                        "best_remove_3": alternate_ablation["by_removed_count"]["3"][0],
                        "first_all_models_pass": alternate_ablation["first_all_models_pass"],
                        "candidate_scene_805_889_978": alternate_ablation[
                            "candidate_scene_805_889_978"
                        ],
                    },
                },
                "candidate_boundary_witness": {
                    "removed_group_ids": candidate_removed_groups,
                    "w600k-r50": {
                        "baseline_witnesses": current_boundary["baseline_witnesses"],
                        "best_single_reference_ablation": current_boundary[
                            "best_single_reference_ablation"
                        ],
                        "first_all_models_pass": current_boundary[
                            "first_all_models_pass"
                        ],
                    },
                    "antelopev2-glintr100": {
                        "baseline_witnesses": alternate_boundary["baseline_witnesses"],
                        "best_single_reference_ablation": alternate_boundary[
                            "best_single_reference_ablation"
                        ],
                        "first_all_models_pass": alternate_boundary[
                            "first_all_models_pass"
                        ],
                    },
                },
                "boundary_witness_review": witness_review,
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

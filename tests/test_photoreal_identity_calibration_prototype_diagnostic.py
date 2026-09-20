from __future__ import annotations

from bodyrig.photoreal_identity_calibration_prototype_diagnostic import analyze


def _vec(primary: int, secondary: float = 0.0, dimension: int = 32) -> list[float]:
    value = [0.0] * dimension
    value[primary] = 1.0
    value[(primary + 1) % dimension] = secondary
    return value


def _bank() -> dict[str, object]:
    refs = []
    frame = 1
    for group_id, values in (
        ("scene:a", [_vec(0, 0.01), _vec(0, 0.02)]),
        ("scene:b", [_vec(0, 0.03), _vec(0, 0.04)]),
    ):
        for index, embedding in enumerate(values):
            refs.append(
                {
                    "source_key": f"{group_id}:E:/x.mp4",
                    "source_sha256": ("a" if group_id == "scene:a" else "b") * 64,
                    "group_id": group_id,
                    "timestamp_seconds": float(index + 1),
                    "eye": "mono",
                    "frame_sha256": format(frame, "x") * 64,
                    "embedding": embedding,
                }
            )
            frame += 1
    from bodyrig.photoreal_identity_bank import _normalized_mean, _canonical_bank_digest
    centroid = _normalized_mean([row["embedding"] for row in refs])
    bank = {
        "format": "bodyrig-photoreal-identity-bank",
        "version": 1,
        "performer_id": "42",
        "extractor": "identity-test",
        "extractor_revision": "r1",
        "model_set_sha256": "c" * 64,
        "embedding_dimension": 32,
        "reference_count": 4,
        "source_group_count": 2,
        "references": refs,
        "centroid_embedding": centroid,
        "train_only": True,
        "evaluation_reference_count": 0,
        "match_threshold_calibrated": False,
        "identity_matching_authorized": False,
        "identity_bank_ready_for_calibration": True,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    bank["identity_bank_sha256"] = _canonical_bank_digest(bank)
    return bank


def _plan(bank: dict[str, object]) -> dict[str, object]:
    sources = []
    for index, performer in enumerate(("7", "8")):
        sources.append(
            {
                "source_key": f"scene:n{index}:E:/n{index}.mp4",
                "source_sha256": str(index + 7) * 64,
                "subject_performer_id": performer,
                "target_performer_absent": True,
                "samples": [
                    {"timestamp_seconds": float(sample + 1), "eye": "mono"}
                    for sample in range(4)
                ],
            }
        )
    return {
        "format": "bodyrig-photoreal-identity-calibration-plan",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": bank["identity_bank_sha256"],
        "model_set_sha256": bank["model_set_sha256"],
        "extractor": bank["extractor"],
        "extractor_revision": bank["extractor_revision"],
        "embedding_dimension": 32,
        "sources": sources,
        "calibration_only": True,
        "negative_embedding_extraction_required": True,
        "teacher_training_authorized": False,
        "identity_matching_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _negatives(bank: dict[str, object], plan: dict[str, object]) -> dict[str, object]:
    observations = []
    frame = 10
    for source_index, source in enumerate(plan["sources"]):
        for sample in source["samples"]:
            observations.append(
                {
                    "source_key": source["source_key"],
                    "source_sha256": source["source_sha256"],
                    "subject_performer_id": source["subject_performer_id"],
                    "timestamp_seconds": sample["timestamp_seconds"],
                    "eye": "mono",
                    "frame_sha256": format(frame, "x")[-1] * 64,
                    "embedding": _vec(5 + source_index, 0.01),
                }
            )
            frame += 1
    return {
        "format": "bodyrig-photoreal-identity-negative-observations",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": bank["identity_bank_sha256"],
        "extractor": bank["extractor"],
        "extractor_revision": bank["extractor_revision"],
        "model_set_sha256": bank["model_set_sha256"],
        "embedding_dimension": 32,
        "observations": observations,
        "calibration_only": True,
        "build_only": True,
        "production_activation": False,
    }


def _attestation(bank: dict[str, object]) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-group-attestation",
        "version": 1,
        "identity_bank_sha256": bank["identity_bank_sha256"],
        "accepted_group_ids": ["scene:a", "scene:b"],
        "rejected_group_ids": [],
        "human_identity_attested": True,
        "identity_group_selection_authority": True,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def test_prototype_diagnostic_compares_three_scoring_models_without_authority() -> None:
    bank = _bank()
    plan = _plan(bank)
    result = analyze(
        bank=bank,
        plan=plan,
        negative_observations=_negatives(bank, plan),
        attestation=_attestation(bank),
    )

    assert set(result["variants"]) == {
        "current-reference-weighted",
        "group-balanced-centroid-lgo",
        "nearest-group-prototype",
    }
    assert result["positive_reference_count"] == 4
    assert result["positive_group_count"] == 2
    assert result["negative_observation_count"] == 8
    assert result["negative_performer_count"] == 2
    assert result["identity_matching_authorized"] is False
    assert result["teacher_training_authorized"] is False
    assert result["production_activation"] is False
    assert all(
        "observed_separation_margin" in variant
        for variant in result["variants"].values()
    )


def test_prototype_diagnostic_reports_group_neighbors() -> None:
    bank = _bank()
    plan = _plan(bank)
    result = analyze(
        bank=bank,
        plan=plan,
        negative_observations=_negatives(bank, plan),
        attestation=_attestation(bank),
    )

    assert len(result["groups_weakest_first"]) == 2
    assert {
        item["nearest_other_group_id"]
        for item in result["groups_weakest_first"]
    } == {"scene:a", "scene:b"}

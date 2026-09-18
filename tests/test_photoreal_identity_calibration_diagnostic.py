from __future__ import annotations

import pytest

import bodyrig.photoreal_identity_calibration_diagnostic as diagnostic


def _vec(primary: int, secondary: float = 0.0) -> list[float]:
    value = [0.0] * 32
    value[primary] = 1.0
    value[(primary + 1) % 32] = secondary
    return value


def _bank() -> dict[str, object]:
    return {
        "performer_id": "42",
        "identity_bank_sha256": "d" * 64,
        "embedding_dimension": 32,
        "centroid_embedding": _vec(0, 0.02),
        "references": [
            {
                "group_id": "a",
                "source_key": "a",
                "timestamp_seconds": 1.0,
                "eye": "mono",
                "frame_sha256": "1" * 64,
                "embedding": _vec(0, 0.01),
            },
            {
                "group_id": "a",
                "source_key": "a",
                "timestamp_seconds": 2.0,
                "eye": "mono",
                "frame_sha256": "2" * 64,
                "embedding": _vec(0, 0.02),
            },
            {
                "group_id": "b",
                "source_key": "b",
                "timestamp_seconds": 3.0,
                "eye": "mono",
                "frame_sha256": "3" * 64,
                "embedding": _vec(0, 0.015),
            },
            {
                "group_id": "b",
                "source_key": "b",
                "timestamp_seconds": 4.0,
                "eye": "mono",
                "frame_sha256": "4" * 64,
                "embedding": _vec(0, 0.025),
            },
        ],
    }


def _plan() -> dict[str, object]:
    return {
        "sources": [
            {
                "source_key": "n7",
                "subject_performer_id": "7",
                "subject_performer_name": "P7",
                "resolved_path": r"C:\negative\p7.mp4",
                "sample_count": 2,
                "samples": [{}, {}],
            },
            {
                "source_key": "n8",
                "subject_performer_id": "8",
                "subject_performer_name": "P8",
                "resolved_path": r"C:\negative\p8.mp4",
                "sample_count": 2,
                "samples": [{}, {}],
            },
            {
                "source_key": "n9",
                "subject_performer_id": "9",
                "subject_performer_name": "P9",
                "resolved_path": r"C:\negative\p9.mp4",
                "sample_count": 2,
                "samples": [{}, {}],
            },
        ]
    }


def _observations() -> dict[str, object]:
    return {
        "observations": [
            {
                "source_key": "n7",
                "subject_performer_id": "7",
                "timestamp_seconds": 10.0,
                "eye": "mono",
                "frame_sha256": "7" * 64,
                "embedding": _vec(0, 0.10),
            },
            {
                "source_key": "n8",
                "subject_performer_id": "8",
                "timestamp_seconds": 20.0,
                "eye": "mono",
                "frame_sha256": "8" * 64,
                "embedding": _vec(5, 0.10),
            },
        ]
    }


def _fake_core(bank, plan, observations):
    dimension = int(bank["embedding_dimension"])
    target = diagnostic._embedding(
        bank["centroid_embedding"],
        dimension=dimension,
        label="target",
    )

    positive_scores = []
    for reference in bank["references"]:
        others = [
            diagnostic._embedding(
                other["embedding"],
                dimension=dimension,
                label="other",
            )
            for other in bank["references"]
            if other["group_id"] != reference["group_id"]
        ]
        positive_scores.append(
            diagnostic._cosine(
                diagnostic._embedding(
                    reference["embedding"],
                    dimension=dimension,
                    label="ref",
                ),
                diagnostic._centroid(others),
            )
        )

    negative_scores = [
        diagnostic._cosine(
            diagnostic._embedding(
                observation["embedding"],
                dimension=dimension,
                label="negative",
            ),
            target,
        )
        for observation in observations["observations"]
    ]

    return {
        "observed_separation_margin":
            round(min(positive_scores) - max(negative_scores), 9),
        "identity_matching_authorized": False,
        "calibration_blockers": ["blocked"],
    }


def test_diagnostic_identifies_highest_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostic,
        "build_identity_calibration",
        _fake_core,
    )

    result = diagnostic.build_identity_calibration_diagnostic(
        _bank(),
        _plan(),
        _observations(),
    )

    assert result["diagnostic_only"] is True
    assert result["identity_matching_authority"] is False
    assert result["production_activation"] is False
    assert (
        result["highest_negative_match"]["subject_performer_id"]
        == "7"
    )
    assert (
        result["stage13_observed_separation_margin"]
        == result["observed_separation_margin"]
    )
    assert result["violating_negative_observation_count"] == 1
    assert result["violating_negative_performer_count"] == 1
    assert result["violating_negative_source_count"] == 1
    assert result["violating_negative_observation_fraction"] == 0.5
    assert len(result["negative_source_summaries"]) == 2
    assert (
        result["negative_source_summaries"][0]["source_key"]
        == "n7"
    )
    assert (
        result["negative_source_summaries"][0]
        ["violating_observation_count"]
        == 1
    )
    assert result["positive_cosine_max"] >= result["positive_floor"]
    assert result["positive_group_count"] == 2
    assert result["positive_cross_group_pair_count"] == 1
    assert len(result["positive_group_summaries"]) == 2
    assert len(result["positive_cross_group_pairs"]) == 1
    assert (
        result["positive_cross_group_centroid_cosine_min"]
        == result["positive_cross_group_centroid_cosine_median"]
        == result["positive_cross_group_centroid_cosine_max"]
    )
    assert (
        result["positive_reference_to_target_cosine_max"]
        >= result["positive_reference_to_target_cosine_median"]
        >= result["positive_reference_to_target_cosine_min"]
    )
    assert (
        result["negative_ceiling"]
        >= result["negative_cosine_median"]
        >= result["negative_cosine_min"]
    )
    assert result["planned_negative_observation_count"] == 6
    assert result["negative_observation_count"] == 2
    assert result["negative_extraction_yield_fraction"] == 0.333333333
    assert result["planned_negative_source_count"] == 3
    assert result["observed_negative_source_count"] == 2
    assert result["planned_negative_performer_count"] == 3
    assert (
        result["weakest_positive_group"]["group_id"]
        in {"a", "b"}
    )

    source_yields = {
        item["source_key"]: item
        for item in result["negative_source_yield_summaries"]
    }
    assert source_yields["n7"]["extraction_yield_fraction"] == 0.5
    assert source_yields["n8"]["extraction_yield_fraction"] == 0.5
    assert source_yields["n9"]["observation_count"] == 0
    assert source_yields["n9"]["extraction_yield_fraction"] == 0.0

    for performer_summary in result["negative_performer_summaries"]:
        assert "resolved_path" not in performer_summary

    performer_yields = {
        item["subject_performer_id"]: item
        for item in result["negative_performer_yield_summaries"]
    }
    assert performer_yields["9"]["observation_count"] == 0
    assert performer_yields["9"]["extraction_yield_fraction"] == 0.0

    assert (
        result["lowest_yield_negative_source"]["source_key"]
        == "n9"
    )
    assert (
        result["lowest_yield_negative_performer"]
        ["subject_performer_id"]
        == "9"
    )
    assert (
        result["highest_collision_negative_source"]["source_key"]
        == "n7"
    )
    assert (
        result["highest_collision_negative_source"]["resolved_path"]
        == r"C:\negative\p7.mp4"
    )
    assert (
        result["highest_negative_match"]["resolved_path"]
        == r"C:\negative\p7.mp4"
    )
    assert (
        result["highest_collision_negative_performer"]
        ["subject_performer_id"]
        == "7"
    )


def test_diagnostic_rejects_stage13_math_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostic,
        "build_identity_calibration",
        lambda *_args: {
            "observed_separation_margin": 0.5,
            "identity_matching_authorized": False,
            "calibration_blockers": ["blocked"],
        },
    )

    with pytest.raises(
        diagnostic.PhotorealIdentityCalibrationDiagnosticError,
        match="does not reproduce Stage-13",
    ):
        diagnostic.build_identity_calibration_diagnostic(
            _bank(),
            _plan(),
            _observations(),
        )


def test_diagnostic_rejects_invalid_top_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostic,
        "build_identity_calibration",
        _fake_core,
    )

    with pytest.raises(
        diagnostic.PhotorealIdentityCalibrationDiagnosticError,
        match="top_matches",
    ):
        diagnostic.build_identity_calibration_diagnostic(
            _bank(),
            _plan(),
            _observations(),
            top_matches=0,
        )

def test_diagnostic_wraps_stage13_input_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args):
        raise diagnostic.PhotorealIdentityCalibrationError(
            "bad calibration input"
        )

    monkeypatch.setattr(
        diagnostic,
        "build_identity_calibration",
        fail,
    )

    with pytest.raises(
        diagnostic.PhotorealIdentityCalibrationDiagnosticError,
        match="Stage-13 calibration input is invalid",
    ):
        diagnostic.build_identity_calibration_diagnostic(
            _bank(),
            _plan(),
            _observations(),
        )

def test_diagnostic_groups_multiple_observations_by_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostic,
        "build_identity_calibration",
        _fake_core,
    )

    observations = _observations()
    observations["observations"].append(
        {
            "source_key": "n7",
            "subject_performer_id": "7",
            "timestamp_seconds": 30.0,
            "eye": "mono",
            "frame_sha256": "9" * 64,
            "embedding": _vec(5, 0.05),
        }
    )

    result = diagnostic.build_identity_calibration_diagnostic(
        _bank(),
        _plan(),
        observations,
    )

    n7 = next(
        item
        for item in result["negative_source_summaries"]
        if item["source_key"] == "n7"
    )
    assert n7["observation_count"] == 2
    assert n7["violating_observation_count"] == 1
    assert n7["subject_performer_id"] == "7"
    assert n7["resolved_path"] == r"C:\negative\p7.mp4"

    n7_yield = next(
        item
        for item in result["negative_source_yield_summaries"]
        if item["source_key"] == "n7"
    )
    assert n7_yield["resolved_path"] == r"C:\negative\p7.mp4"
    assert n7_yield["planned_sample_count"] == 2
    assert n7_yield["observation_count"] == 2
    assert n7_yield["extraction_yield_fraction"] == 1.0

def test_diagnostic_rejects_invalid_planned_sample_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostic,
        "build_identity_calibration",
        _fake_core,
    )

    plan = _plan()
    plan["sources"][0]["sample_count"] = 0
    plan["sources"][0]["samples"] = []

    with pytest.raises(
        diagnostic.PhotorealIdentityCalibrationDiagnosticError,
        match="sample_count is invalid",
    ):
        diagnostic.build_identity_calibration_diagnostic(
            _bank(),
            plan,
            _observations(),
        )

def test_diagnostic_reports_positive_group_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostic,
        "build_identity_calibration",
        _fake_core,
    )

    result = diagnostic.build_identity_calibration_diagnostic(
        _bank(),
        _plan(),
        _observations(),
    )

    groups = {
        item["group_id"]: item
        for item in result["positive_group_summaries"]
    }

    assert set(groups) == {"a", "b"}
    assert groups["a"]["reference_count"] == 2
    assert groups["b"]["reference_count"] == 2
    assert groups["a"]["source_count"] == 1
    assert groups["b"]["source_count"] == 1
    assert groups["a"]["within_group_pairwise_cosine_min"] is not None
    assert groups["b"]["within_group_pairwise_cosine_min"] is not None

    pair = result["positive_cross_group_pairs"][0]
    assert {pair["left_group_id"], pair["right_group_id"]} == {"a", "b"}
    assert -1.0 <= pair["centroid_cosine"] <= 1.0


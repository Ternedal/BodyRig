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
                "subject_performer_name": "P7",
            },
            {
                "source_key": "n8",
                "subject_performer_name": "P8",
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

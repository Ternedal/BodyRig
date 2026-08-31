from __future__ import annotations

import pytest

from bodyrig.bridges.opencv_fidelity_evaluator import (
    head_shoulder_plausibility,
    human_plausibility_score,
    skin_liveliness_similarity,
)


def test_head_shoulder_plausibility_accepts_broad_human_range() -> None:
    score, ratio = head_shoulder_plausibility([
        0.34,
        0.38,
        0.72,
        0.76,
        0.64,
        0.62,
        0.55,
        0.42,
        0.28,
    ])
    assert ratio == pytest.approx((0.34 + 0.38) / (0.72 + 0.76))
    assert score == pytest.approx(1.0)


def test_extreme_head_to_shoulder_ratio_is_penalized() -> None:
    score, ratio = head_shoulder_plausibility([
        0.82,
        0.84,
        0.70,
        0.72,
        0.62,
        0.60,
        0.52,
        0.40,
        0.26,
    ])
    assert ratio > 1.0
    assert score < 0.2


def test_missing_detectable_face_cannot_clear_default_plausibility_threshold() -> None:
    score = human_plausibility_score(
        face_detected=False,
        bilateral_balance=1.0,
        head_shoulder=1.0,
        liveliness=1.0,
    )
    assert score < 0.82


def test_one_severe_plausibility_defect_caps_the_combined_score() -> None:
    score = human_plausibility_score(
        face_detected=True,
        bilateral_balance=0.95,
        head_shoulder=0.95,
        liveliness=0.20,
    )
    assert score < 0.82


def test_balanced_plausible_render_can_clear_threshold() -> None:
    score = human_plausibility_score(
        face_detected=True,
        bilateral_balance=0.91,
        head_shoulder=0.95,
        liveliness=0.88,
    )
    assert score >= 0.82


def test_skin_liveliness_is_reference_relative_not_absolute_skin_tone() -> None:
    references = [(0.42, 0.68), (0.46, 0.72), (0.44, 0.70)]
    assert skin_liveliness_similarity(references, (0.44, 0.70)) > 0.95
    assert skin_liveliness_similarity(references, (0.02, 0.25)) < 0.25

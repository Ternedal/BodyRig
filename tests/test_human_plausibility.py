from __future__ import annotations

import pytest

from bodyrig.bridges.opencv_fidelity_evaluator import (
    facial_definition_similarity,
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


def test_low_facial_definition_cannot_be_hidden_by_other_good_plausibility_components() -> None:
    score = human_plausibility_score(
        face_detected=True,
        bilateral_balance=0.97,
        head_shoulder=0.97,
        liveliness=0.95,
        facial_definition=0.40,
    )
    assert score < 0.82


def test_balanced_plausible_render_can_clear_threshold() -> None:
    score = human_plausibility_score(
        face_detected=True,
        bilateral_balance=0.91,
        head_shoulder=0.95,
        liveliness=0.88,
        facial_definition=0.90,
    )
    assert score >= 0.82


def test_skin_liveliness_is_reference_relative_not_absolute_skin_tone() -> None:
    references = [(0.42, 0.68), (0.46, 0.72), (0.44, 0.70)]
    assert skin_liveliness_similarity(references, (0.44, 0.70)) > 0.95
    assert skin_liveliness_similarity(references, (0.02, 0.25)) < 0.25


def _definition(detail: float, local: float, eyes: float, midface: float) -> dict[str, float]:
    return {
        "detail": detail,
        "local_contrast": local,
        "eye_edge_density": eyes,
        "midface_edge_density": midface,
    }


def test_reference_like_facial_definition_scores_high() -> None:
    references = [
        _definition(5.4, 0.31, 0.18, 0.20),
        _definition(5.1, 0.29, 0.17, 0.19),
        _definition(4.8, 0.27, 0.16, 0.18),
    ]
    candidate = _definition(5.15, 0.30, 0.175, 0.19)
    assert facial_definition_similarity(references, candidate) > 0.85


def test_smooth_ultrasound_like_face_is_strongly_penalized() -> None:
    references = [
        _definition(5.4, 0.31, 0.18, 0.20),
        _definition(5.1, 0.29, 0.17, 0.19),
        _definition(4.8, 0.27, 0.16, 0.18),
    ]
    smooth_candidate = _definition(2.8, 0.11, 0.055, 0.06)
    assert facial_definition_similarity(references, smooth_candidate) < 0.60


def test_extreme_over_sharpening_does_not_game_definition_score() -> None:
    references = [
        _definition(5.4, 0.31, 0.18, 0.20),
        _definition(5.1, 0.29, 0.17, 0.19),
        _definition(4.8, 0.27, 0.16, 0.18),
    ]
    noisy_candidate = _definition(9.5, 0.80, 0.48, 0.52)
    assert facial_definition_similarity(references, noisy_candidate) < 0.70


def test_blurred_reference_does_not_make_blurred_candidate_acceptable() -> None:
    references = [
        _definition(5.5, 0.32, 0.19, 0.21),
        _definition(5.2, 0.30, 0.18, 0.20),
        _definition(5.0, 0.29, 0.17, 0.19),
        _definition(2.4, 0.10, 0.05, 0.05),
    ]
    blurred_candidate = _definition(2.5, 0.105, 0.052, 0.052)
    assert facial_definition_similarity(references, blurred_candidate) < 0.60

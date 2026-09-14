from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.face_secondary_hair_eye_comparison as comparison
import bodyrig.face_secondary_hair_eye_review as review


@pytest.mark.parametrize("module", [review, comparison])
def test_v1_predicate_accepts_numeric_one_but_rejects_bool_and_coercive_values(module) -> None:
    assert module._is_v1(1) is True
    assert module._is_v1(1.0) is True
    for bad in (True, False, "1", None, 2):
        assert module._is_v1(bad) is False


def test_all_active_v1_readers_use_bool_safe_predicate() -> None:
    review_source = Path(review.__file__).read_text(encoding="utf-8")
    comparison_source = Path(comparison.__file__).read_text(encoding="utf-8")

    assert 'value.get("format") != SOURCE_FORMAT or not _is_v1(value.get("version"))' in review_source
    assert 'or not _is_v1(eye_metadata.get("version"))' in review_source
    assert 'value.get("format") != FORMAT or not _is_v1(value.get("version"))' in review_source
    assert 'embedded.get("format") != REVIEW_METADATA_FORMAT' in review_source
    assert 'or not _is_v1(embedded.get("version"))' in review_source
    assert 'value.get("format") != FORMAT or not _is_v1(value.get("version"))' in comparison_source


def test_review_only_authority_boundaries_remain_explicit() -> None:
    review_source = Path(review.__file__).read_text(encoding="utf-8")
    comparison_source = Path(comparison.__file__).read_text(encoding="utf-8")

    for marker in (
        '"comparisonOnly": True',
        '"humanReviewRequired": True',
        '"faceSecondaryComponentAuthority": False',
        '"packageMutationPerformed": False',
        '"productionActivation": False',
    ):
        assert marker in review_source
    for marker in (
        '"comparisonOnly": True',
        '"physicalAcceptanceAuthority": False',
        '"humanReviewRequired": True',
        '"packagePromotionAuthority": False',
        '"productionActivation": False',
    ):
        assert marker in comparison_source

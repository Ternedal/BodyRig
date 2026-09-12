from __future__ import annotations

import pytest

from bodyrig.hands_feet_nails_source_capture import (
    HandsFeetNailsSourceCaptureError,
    _normalized_crop,
)
from bodyrig.wardrobe_source_capture import WardrobeSourceCaptureError, _crop


def test_hands_feet_nails_crop_rejects_huge_integer_with_domain_error() -> None:
    with pytest.raises(HandsFeetNailsSourceCaptureError, match="non-numeric"):
        _normalized_crop([0.0, 0.0, 10**400, 0.5], region="left_hand")


def test_hands_feet_nails_crop_rejects_boolean_component() -> None:
    with pytest.raises(HandsFeetNailsSourceCaptureError, match="non-numeric"):
        _normalized_crop([0.0, 0.0, True, 0.5], region="left_hand")


def test_wardrobe_crop_rejects_huge_integer_with_domain_error() -> None:
    with pytest.raises(WardrobeSourceCaptureError, match="non-numeric"):
        _crop([0.0, 0.0, 10**400, 0.5], view="front")


def test_wardrobe_crop_rejects_boolean_component() -> None:
    with pytest.raises(WardrobeSourceCaptureError, match="non-numeric"):
        _crop([0.0, 0.0, True, 0.5], view="front")


def test_source_capture_crops_still_accept_numeric_unit_frame() -> None:
    assert _normalized_crop([0, 0, 1, 1], region="left_hand") == [0.0, 0.0, 1.0, 1.0]
    assert _crop([0, 0, 1, 1], view="front") == [0.0, 0.0, 1.0, 1.0]

from __future__ import annotations

import pytest

from bodyrig.photoreal_appearance_epoch_review_recorder import (
    PhotorealAppearanceEpochReviewRecorderError,
    _sha,
    _text,
)


@pytest.mark.parametrize("value", [True, False, 42, 1.0, ["scene:a"], {"id": "scene:a"}])
def test_review_recorder_text_boundary_rejects_non_strings(value: object) -> None:
    with pytest.raises(PhotorealAppearanceEpochReviewRecorderError, match="is invalid"):
        _text(value, label="authority text")


def test_review_recorder_text_boundary_preserves_real_string() -> None:
    assert _text("  scene:train-a  ", label="authority text") == "scene:train-a"


@pytest.mark.parametrize(
    "value",
    [
        int("1" * 64),
        True,
        False,
        1.0,
        ["a" * 64],
        {"sha": "a" * 64},
    ],
)
def test_review_recorder_sha_boundary_rejects_non_strings(value: object) -> None:
    with pytest.raises(PhotorealAppearanceEpochReviewRecorderError, match="is invalid"):
        _sha(value, label="authority SHA-256")


def test_review_recorder_sha_boundary_accepts_normalized_hex_string() -> None:
    assert _sha("  " + "A" * 64 + "  ", label="authority SHA-256") == "a" * 64

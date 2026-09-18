from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.photoreal_appearance_epoch_handoff as module
from bodyrig.photoreal_appearance_epoch_handoff import (
    PhotorealAppearanceEpochHandoffError,
    _optional_text,
    _sha,
    _text,
    build_appearance_epoch_review_handoff_files,
)


@pytest.mark.parametrize("value", [True, False, 42, 1.0, ["scene:a"], {"id": "scene:a"}])
def test_handoff_text_boundary_rejects_non_strings(value: object) -> None:
    with pytest.raises(PhotorealAppearanceEpochHandoffError, match="is invalid"):
        _text(value, label="authority text")


def test_handoff_text_boundary_preserves_real_string() -> None:
    assert _text("  scene:train-a  ", label="authority text") == "scene:train-a"


@pytest.mark.parametrize("value", [True, 42, 1.0, ["Performer 42"], {"name": "Performer 42"}])
def test_handoff_optional_text_boundary_rejects_non_strings(value: object) -> None:
    with pytest.raises(PhotorealAppearanceEpochHandoffError, match="is invalid"):
        _optional_text(value, label="performer name")


def test_handoff_optional_text_boundary_allows_none_as_empty() -> None:
    assert _optional_text(None, label="performer name") == ""


@pytest.mark.parametrize(
    "value",
    [int("1" * 64), True, False, 1.0, ["a" * 64], {"sha": "a" * 64}],
)
def test_handoff_sha_boundary_rejects_non_strings(value: object) -> None:
    with pytest.raises(PhotorealAppearanceEpochHandoffError, match="is invalid"):
        _sha(value, label="authority SHA-256")


def test_handoff_sha_boundary_accepts_normalized_hex_string() -> None:
    assert _sha("  " + "A" * 64 + "  ", label="authority SHA-256") == "a" * 64


def test_handoff_file_builder_wraps_output_parent_creation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "_read_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        module,
        "build_appearance_epoch_review_handoff",
        lambda *args, **kwargs: ({"format": "handoff"}, {"format": "review"}),
    )

    original_exists = Path.exists

    def fake_exists(self: Path) -> bool:
        if self.name in {"handoff.json", "review.json"}:
            return False
        return original_exists(self)

    def fail_mkdir(self: Path, *args, **kwargs) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    with pytest.raises(PhotorealAppearanceEpochHandoffError, match="failed to persist appearance epoch review handoff"):
        build_appearance_epoch_review_handoff_files(
            tmp_path / "plan.json",
            tmp_path / "blocked" / "handoff.json",
            tmp_path / "blocked" / "review.json",
        )

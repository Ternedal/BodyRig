from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.photoreal_appearance_epoch_review_recorder as module
from bodyrig.photoreal_appearance_epoch_review_recorder import (
    PhotorealAppearanceEpochReviewRecorderError,
    build_human_review_record_file,
)


def test_review_record_file_wraps_output_parent_creation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "_read_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        module,
        "build_human_review_record",
        lambda *args, **kwargs: {
            "format": "bodyrig-photoreal-appearance-epoch-review",
            "version": 1,
            "performer_id": "42",
            "appearance_epoch_plan_sha256": "a" * 64,
            "selected_epoch_id": "epoch-a",
            "selected_source_group_ids": ["scene:train-a", "scene:eval-a"],
            "human_review_complete": True,
            "human_approved": True,
            "reviewed_by": "operator",
            "review_notes": "Reviewed.",
            "production_activation": False,
        },
    )

    def fail_mkdir(self: Path, *args, **kwargs) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    with pytest.raises(PhotorealAppearanceEpochReviewRecorderError, match="failed to persist human review record"):
        build_human_review_record_file(
            tmp_path / "plan.json",
            tmp_path / "handoff.json",
            tmp_path / "blocked" / "human-review.json",
            selected_epoch_id="epoch-a",
            selected_source_group_ids=["scene:train-a", "scene:eval-a"],
            reviewed_by="operator",
            review_notes="Reviewed.",
            approve_human_review=True,
        )

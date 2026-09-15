from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.photoreal_teacher_input_p0_root as module
from bodyrig.photoreal_teacher_input_p0_root import (
    PhotorealTeacherInputP0RootError,
    build_teacher_input_from_p0_root,
)


def _write_authorized_p0_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "p0"
    root.mkdir()
    plan = root / "dataset-plan.json"
    receipt = root / "source-receipt.json"
    frame_index = root / "frame-index.json"
    for path in (plan, receipt, frame_index):
        path.write_text("{}\n", encoding="utf-8")

    (root / "p0-status.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-photoreal-p0-status",
                "version": 1,
                "bodyrig_revision": "a" * 40,
                "performer_id": "42",
                "status": "teacher-training-authorized",
                "teacher_training_authorized": True,
                "blockers": [],
                "human_visual_acceptance_required": True,
                "photoreal_acceptance_authority": False,
                "production_activation": False,
                "outputs": {
                    "dataset_plan": str(plan.resolve()),
                    "source_receipt": str(receipt.resolve()),
                    "frame_index": str(frame_index.resolve()),
                },
            }
        ),
        encoding="utf-8",
    )

    selection = tmp_path / "epoch-selection.json"
    selection.write_text(
        json.dumps(
            {
                "format": "bodyrig-photoreal-appearance-epoch-selection",
                "version": 1,
                "performer_id": "42",
                "teacher_input_authorized": True,
                "teacher_training_authorized": True,
                "photoreal_acceptance_authority": False,
                "human_visual_acceptance_required": True,
                "build_only": True,
                "runtime_dependency": False,
                "production_activation": False,
            }
        ),
        encoding="utf-8",
    )
    return root, selection


def test_p0_root_wraps_teacher_output_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, selection = _write_authorized_p0_root(tmp_path)

    def fail_builder(*args, **kwargs):
        raise OSError("output filesystem unavailable")

    monkeypatch.setattr(module, "build_teacher_input_files_strict", fail_builder)
    with pytest.raises(PhotorealTeacherInputP0RootError, match="strict teacher input gate rejected P0 root"):
        build_teacher_input_from_p0_root(root, selection, tmp_path / "teacher-input.json")

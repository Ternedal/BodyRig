from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.photoreal_teacher_input_p0_root import (
    PhotorealTeacherInputP0RootError,
    resolve_authorized_p0_teacher_inputs,
)


def _write_authorized_p0_root(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "p0"
    root.mkdir()
    plan = root / "dataset-plan.json"
    receipt = root / "source-receipt.json"
    frame_index = root / "frame-index.json"
    for path in (plan, receipt, frame_index):
        path.write_text("{}\n", encoding="utf-8")

    status = {
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
    (root / "p0-status.json").write_text(json.dumps(status), encoding="utf-8")

    selection = {
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
    selection_path = tmp_path / "epoch-selection.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    return root, selection_path, plan


def test_p0_root_rejects_symlinked_canonical_file_escape(tmp_path: Path) -> None:
    root, selection, plan = _write_authorized_p0_root(tmp_path)
    outside = tmp_path / "outside-plan.json"
    outside.write_text("{}\n", encoding="utf-8")
    plan.unlink()
    try:
        plan.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable on this runner: {exc}")

    with pytest.raises(PhotorealTeacherInputP0RootError, match="may not be a symlink"):
        resolve_authorized_p0_teacher_inputs(root, selection)

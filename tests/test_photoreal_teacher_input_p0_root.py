from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.photoreal_teacher_input_p0_root as module
from bodyrig.photoreal_teacher_input import PhotorealTeacherInputError
from bodyrig.photoreal_teacher_input_p0_root import (
    PhotorealTeacherInputP0RootError,
    build_teacher_input_from_p0_root,
    resolve_authorized_p0_teacher_inputs,
)


def _write_p0_root(tmp_path: Path) -> tuple[Path, Path]:
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
    return root, selection_path


def _rewrite(path: Path, mutate) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_authorized_p0_root_resolves_canonical_teacher_inputs(tmp_path: Path) -> None:
    root, selection = _write_p0_root(tmp_path)
    plan, receipt, frame_index, resolved_selection = resolve_authorized_p0_teacher_inputs(root, selection)

    assert plan == (root / "dataset-plan.json").resolve()
    assert receipt == (root / "source-receipt.json").resolve()
    assert frame_index == (root / "frame-index.json").resolve()
    assert resolved_selection == selection.resolve()


def test_build_from_p0_root_delegates_to_strict_teacher_builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, selection = _write_p0_root(tmp_path)
    output = tmp_path / "teacher-input.json"
    observed: dict[str, object] = {}

    def fake_builder(plan, receipt, frame_index, epoch_selection, out):
        observed.update(
            {
                "plan": Path(plan),
                "receipt": Path(receipt),
                "frame_index": Path(frame_index),
                "selection": Path(epoch_selection),
                "out": Path(out),
            }
        )
        return {
            "format": "bodyrig-photoreal-teacher-input",
            "version": 1,
            "performer_id": "42",
            "selected_epoch_id": "epoch-a",
            "training_source_count": 2,
            "held_out_evaluation_source_count": 1,
            "teacher_training_authorized": True,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }

    monkeypatch.setattr(module, "build_teacher_input_files_strict", fake_builder)
    result = build_teacher_input_from_p0_root(root, selection, output)

    assert result["teacher_training_authorized"] is True
    assert observed == {
        "plan": (root / "dataset-plan.json").resolve(),
        "receipt": (root / "source-receipt.json").resolve(),
        "frame_index": (root / "frame-index.json").resolve(),
        "selection": selection.resolve(),
        "out": output,
    }


def test_p0_root_rejects_status_without_teacher_authority(tmp_path: Path) -> None:
    root, selection = _write_p0_root(tmp_path)
    _rewrite(root / "p0-status.json", lambda value: value.__setitem__("teacher_training_authorized", False))

    with pytest.raises(PhotorealTeacherInputP0RootError, match="does not authorize teacher training"):
        resolve_authorized_p0_teacher_inputs(root, selection)


def test_p0_root_rejects_status_with_blockers_even_if_authorized(tmp_path: Path) -> None:
    root, selection = _write_p0_root(tmp_path)
    _rewrite(root / "p0-status.json", lambda value: value.__setitem__("blockers", ["still blocked"]))

    with pytest.raises(PhotorealTeacherInputP0RootError, match="still contains blockers"):
        resolve_authorized_p0_teacher_inputs(root, selection)


def test_p0_root_rejects_repointed_status_output(tmp_path: Path) -> None:
    root, selection = _write_p0_root(tmp_path)
    other = tmp_path / "other-plan.json"
    other.write_text("{}\n", encoding="utf-8")
    _rewrite(
        root / "p0-status.json",
        lambda value: value["outputs"].__setitem__("dataset_plan", str(other.resolve())),
    )

    with pytest.raises(PhotorealTeacherInputP0RootError, match="output path mismatch: dataset_plan"):
        resolve_authorized_p0_teacher_inputs(root, selection)


def test_p0_root_rejects_epoch_selection_for_other_performer(tmp_path: Path) -> None:
    root, selection = _write_p0_root(tmp_path)
    _rewrite(selection, lambda value: value.__setitem__("performer_id", "99"))

    with pytest.raises(PhotorealTeacherInputP0RootError, match="performer does not match"):
        resolve_authorized_p0_teacher_inputs(root, selection)


def test_p0_root_rejects_boolean_v1(tmp_path: Path) -> None:
    root, selection = _write_p0_root(tmp_path)
    _rewrite(root / "p0-status.json", lambda value: value.__setitem__("version", True))

    with pytest.raises(PhotorealTeacherInputP0RootError, match="format/version mismatch"):
        resolve_authorized_p0_teacher_inputs(root, selection)


def test_p0_root_rejects_selection_that_crosses_photoreal_authority(tmp_path: Path) -> None:
    root, selection = _write_p0_root(tmp_path)
    _rewrite(selection, lambda value: value.__setitem__("photoreal_acceptance_authority", True))

    with pytest.raises(PhotorealTeacherInputP0RootError, match="crossed photoreal authority"):
        resolve_authorized_p0_teacher_inputs(root, selection)


def test_p0_root_wraps_strict_teacher_gate_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, selection = _write_p0_root(tmp_path)

    def fail_builder(*args, **kwargs):
        raise PhotorealTeacherInputError("strict mismatch")

    monkeypatch.setattr(module, "build_teacher_input_files_strict", fail_builder)
    with pytest.raises(PhotorealTeacherInputP0RootError, match="strict teacher input gate rejected P0 root"):
        build_teacher_input_from_p0_root(root, selection, tmp_path / "teacher-input.json")

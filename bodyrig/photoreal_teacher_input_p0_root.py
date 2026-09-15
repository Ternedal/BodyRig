from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from .photoreal_teacher_authority import build_teacher_input_files_strict
from .photoreal_teacher_input import (
    PhotorealTeacherInputError,
    SELECTION_FORMAT,
    SELECTION_VERSION,
)

STATUS_FORMAT = "bodyrig-photoreal-p0-status"
STATUS_VERSION = 1
STATUS_TEACHER_TRAINING_AUTHORIZED = "teacher-training-authorized"
CRASH_RECEIPT_NAME = "p0-crash-receipt.json"


class PhotorealTeacherInputP0RootError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealTeacherInputP0RootError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealTeacherInputP0RootError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealTeacherInputP0RootError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum:
        raise PhotorealTeacherInputP0RootError(f"{label} is invalid")
    return result


def _numeric_version(value: Any, *, expected: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != expected:
        raise PhotorealTeacherInputP0RootError(f"{label} format/version mismatch")


def _git_sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=40).lower()
    if len(result) != 40 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealTeacherInputP0RootError(f"{label} is invalid")
    return result


def _need_file(root: Path, name: str, *, label: str) -> Path:
    candidate = root / name
    if candidate.is_symlink():
        raise PhotorealTeacherInputP0RootError(f"{label} may not be a symlink: {candidate}")
    try:
        path = candidate.resolve(strict=True)
    except OSError as exc:
        raise PhotorealTeacherInputP0RootError(f"{label} not found in P0 root: {candidate}") from exc
    if not path.is_file():
        raise PhotorealTeacherInputP0RootError(f"{label} not found in P0 root: {path}")
    if path.parent != root or path.name != name:
        raise PhotorealTeacherInputP0RootError(f"{label} escaped the canonical P0 root: {path}")
    return path


def _normalized_path(value: Any, *, label: str) -> str:
    text = _text(value, label=label, maximum=32768)
    return os.path.normcase(os.path.abspath(os.path.expanduser(text)))


def _require_status_output_path(
    outputs: Mapping[str, Any],
    *,
    key: str,
    expected: Path,
) -> None:
    if key not in outputs:
        raise PhotorealTeacherInputP0RootError(f"P0 status output is missing: {key}")
    observed = _normalized_path(outputs.get(key), label=f"P0 status output {key}")
    expected_normalized = os.path.normcase(os.path.abspath(str(expected)))
    if observed != expected_normalized:
        raise PhotorealTeacherInputP0RootError(f"P0 status output path mismatch: {key}")


def resolve_authorized_p0_teacher_inputs(
    p0_root: str | Path,
    epoch_selection_path: str | Path,
) -> tuple[Path, Path, Path, Path]:
    root = Path(p0_root).expanduser().resolve()
    if not root.is_dir():
        raise PhotorealTeacherInputP0RootError(f"P0 root not found: {root}")

    crash_receipt = root / CRASH_RECEIPT_NAME
    if crash_receipt.exists() or crash_receipt.is_symlink():
        raise PhotorealTeacherInputP0RootError(
            f"P0 root contains {CRASH_RECEIPT_NAME}; interrupted/partial P0 outputs may not grant teacher authority"
        )

    status_path = _need_file(root, "p0-status.json", label="P0 status")
    plan_path = _need_file(root, "dataset-plan.json", label="dataset plan")
    receipt_path = _need_file(root, "source-receipt.json", label="source receipt")
    frame_index_path = _need_file(root, "frame-index.json", label="frame index")

    selection_path = Path(epoch_selection_path).expanduser().resolve()
    if not selection_path.is_file():
        raise PhotorealTeacherInputP0RootError(f"appearance epoch selection not found: {selection_path}")

    status = _read_json(status_path, label="P0 status")
    if status.get("format") != STATUS_FORMAT:
        raise PhotorealTeacherInputP0RootError("P0 status format/version mismatch")
    _numeric_version(status.get("version"), expected=STATUS_VERSION, label="P0 status")
    performer_id = _text(status.get("performer_id"), label="P0 status performer id", maximum=256)
    _git_sha(status.get("bodyrig_revision"), label="P0 status BodyRig revision")
    status_state = _text(status.get("status"), label="P0 status state", maximum=256)
    if status_state != STATUS_TEACHER_TRAINING_AUTHORIZED:
        raise PhotorealTeacherInputP0RootError("P0 status state does not authorize teacher training")

    blockers = status.get("blockers")
    if not isinstance(blockers, list):
        raise PhotorealTeacherInputP0RootError("P0 status blockers must be a list")
    if blockers:
        raise PhotorealTeacherInputP0RootError(
            f"P0 status still contains blockers ({len(blockers)}); teacher input remains blocked"
        )
    if status.get("teacher_training_authorized") is not True:
        raise PhotorealTeacherInputP0RootError("P0 status does not authorize teacher training")
    if status.get("human_visual_acceptance_required") is not True:
        raise PhotorealTeacherInputP0RootError("P0 status removed the human visual acceptance boundary")
    if status.get("photoreal_acceptance_authority") is not False:
        raise PhotorealTeacherInputP0RootError("P0 status crossed photoreal acceptance authority")
    if status.get("production_activation") is not False:
        raise PhotorealTeacherInputP0RootError("P0 status crossed production authority")

    outputs = status.get("outputs")
    if not isinstance(outputs, Mapping):
        raise PhotorealTeacherInputP0RootError("P0 status outputs are invalid")
    _require_status_output_path(outputs, key="dataset_plan", expected=plan_path)
    _require_status_output_path(outputs, key="source_receipt", expected=receipt_path)
    _require_status_output_path(outputs, key="frame_index", expected=frame_index_path)

    selection = _read_json(selection_path, label="appearance epoch selection")
    if selection.get("format") != SELECTION_FORMAT:
        raise PhotorealTeacherInputP0RootError("appearance epoch selection format/version mismatch")
    _numeric_version(
        selection.get("version"),
        expected=SELECTION_VERSION,
        label="appearance epoch selection",
    )
    if _text(selection.get("performer_id"), label="appearance epoch selection performer id", maximum=256) != performer_id:
        raise PhotorealTeacherInputP0RootError("appearance epoch selection performer does not match the P0 root")
    if selection.get("teacher_input_authorized") is not True or selection.get("teacher_training_authorized") is not True:
        raise PhotorealTeacherInputP0RootError("appearance epoch selection does not authorize teacher input/training")
    if selection.get("photoreal_acceptance_authority") is not False:
        raise PhotorealTeacherInputP0RootError("appearance epoch selection crossed photoreal authority")
    if selection.get("human_visual_acceptance_required") is not True:
        raise PhotorealTeacherInputP0RootError("appearance epoch selection removed human visual acceptance")
    if selection.get("build_only") is not True or selection.get("runtime_dependency") is not False:
        raise PhotorealTeacherInputP0RootError("appearance epoch selection build/runtime boundary is invalid")
    if selection.get("production_activation") is not False:
        raise PhotorealTeacherInputP0RootError("appearance epoch selection crossed production authority")

    return plan_path, receipt_path, frame_index_path, selection_path


def build_teacher_input_from_p0_root(
    p0_root: str | Path,
    epoch_selection_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan_path, receipt_path, frame_index_path, selection_path = resolve_authorized_p0_teacher_inputs(
        p0_root,
        epoch_selection_path,
    )
    try:
        return build_teacher_input_files_strict(
            plan_path,
            receipt_path,
            frame_index_path,
            selection_path,
            output_path,
        )
    except (OSError, PhotorealTeacherInputError) as exc:
        raise PhotorealTeacherInputP0RootError(f"strict teacher input gate rejected P0 root: {exc}") from exc

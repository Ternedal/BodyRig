from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .photoreal_frame_index_integrity import (
    PhotorealFrameIndexIntegrityError,
    validate_frame_index_integrity,
)
from .photoreal_teacher_input import PhotorealTeacherInputError, build_teacher_input


class PhotorealTeacherInputReadbackAuthorityError(PhotorealTeacherInputError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealTeacherInputReadbackAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealTeacherInputReadbackAuthorityError(f"{label} must be a JSON object")
    return value


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_teacher_input_files_strict(
    plan_path: str | Path,
    receipt_path: str | Path,
    frame_index_path: str | Path,
    epoch_selection_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path, label="photoreal dataset plan")
    receipt = _read_json(receipt_path, label="photoreal source receipt")
    frame_index = _read_json(frame_index_path, label="photoreal sealed frame index")
    selection = _read_json(epoch_selection_path, label="appearance epoch selection")
    try:
        frame_index_sha256 = validate_frame_index_integrity(frame_index)
    except PhotorealFrameIndexIntegrityError as exc:
        raise PhotorealTeacherInputReadbackAuthorityError(str(exc)) from exc

    result = dict(build_teacher_input(plan, receipt, frame_index, selection))
    result.pop("teacher_input_sha256", None)
    result["source_frame_index_sha256"] = frame_index_sha256
    result["teacher_input_sha256"] = _digest(result)

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealTeacherInputReadbackAuthorityError(
            f"teacher input manifest already exists: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .photoreal_appearance_epoch import PhotorealAppearanceEpochError, build_appearance_epoch_plan
from .photoreal_frame_index_integrity import (
    PhotorealFrameIndexIntegrityError,
    validate_frame_index_integrity,
)


class PhotorealAppearanceEpochReadbackAuthorityError(PhotorealAppearanceEpochError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealAppearanceEpochReadbackAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAppearanceEpochReadbackAuthorityError(f"{label} must be a JSON object")
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


def build_appearance_epoch_plan_file_strict(
    frame_index_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    frame_index = _read_json(frame_index_path, label="photoreal sealed frame index")
    try:
        frame_index_sha256 = validate_frame_index_integrity(frame_index)
    except PhotorealFrameIndexIntegrityError as exc:
        raise PhotorealAppearanceEpochReadbackAuthorityError(str(exc)) from exc

    result = dict(build_appearance_epoch_plan(frame_index))
    result.pop("appearance_epoch_plan_sha256", None)
    result["source_frame_index_sha256"] = frame_index_sha256
    result["appearance_epoch_plan_sha256"] = _digest(result)

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealAppearanceEpochReadbackAuthorityError(
            f"appearance epoch plan already exists: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result

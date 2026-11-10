from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .photoreal_frame_authorized_observations_integrity import (
    PhotorealAuthorizedObservationsIntegrityError,
    validate_authorized_observations_integrity,
)
from .photoreal_frame_index import PhotorealFrameIndexError, build_frame_index
from . import json_io


class PhotorealFrameIndexReadbackAuthorityError(PhotorealFrameIndexError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    return json_io.read_json_object(
        source,
        error=PhotorealFrameIndexReadbackAuthorityError,
        unreadable=f"{label} is unreadable: {source}",
        not_object=f"{label} must be a JSON object",
    )


def build_frame_index_files_strict(
    plan_path: str | Path,
    receipt_path: str | Path,
    observations_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path, label="photoreal dataset plan")
    receipt = _read_json(receipt_path, label="photoreal source receipt")
    observations = _read_json(
        observations_path,
        label="photoreal core-authorized frame observations",
    )
    try:
        validate_authorized_observations_integrity(observations)
    except PhotorealAuthorizedObservationsIntegrityError as exc:
        raise PhotorealFrameIndexReadbackAuthorityError(str(exc)) from exc

    result = build_frame_index(plan, receipt, observations)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealFrameIndexReadbackAuthorityError(
            f"photoreal frame index already exists: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result

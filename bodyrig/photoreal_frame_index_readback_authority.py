from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .photoreal_frame_authorized_observations_integrity import (
    PhotorealAuthorizedObservationsIntegrityError,
    validate_authorized_observations_integrity,
)
from .photoreal_frame_index import PhotorealFrameIndexError, build_frame_index
from .photoreal_frame_index_integrity import (
    PhotorealFrameIndexIntegrityError,
    seal_frame_index,
)


class PhotorealFrameIndexReadbackAuthorityError(PhotorealFrameIndexError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealFrameIndexReadbackAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealFrameIndexReadbackAuthorityError(f"{label} must be a JSON object")
    return value


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
        source_authority_sha256 = validate_authorized_observations_integrity(observations)
    except PhotorealAuthorizedObservationsIntegrityError as exc:
        raise PhotorealFrameIndexReadbackAuthorityError(str(exc)) from exc

    try:
        result = seal_frame_index(
            build_frame_index(plan, receipt, observations),
            source_authority_sha256,
        )
    except PhotorealFrameIndexIntegrityError as exc:
        raise PhotorealFrameIndexReadbackAuthorityError(str(exc)) from exc

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

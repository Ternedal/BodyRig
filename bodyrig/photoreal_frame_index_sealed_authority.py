from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .photoreal_frame_identity_output_provenance import (
    PhotorealFrameIdentityOutputProvenanceError,
    validate_frame_identity_authority_integrity,
)
from .photoreal_frame_index import PhotorealFrameIndexError, build_frame_index


class PhotorealFrameIndexSealedAuthorityError(PhotorealFrameIndexError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealFrameIndexSealedAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealFrameIndexSealedAuthorityError(f"{label} must be a JSON object")
    return value


def build_frame_index_files_sealed(
    plan_path: str | Path,
    receipt_path: str | Path,
    observations_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path, label="photoreal dataset plan")
    receipt = _read_json(receipt_path, label="photoreal source receipt")
    observations = _read_json(
        observations_path,
        label="photoreal sealed core-authorized frame observations",
    )
    try:
        authority_sha256 = validate_frame_identity_authority_integrity(observations)
    except PhotorealFrameIdentityOutputProvenanceError as exc:
        raise PhotorealFrameIndexSealedAuthorityError(str(exc)) from exc

    result = dict(build_frame_index(plan, receipt, observations))
    result["source_frame_identity_authority_sha256"] = authority_sha256

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealFrameIndexSealedAuthorityError(
            f"photoreal frame index already exists: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result

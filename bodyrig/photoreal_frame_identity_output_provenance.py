from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .photoreal_frame_identity_authority import PhotorealFrameIdentityAuthorityError

DIGEST_FIELD = "frame_identity_authority_sha256"


class PhotorealFrameIdentityOutputProvenanceError(PhotorealFrameIdentityAuthorityError):
    pass


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealFrameIdentityOutputProvenanceError(
            "frame identity authority artifact is not canonical JSON"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def canonical_frame_identity_authority_sha256(artifact: Mapping[str, Any]) -> str:
    core = dict(artifact)
    core.pop(DIGEST_FIELD, None)
    return _canonical_digest(core)


def seal_frame_identity_authority(artifact: Mapping[str, Any]) -> dict[str, Any]:
    if DIGEST_FIELD in artifact:
        raise PhotorealFrameIdentityOutputProvenanceError(
            "frame identity authority artifact is already sealed"
        )
    result = dict(artifact)
    result[DIGEST_FIELD] = canonical_frame_identity_authority_sha256(result)
    return result


def validate_frame_identity_authority_integrity(artifact: Mapping[str, Any]) -> str:
    digest = artifact.get(DIGEST_FIELD)
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or digest != digest.lower()
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise PhotorealFrameIdentityOutputProvenanceError(
            "frame identity authority SHA-256 is missing or invalid"
        )
    expected = canonical_frame_identity_authority_sha256(artifact)
    if digest != expected:
        raise PhotorealFrameIdentityOutputProvenanceError(
            "frame identity authority digest mismatch"
        )
    return digest

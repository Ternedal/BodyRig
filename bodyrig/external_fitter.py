from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .avatar import AvatarError, AvatarFitResult, validate_vrm1
from .identity import validate_visual_identity
from .package import validate_bodyprint

REQUEST_FORMAT = "bodyrig-avatar-fit-request"
RESULT_FORMAT = "bodyrig-avatar-fit-result"
VERSION = 1
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ADAPTER_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class ExternalFitterError(ValueError):
    pass


@dataclass(frozen=True)
class ExternalFitterResult:
    fit: AvatarFitResult
    visual_identity: str


def build_external_fit_request(
    *,
    bodyprint: Mapping[str, Any],
    name: str,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the metadata request passed to an isolated reconstruction engine.

    The private identity workspace path is deliberately *not* part of the JSON
    request. An operator/invoker may pass such a path separately to the external
    process, but it must never leak into provenance or portable package data.
    """

    if not isinstance(name, str) or not name.strip() or len(name) > 160:
        raise ExternalFitterError("avatar name must contain 1..160 characters")
    validated_bodyprint = validate_bodyprint(dict(bodyprint))
    validated_identity = validate_visual_identity(identity)
    return {
        "format": REQUEST_FORMAT,
        "version": VERSION,
        "name": name.strip(),
        "bodyprint": validated_bodyprint,
        "visual_identity": validated_identity,
    }


def validate_external_fit_output(
    output_dir: str | Path,
    *,
    expected_adapter: str,
    expected_revision: str,
) -> ExternalFitterResult:
    """Validate an isolated fitter result before BodyRig can package it.

    The external environment may be arbitrary research code; the trust boundary
    is the files it returns. BodyRig accepts only fixed filenames, strict JSON,
    exact hashes, a valid VRM 1.0 avatar and a real PNG thumbnail.
    """

    if not ADAPTER_RE.fullmatch(expected_adapter):
        raise ExternalFitterError("expected adapter id is invalid")
    if not isinstance(expected_revision, str) or not expected_revision.strip() or len(expected_revision) > 160:
        raise ExternalFitterError("expected adapter revision is invalid")

    root = Path(output_dir).expanduser().resolve()
    if not root.is_dir():
        raise ExternalFitterError(f"external fitter output directory not found: {root}")
    expected_names = {"result.json", "avatar.vrm", "thumbnail.png"}
    actual_names = {path.name for path in root.iterdir()}
    if actual_names != expected_names or any(not path.is_file() for path in root.iterdir()):
        raise ExternalFitterError("external fitter output must contain exactly result.json, avatar.vrm and thumbnail.png")

    try:
        result = json.loads(
            (root / "result.json").read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExternalFitterError("external fitter result.json is invalid canonical JSON") from exc

    required = {
        "format",
        "version",
        "adapter",
        "revision",
        "visual_identity",
        "avatar_sha256",
        "thumbnail_sha256",
    }
    if not isinstance(result, dict) or set(result) != required:
        raise ExternalFitterError("external fitter result fields must match v1 exactly")
    if result["format"] != RESULT_FORMAT or result["version"] != VERSION:
        raise ExternalFitterError("unsupported external fitter result format/version")
    if result["adapter"] != expected_adapter or result["revision"] != expected_revision:
        raise ExternalFitterError("external fitter adapter/revision does not match the selected adapter")
    if result["visual_identity"] != "source-derived":
        raise ExternalFitterError("external fitter must explicitly report source-derived visual identity")

    avatar = (root / "avatar.vrm").read_bytes()
    thumbnail = (root / "thumbnail.png").read_bytes()
    avatar_hash = hashlib.sha256(avatar).hexdigest()
    thumbnail_hash = hashlib.sha256(thumbnail).hexdigest()
    for field, actual in (("avatar_sha256", avatar_hash), ("thumbnail_sha256", thumbnail_hash)):
        expected = result[field]
        if not isinstance(expected, str) or not SHA_RE.fullmatch(expected) or expected != actual:
            raise ExternalFitterError(f"external fitter {field} mismatch")

    try:
        validate_vrm1(avatar)
    except AvatarError as exc:
        raise ExternalFitterError(f"external fitter avatar is not valid VRM 1.0: {exc}") from exc
    if not thumbnail.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ExternalFitterError("external fitter thumbnail is not PNG")

    return ExternalFitterResult(
        fit=AvatarFitResult(
            avatar_vrm=avatar,
            thumbnail_png=thumbnail,
            adapter=expected_adapter,
            revision=expected_revision,
        ),
        visual_identity="source-derived",
    )

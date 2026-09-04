from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .bridges.avatar_fidelity_components import (
    FidelityComponentError,
    validate_receipt,
    with_face_secondary_receipt,
)
from .bridges.face_secondary_fidelity import (
    FaceSecondaryFidelityError,
    validate_face_secondary_receipt,
)
from .package import MRBodyError, validate_package


FORMAT = "bodyrig-high-fidelity-package-audit"
VERSION = 1
GLB_MAGIC = b"glTF"
JSON_CHUNK = b"JSON"


class HighFidelityPackageAuditError(ValueError):
    pass


def _read_glb_document(value: bytes) -> dict[str, Any]:
    if not isinstance(value, bytes) or len(value) < 20 or value[:4] != GLB_MAGIC:
        raise HighFidelityPackageAuditError("avatar.vrm is not a GLB/VRM")
    version, declared_length = struct.unpack("<II", value[4:12])
    if version != 2 or declared_length != len(value):
        raise HighFidelityPackageAuditError("avatar.vrm GLB header is invalid")
    offset = 12
    document: dict[str, Any] | None = None
    while offset + 8 <= len(value):
        length, kind = struct.unpack("<I4s", value[offset:offset + 8])
        offset += 8
        end = offset + length
        if end > len(value):
            raise HighFidelityPackageAuditError("avatar.vrm GLB chunk is truncated")
        payload = value[offset:end]
        offset = end
        if kind != JSON_CHUNK:
            continue
        if document is not None:
            raise HighFidelityPackageAuditError("avatar.vrm contains multiple JSON chunks")
        try:
            raw = json.loads(
                payload.rstrip(b" \x00").decode("utf-8"),
                parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise HighFidelityPackageAuditError("avatar.vrm GLB JSON is invalid") from exc
        if not isinstance(raw, dict):
            raise HighFidelityPackageAuditError("avatar.vrm GLB JSON document is not an object")
        document = raw
    if document is None:
        raise HighFidelityPackageAuditError("avatar.vrm GLB has no JSON document")
    return document


def audit_fidelity_document(document: Mapping[str, Any]) -> dict[str, Any]:
    extras = document.get("extras") if isinstance(document, Mapping) else None
    bodyrig = extras.get("bodyrig") if isinstance(extras, Mapping) else None
    if not isinstance(bodyrig, Mapping):
        raise HighFidelityPackageAuditError("BodyRig VRM metadata is missing")

    top_raw = bodyrig.get("fidelityComponents")
    face_raw = bodyrig.get("faceSecondaryFidelity")
    if not isinstance(top_raw, Mapping):
        raise HighFidelityPackageAuditError("BodyRig fidelityComponents receipt is missing")
    if not isinstance(face_raw, Mapping):
        raise HighFidelityPackageAuditError("BodyRig faceSecondaryFidelity receipt is missing")
    try:
        top = validate_receipt(top_raw)
        face = validate_face_secondary_receipt(face_raw)
        expected_top = with_face_secondary_receipt(
            top,
            face_secondary_receipt=face,
        )
    except (FidelityComponentError, FaceSecondaryFidelityError) as exc:
        raise HighFidelityPackageAuditError(str(exc)) from exc

    if top != expected_top:
        raise HighFidelityPackageAuditError(
            "top-level face_secondary status is inconsistent with nested face-secondary receipt"
        )

    return {
        "components": dict(top["components"]),
        "high_fidelity_ready": bool(top["highFidelityReady"]),
        "top_level_blockers": list(top["blockers"]),
        "face_secondary_components": dict(face["components"]),
        "face_secondary_ready": bool(face["faceSecondaryReady"]),
        "face_secondary_blockers": list(face["blockers"]),
        "semantic_vertex_map_authority": str(face["semanticVertexMapAuthority"]),
        "human_review_required": bool(top["humanReviewRequired"] and face["humanReviewRequired"]),
        "production_ready": bool(top["productionReady"] or face["productionReady"]),
    }


def audit_high_fidelity_package(path: str | Path) -> dict[str, Any]:
    package = Path(path).expanduser().resolve()
    try:
        validated = validate_package(package)
    except MRBodyError as exc:
        raise HighFidelityPackageAuditError(str(exc)) from exc
    try:
        with zipfile.ZipFile(package, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise HighFidelityPackageAuditError("could not read validated avatar.vrm") from exc

    fidelity = audit_fidelity_document(_read_glb_document(avatar))
    return {
        "format": FORMAT,
        "version": VERSION,
        "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "canonical_body_id": validated.manifest["id"],
        **fidelity,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate BodyRig high-fidelity component metadata inside a strict .mrbody package."
    )
    parser.add_argument("package")
    args = parser.parse_args(argv)
    try:
        result = audit_high_fidelity_package(args.package)
    except (OSError, HighFidelityPackageAuditError) as exc:
        print(f"BodyRig high-fidelity package audit: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

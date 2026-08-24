from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from .identity import VisualIdentityError, bind_visual_identity_to_proof
from .proof import ProofError, validate_recovery_proof, read_canonical_json

FORMAT = "bodyrig-portable-identity"
VERSION = 1
AUTHORITY_ADAPTER = "bodyrig.portable_identity"
AUTHORITY_REVISION = "1"
BODY_ID_RE = re.compile(r"^bodyid-[0-9a-f]{24}$")
ALIAS_RE = re.compile(r"^[a-z0-9æøå_-]{1,160}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FIELDS = {
    "format",
    "version",
    "body_id",
    "requested_alias",
    "source_count",
    "source_set_sha256",
    "recovery_proof_sha256",
    "visual_identity_sha256",
    "subject_track_id",
    "authority",
}


class PortableIdentityError(ValueError):
    pass


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PortableIdentityError("portable identity material is not canonicalizable") from exc


def _digest_json(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise PortableIdentityError(f"could not hash source media: {path.name}") from exc
    return digest.hexdigest()


def _source_set_digest(source_files: Iterable[str | Path], *, expected_count: int) -> str:
    paths = [Path(item).expanduser().resolve() for item in source_files]
    if len(paths) != expected_count or not 1 <= len(paths) <= 10:
        raise PortableIdentityError("source media count must match recovery proof source_count")
    seen: set[str] = set()
    digests: list[str] = []
    for path in paths:
        key = os.path.normcase(str(path))
        if key in seen:
            raise PortableIdentityError("source media paths must be distinct")
        seen.add(key)
        if not path.is_file():
            raise PortableIdentityError(f"source media is not a regular file: {path.name}")
        digests.append(_hash_file(path))
    material = {
        "format": "bodyrig-source-byte-set",
        "version": 1,
        "source_sha256": sorted(digests),
    }
    return _digest_json(material)


def _identity_material(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "format": value["format"],
        "version": value["version"],
        "source_count": value["source_count"],
        "source_set_sha256": value["source_set_sha256"],
        "recovery_proof_sha256": value["recovery_proof_sha256"],
        "visual_identity_sha256": value["visual_identity_sha256"],
        "subject_track_id": value["subject_track_id"],
        "authority": value["authority"],
    }


def _body_id_from_material(value: Mapping[str, Any]) -> str:
    return f"bodyid-{hashlib.sha256(_canonical_bytes(_identity_material(value))).hexdigest()[:24]}"


def validate_portable_identity(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != FIELDS:
        raise PortableIdentityError("portable identity fields must match v1 exactly")
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise PortableIdentityError("unsupported portable identity format/version")

    body_id = value.get("body_id")
    if not isinstance(body_id, str) or BODY_ID_RE.fullmatch(body_id) is None:
        raise PortableIdentityError("body_id must be bodyid-<24 lowercase hex>")
    alias = value.get("requested_alias")
    if not isinstance(alias, str) or ALIAS_RE.fullmatch(alias) is None:
        raise PortableIdentityError("requested_alias is invalid")

    count = value.get("source_count")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
        raise PortableIdentityError("source_count must be 1..10")
    for field in ("source_set_sha256", "recovery_proof_sha256", "visual_identity_sha256"):
        digest = value.get(field)
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            raise PortableIdentityError(f"{field} must be lowercase SHA-256")

    track_id = value.get("subject_track_id")
    if not isinstance(track_id, str) or not track_id or len(track_id) > 160:
        raise PortableIdentityError("subject_track_id is invalid")
    authority = value.get("authority")
    if authority != {"adapter": AUTHORITY_ADAPTER, "revision": AUTHORITY_REVISION}:
        raise PortableIdentityError("portable identity authority is invalid")
    if body_id != _body_id_from_material(value):
        raise PortableIdentityError("body_id does not match portable identity content")
    return dict(value)


def build_portable_identity(
    *,
    proof: Mapping[str, Any],
    visual_identity: Mapping[str, Any],
    source_files: Iterable[str | Path],
    requested_alias: str,
) -> dict[str, Any]:
    if not isinstance(requested_alias, str) or ALIAS_RE.fullmatch(requested_alias) is None:
        raise PortableIdentityError("requested_alias is invalid")
    try:
        validated_proof = validate_recovery_proof(dict(proof))
        validated_identity = bind_visual_identity_to_proof(visual_identity, validated_proof)
    except (ProofError, VisualIdentityError, ValueError) as exc:
        raise PortableIdentityError(str(exc)) from exc

    value: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "body_id": "bodyid-" + ("0" * 24),
        "requested_alias": requested_alias,
        "source_count": validated_proof["source_count"],
        "source_set_sha256": _source_set_digest(
            source_files,
            expected_count=validated_proof["source_count"],
        ),
        "recovery_proof_sha256": _digest_json(validated_proof),
        "visual_identity_sha256": _digest_json(validated_identity),
        "subject_track_id": validated_proof["track_id"],
        "authority": {"adapter": AUTHORITY_ADAPTER, "revision": AUTHORITY_REVISION},
    }
    value["body_id"] = _body_id_from_material(value)
    return validate_portable_identity(value)


def _strict_json_object(text: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise PortableIdentityError(f"portable identity receipt contains duplicate key {key!r}")
            result[key] = item
        return result

    value = json.loads(
        text,
        object_pairs_hook=pairs,
        parse_constant=lambda token: (_ for _ in ()).throw(
            PortableIdentityError(f"portable identity receipt contains non-finite constant {token}")
        ),
    )
    if not isinstance(value, dict):
        raise PortableIdentityError("portable identity receipt must be a JSON object")
    return value


def load_portable_identity(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise PortableIdentityError(f"portable identity receipt not found: {resolved}")
    try:
        value = _strict_json_object(resolved.read_text(encoding="utf-8-sig"))
    except PortableIdentityError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PortableIdentityError("portable identity receipt is invalid JSON") from exc
    return validate_portable_identity(value)


def provenance_identity_stage(value: Mapping[str, Any] | Any) -> dict[str, str]:
    receipt = validate_portable_identity(value)
    return {
        "stage": "identity_content",
        "adapter": AUTHORITY_ADAPTER,
        "revision": receipt["body_id"].removeprefix("bodyid-"),
    }


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)
        except FileExistsError as exc:
            raise PortableIdentityError(f"portable identity output already exists: {path}") from exc
        except OSError as exc:
            raise PortableIdentityError("could not commit portable identity receipt create-only") from exc
    finally:
        temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a path-free, content-addressed BodyRig portable identity receipt."
    )
    parser.add_argument("proof", help="bodyrig-recovery-proof.json")
    parser.add_argument("sources", nargs="+", help="Exact source media used by recovery/identity capture")
    parser.add_argument("--identity-profile", required=True, help="bodyrig-visual-identity v1 JSON")
    parser.add_argument("--requested-alias", required=True, help="Operator-facing BodyRig alias")
    parser.add_argument("--out", required=True, help="Create-only portable identity receipt")
    args = parser.parse_args(argv)

    output = Path(args.out).expanduser().resolve()
    try:
        proof = read_canonical_json(args.proof, label="recovery proof")
        identity = read_canonical_json(args.identity_profile, label="visual identity profile")
        receipt = build_portable_identity(
            proof=proof,
            visual_identity=identity,
            source_files=args.sources,
            requested_alias=args.requested_alias,
        )
        _write_create_only(output, receipt)
    except (OSError, ProofError, PortableIdentityError, VisualIdentityError, ValueError) as exc:
        print(f"BodyRig portable identity: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

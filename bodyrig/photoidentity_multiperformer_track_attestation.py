from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_multiperformer_review_prepare import (
    FORMAT as REVIEW_FORMAT,
    PRIVATE_FORMAT as REVIEW_PRIVATE_FORMAT,
    PRIVATE_VERSION as REVIEW_PRIVATE_VERSION,
    VERSION as REVIEW_VERSION,
)

FORMAT = "bodyrig-photoidentity-multiperformer-track-attestation"
VERSION = 1
POLICY = "human-source-track-identity-v1"


class PhotoIdentityMultiTrackAttestationError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityMultiTrackAttestationError(f"required attestation input is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotoIdentityMultiTrackAttestationError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityMultiTrackAttestationError(f"{label} must be a JSON object")
    return value


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _track_maps(public: Mapping[str, Any], private: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    public_rows = public.get("tracks")
    private_rows = private.get("tracks")
    if not isinstance(public_rows, list) or not isinstance(private_rows, list):
        raise PhotoIdentityMultiTrackAttestationError("track review candidate lists are invalid")
    public_map: dict[str, dict[str, Any]] = {}
    private_map: dict[str, dict[str, Any]] = {}
    for raw in public_rows:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityMultiTrackAttestationError("public track review candidate is invalid")
        candidate_id = str(raw.get("track_candidate_id") or "")
        if not candidate_id.startswith("trackcand-") or len(candidate_id) != 42 or candidate_id in public_map:
            raise PhotoIdentityMultiTrackAttestationError("public track candidate id is invalid/duplicate")
        public_map[candidate_id] = dict(raw)
    for raw in private_rows:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityMultiTrackAttestationError("private track review candidate is invalid")
        candidate_id = str(raw.get("track_candidate_id") or "")
        if candidate_id not in public_map or candidate_id in private_map:
            raise PhotoIdentityMultiTrackAttestationError("private track candidate does not match public review")
        if raw.get("track_id") != public_map[candidate_id].get("track_id"):
            raise PhotoIdentityMultiTrackAttestationError("public/private track id binding changed")
        private_map[candidate_id] = dict(raw)
    if set(public_map) != set(private_map):
        raise PhotoIdentityMultiTrackAttestationError("public/private track candidate sets differ")
    return public_map, private_map


def record_multiperformer_track_attestation(
    *,
    review_root: Path,
    track_candidate_id: str,
    current_revision: str,
    quality_note: str,
    confirm_identity: bool,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if confirm_identity is not True:
        raise PhotoIdentityMultiTrackAttestationError("explicit human identity confirmation is required")
    note = str(quality_note or "").strip()
    if not 10 <= len(note) <= 1000:
        raise PhotoIdentityMultiTrackAttestationError("human identity note must contain 10..1000 characters")
    revision = str(current_revision or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise PhotoIdentityMultiTrackAttestationError("current BodyRig revision is not canonical")

    root = review_root.expanduser().resolve()
    if not root.is_dir():
        raise PhotoIdentityMultiTrackAttestationError("multi-performer track review root is missing")
    public_path = root / "multiperformer-track-review-candidates.json"
    private_path = root / "private-track-review" / "private-review-index.json"
    machine_path = root / "machine-track-review.json"
    public = _read_json(public_path, label="Public multi-performer track review")
    private = _read_json(private_path, label="Private multi-performer track review index")

    if public.get("format") != REVIEW_FORMAT or public.get("version") != REVIEW_VERSION:
        raise PhotoIdentityMultiTrackAttestationError("public multi-performer track review format/version is invalid")
    for field in (
        "source_paths_persisted",
        "target_track_selected",
        "biometric_identity_inference_used",
        "generic_guessing_permitted",
        "target_isolated_source_authority",
        "photoidentity_source_evidence_authority",
        "reconstruction_permitted",
        "production_activation",
    ):
        if public.get(field) is not False:
            raise PhotoIdentityMultiTrackAttestationError(f"public track review crossed authority boundary: {field}")
    if public.get("human_identity_attestation_required") is not True:
        raise PhotoIdentityMultiTrackAttestationError("public track review does not require human identity attestation")
    if str(public.get("bodyrig_revision") or "") != revision:
        raise PhotoIdentityMultiTrackAttestationError("track review belongs to a different BodyRig revision")

    if private.get("format") != REVIEW_PRIVATE_FORMAT or private.get("version") != REVIEW_PRIVATE_VERSION:
        raise PhotoIdentityMultiTrackAttestationError("private track review index format/version is invalid")
    if private.get("public_review_manifest_sha256") != _sha256_file(public_path):
        raise PhotoIdentityMultiTrackAttestationError("private track review index is not bound to public review bytes")
    for field in ("bodyrig_revision", "performer_id", "source_candidate_id", "scene_id", "source_media_sha256"):
        if private.get(field) != public.get(field):
            raise PhotoIdentityMultiTrackAttestationError(f"public/private track review differs: {field}")
    if public.get("machine_track_review_sha256") != _sha256_file(machine_path):
        raise PhotoIdentityMultiTrackAttestationError("machine track review bytes changed after review preparation")

    public_map, private_map = _track_maps(public, private)
    selected_id = str(track_candidate_id or "").strip().lower()
    selected = public_map.get(selected_id)
    selected_private = private_map.get(selected_id)
    if selected is None or selected_private is None:
        raise PhotoIdentityMultiTrackAttestationError(f"unknown track review candidate: {selected_id}")

    expected_sheet = root / "private-track-review" / selected_id / "review-sheet.png"
    actual_sheet = Path(str(selected_private.get("review_sheet") or "")).expanduser().resolve()
    if not _same_path(actual_sheet, expected_sheet):
        raise PhotoIdentityMultiTrackAttestationError("private review sheet path escaped canonical review location")
    if _sha256_file(actual_sheet) != str(selected.get("review_sheet_sha256") or ""):
        raise PhotoIdentityMultiTrackAttestationError("review sheet bytes changed after preparation")

    source = Path(str(private.get("source_path") or "")).expanduser().resolve()
    if not source.is_file():
        raise PhotoIdentityMultiTrackAttestationError("attested source media is no longer local")
    if _sha256_file(source) != str(public.get("source_media_sha256") or ""):
        raise PhotoIdentityMultiTrackAttestationError("attested source media bytes changed after review preparation")

    output = (output_path or (root / "photoidentity-multiperformer-track-attestation.json")).expanduser().resolve()
    if output.exists():
        raise PhotoIdentityMultiTrackAttestationError(f"human track attestation already exists: {output}")
    if output.parent != root:
        raise PhotoIdentityMultiTrackAttestationError("human track attestation must be published at the canonical review root")

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policy": POLICY,
        "bodyrig_revision": revision,
        "performer_id": str(public["performer_id"]),
        "scene_id": str(public["scene_id"]),
        "source_candidate_id": str(public["source_candidate_id"]),
        "source_media_sha256": str(public["source_media_sha256"]),
        "public_review_manifest_sha256": _sha256_file(public_path),
        "private_review_index_sha256": _sha256_file(private_path),
        "machine_track_review_sha256": _sha256_file(machine_path),
        "track_candidate_id": selected_id,
        "selected_track_id": str(selected["track_id"]),
        "review_sheet_sha256": str(selected["review_sheet_sha256"]),
        "review_sample_count": int(selected["review_sample_count"]),
        "human_identity_attested": True,
        "human_identity_note": note,
        "attested_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_paths_persisted": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "target_isolated_source_authority": False,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_raw = tempfile.mkstemp(prefix=f".{output.name}.tmp-", dir=output.parent)
    os.close(fd)
    temp = Path(temp_raw)
    try:
        temp.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if output.exists():
            raise PhotoIdentityMultiTrackAttestationError(f"human track attestation already exists: {output}")
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    return {**receipt, "receipt": str(output), "receipt_sha256": _sha256_file(output)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record explicit human identity attestation for one source-derived PHALP track.")
    parser.add_argument("--review-root", required=True)
    parser.add_argument("--track-candidate-id", required=True)
    parser.add_argument("--current-revision", required=True)
    parser.add_argument("--quality-note", required=True)
    parser.add_argument("--confirm-identity", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    try:
        result = record_multiperformer_track_attestation(
            review_root=Path(args.review_root),
            track_candidate_id=args.track_candidate_id,
            current_revision=args.current_revision,
            quality_note=args.quality_note,
            confirm_identity=args.confirm_identity,
            output_path=Path(args.out) if args.out else None,
        )
        print(result["receipt"])
        print(f"Receipt SHA-256: {result['receipt_sha256']}")
        print("Human source-track identity: ATTESTED")
        print("Target-isolated source authority: FALSE")
        return 0
    except (OSError, ValueError, PhotoIdentityMultiTrackAttestationError) as exc:
        print(f"BodyRig multi-performer track attestation: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

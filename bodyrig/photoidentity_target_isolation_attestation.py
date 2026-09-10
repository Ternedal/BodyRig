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

from .photoidentity_target_isolation_prepare import (
    FORMAT as CANDIDATE_FORMAT,
    PRIVATE_FORMAT as CANDIDATE_PRIVATE_FORMAT,
    PRIVATE_VERSION as CANDIDATE_PRIVATE_VERSION,
    VERSION as CANDIDATE_VERSION,
)

FORMAT = "bodyrig-photoidentity-target-isolation-attestation"
VERSION = 1
POLICY = "human-target-isolated-sampled-frame-set-v1"
AUTHORITY_SCOPE = "isolated-sampled-frame-set-only"


class PhotoIdentityTargetIsolationAttestationError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityTargetIsolationAttestationError(f"required isolation-attestation file is missing: {path}")
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
        raise PhotoIdentityTargetIsolationAttestationError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityTargetIsolationAttestationError(f"{label} must be a JSON object")
    return value


def _canonical_revision(value: object, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise PhotoIdentityTargetIsolationAttestationError(f"{label} is not a canonical Git revision")
    return text


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _canonical_private_path(root: Path, value: object, relative: str, *, label: str) -> Path:
    actual = Path(str(value or "")).expanduser().resolve()
    expected = (root / relative).resolve()
    if not _same_path(actual, expected):
        raise PhotoIdentityTargetIsolationAttestationError(f"{label} escaped canonical isolation review location")
    if not actual.is_file():
        raise PhotoIdentityTargetIsolationAttestationError(f"{label} is missing: {actual}")
    return actual


def _load_candidate(root: Path, current_revision: str) -> dict[str, Any]:
    public_path = root / "target-isolation-candidate.json"
    private_path = root / "private-target-isolation" / "private-isolation-index.json"
    machine_path = root / "machine-target-isolation.json"
    public = _read_json(public_path, label="Public target-isolation candidate")
    private = _read_json(private_path, label="Private target-isolation index")

    if public.get("format") != CANDIDATE_FORMAT or public.get("version") != CANDIDATE_VERSION:
        raise PhotoIdentityTargetIsolationAttestationError("target-isolation candidate format/version is invalid")
    if public.get("human_isolation_review_required") is not True:
        raise PhotoIdentityTargetIsolationAttestationError("target-isolation candidate does not require human review")
    for field in (
        "source_paths_persisted",
        "machine_identity_selection",
        "biometric_identity_inference_used",
        "generic_guessing_permitted",
        "target_isolated_source_authority",
        "photoidentity_source_evidence_authority",
        "reconstruction_permitted",
        "production_activation",
    ):
        if public.get(field) is not False:
            raise PhotoIdentityTargetIsolationAttestationError(f"target-isolation candidate crossed authority boundary: {field}")
    candidate_revision = _canonical_revision(public.get("isolation_operator_revision"), label="isolation operator revision")
    if candidate_revision != current_revision:
        raise PhotoIdentityTargetIsolationAttestationError(
            "target-isolation candidate belongs to a different BodyRig revision; review it from the exact candidate revision"
        )
    _canonical_revision(public.get("attestation_revision"), label="upstream human-attestation revision")

    if private.get("format") != CANDIDATE_PRIVATE_FORMAT or private.get("version") != CANDIDATE_PRIVATE_VERSION:
        raise PhotoIdentityTargetIsolationAttestationError("private target-isolation index format/version is invalid")
    if private.get("public_manifest_sha256") != _sha256_file(public_path):
        raise PhotoIdentityTargetIsolationAttestationError("private target-isolation index is not bound to public manifest bytes")
    for field in (
        "attestation_revision", "isolation_operator_revision", "performer_id", "scene_id",
        "source_media_sha256", "selected_track_id",
    ):
        if private.get(field) != public.get(field):
            raise PhotoIdentityTargetIsolationAttestationError(f"public/private target-isolation evidence differs on {field}")
    for field in ("target_isolated_source_authority", "photoidentity_source_evidence_authority", "production_activation"):
        if private.get(field) is not False:
            raise PhotoIdentityTargetIsolationAttestationError(f"private target-isolation index illegally enabled {field}")

    machine = _canonical_private_path(root, private.get("machine_target_isolation"), "machine-target-isolation.json", label="machine target-isolation evidence")
    if _sha256_file(machine) != str(public.get("machine_target_isolation_sha256") or ""):
        raise PhotoIdentityTargetIsolationAttestationError("machine target-isolation bytes changed after preparation")
    contact = _canonical_private_path(
        root,
        private.get("contact_sheet"),
        "private-target-isolation/target-isolation-contact-sheet.png",
        label="target-isolation contact sheet",
    )
    if _sha256_file(contact) != str(public.get("contact_sheet_sha256") or ""):
        raise PhotoIdentityTargetIsolationAttestationError("target-isolation contact sheet bytes changed after preparation")

    upstream_attestation = Path(str(private.get("human_track_attestation") or "")).expanduser().resolve()
    upstream_machine = Path(str(private.get("machine_track_review") or "")).expanduser().resolve()
    if _sha256_file(upstream_attestation) != str(public.get("human_track_attestation_sha256") or ""):
        raise PhotoIdentityTargetIsolationAttestationError("upstream human track attestation bytes changed")
    if _sha256_file(upstream_machine) != str(public.get("machine_track_review_sha256") or ""):
        raise PhotoIdentityTargetIsolationAttestationError("upstream machine track review bytes changed")

    source = Path(str(private.get("source_path") or "")).expanduser().resolve()
    if not source.is_file() or _sha256_file(source) != str(public.get("source_media_sha256") or ""):
        raise PhotoIdentityTargetIsolationAttestationError("original source media bytes changed after isolation preparation")

    public_samples = public.get("samples")
    private_samples = private.get("samples")
    if not isinstance(public_samples, list) or not isinstance(private_samples, list):
        raise PhotoIdentityTargetIsolationAttestationError("target-isolation sample manifests are invalid")
    if len(public_samples) != public.get("candidate_frame_count") or len(public_samples) != len(private_samples) or len(public_samples) < 3:
        raise PhotoIdentityTargetIsolationAttestationError("target-isolation sample count binding is invalid")

    verified_samples: list[dict[str, Any]] = []
    for index, (public_sample, private_sample) in enumerate(zip(public_samples, private_samples, strict=True), start=1):
        if not isinstance(public_sample, Mapping) or not isinstance(private_sample, Mapping):
            raise PhotoIdentityTargetIsolationAttestationError("target-isolation sample row is invalid")
        if public_sample.get("sample_index") != index or private_sample.get("sample_index") != index:
            raise PhotoIdentityTargetIsolationAttestationError("target-isolation sample ordering changed")
        sample_root = f"private-target-isolation/sample-{index:03d}"
        source_frame = _canonical_private_path(root, private_sample.get("source_frame"), f"{sample_root}/source-frame.png", label="source review frame")
        isolated_frame = _canonical_private_path(root, private_sample.get("isolated_frame"), f"{sample_root}/isolated-frame.png", label="isolated review frame")
        review_tile = _canonical_private_path(root, private_sample.get("review_tile"), f"{sample_root}/review-tile.png", label="isolation review tile")
        for path, field, label in (
            (source_frame, "source_frame_sha256", "source review frame"),
            (isolated_frame, "isolated_frame_sha256", "isolated review frame"),
            (review_tile, "review_tile_sha256", "isolation review tile"),
        ):
            if _sha256_file(path) != str(public_sample.get(field) or ""):
                raise PhotoIdentityTargetIsolationAttestationError(f"{label} bytes changed after preparation")
        verified_samples.append(
            {
                "sample_index": index,
                "timestamp_ms": int(public_sample["timestamp_ms"]),
                "isolated_frame_sha256": str(public_sample["isolated_frame_sha256"]),
                "review_tile_sha256": str(public_sample["review_tile_sha256"]),
            }
        )

    return {
        "public_path": public_path,
        "private_path": private_path,
        "public": public,
        "private": private,
        "machine_path": machine_path,
        "contact_path": contact,
        "upstream_attestation": upstream_attestation,
        "source": source,
        "samples": verified_samples,
    }


def record_target_isolation_attestation(
    *,
    isolation_root: Path,
    current_revision: str,
    quality_note: str,
    confirm_isolation: bool,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if confirm_isolation is not True:
        raise PhotoIdentityTargetIsolationAttestationError("explicit human target-isolation confirmation is required")
    note = str(quality_note or "").strip()
    if not 10 <= len(note) <= 1000:
        raise PhotoIdentityTargetIsolationAttestationError("human isolation note must contain 10..1000 characters")
    revision = _canonical_revision(current_revision, label="current BodyRig revision")
    root = isolation_root.expanduser().resolve()
    if not root.is_dir():
        raise PhotoIdentityTargetIsolationAttestationError("target-isolation review root is missing")
    candidate = _load_candidate(root, revision)
    public = candidate["public"]

    output = (output_path or (root / "photoidentity-target-isolation-attestation.json")).expanduser().resolve()
    if output.parent != root:
        raise PhotoIdentityTargetIsolationAttestationError("target-isolation attestation must be published at canonical isolation root")
    if output.exists():
        raise PhotoIdentityTargetIsolationAttestationError(f"target-isolation attestation already exists: {output}")

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policy": POLICY,
        "authority_scope": AUTHORITY_SCOPE,
        "attestation_revision": str(public["attestation_revision"]),
        "isolation_operator_revision": revision,
        "human_review_revision": revision,
        "performer_id": str(public["performer_id"]),
        "scene_id": str(public["scene_id"]),
        "source_candidate_id": str(public["source_candidate_id"]),
        "source_media_sha256": str(public["source_media_sha256"]),
        "selected_track_id": str(public["selected_track_id"]),
        "human_track_attestation_sha256": str(public["human_track_attestation_sha256"]),
        "target_isolation_manifest_sha256": _sha256_file(candidate["public_path"]),
        "private_isolation_index_sha256": _sha256_file(candidate["private_path"]),
        "machine_target_isolation_sha256": _sha256_file(candidate["machine_path"]),
        "contact_sheet_sha256": _sha256_file(candidate["contact_path"]),
        "isolated_frame_count": len(candidate["samples"]),
        "isolated_frames": candidate["samples"],
        "max_other_overlap_fraction": float(public["max_other_overlap_fraction"]),
        "p95_other_overlap_fraction": float(public["p95_other_overlap_fraction"]),
        "high_overlap_state_count": int(public["high_overlap_state_count"]),
        "severe_overlap_state_count": int(public["severe_overlap_state_count"]),
        "all_isolation_samples_reviewed": True,
        "visible_cross_person_contamination_absent": True,
        "human_isolation_attested": True,
        "human_isolation_note": note,
        "attested_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_paths_persisted": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "target_isolated_source_authority": True,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }

    fd, temp_raw = tempfile.mkstemp(prefix=f".{output.name}.tmp-", dir=output.parent)
    os.close(fd)
    temp = Path(temp_raw)
    try:
        temp.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        try:
            os.link(temp, output)
        except FileExistsError as exc:
            raise PhotoIdentityTargetIsolationAttestationError(f"target-isolation attestation already exists: {output}") from exc
        except OSError as exc:
            raise PhotoIdentityTargetIsolationAttestationError("could not atomically publish target-isolation attestation") from exc
    finally:
        temp.unlink(missing_ok=True)
    return {**receipt, "receipt": str(output), "receipt_sha256": _sha256_file(output)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record explicit human authority for a reviewed target-isolated sampled frame set.")
    parser.add_argument("--isolation-root", required=True)
    parser.add_argument("--current-revision", required=True)
    parser.add_argument("--quality-note", required=True)
    parser.add_argument("--confirm-isolation", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    try:
        result = record_target_isolation_attestation(
            isolation_root=Path(args.isolation_root),
            current_revision=args.current_revision,
            quality_note=args.quality_note,
            confirm_isolation=args.confirm_isolation,
            output_path=Path(args.out) if args.out else None,
        )
        print(result["receipt"])
        print(f"Receipt SHA-256: {result['receipt_sha256']}")
        print(f"Authority scope: {AUTHORITY_SCOPE}")
        print("Target-isolated source authority: TRUE")
        print("Photoidentity source evidence authority: FALSE")
        print("Reconstruction permitted: FALSE")
        return 0
    except (OSError, ValueError, PhotoIdentityTargetIsolationAttestationError) as exc:
        print(f"BodyRig target-isolation attestation: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

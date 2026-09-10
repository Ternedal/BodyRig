from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoidentity_multiperformer_target_isolation import (
    FORMAT as CANDIDATE_FORMAT,
    PRIVATE_FORMAT as PRIVATE_CANDIDATE_FORMAT,
    PRIVATE_VERSION as PRIVATE_CANDIDATE_VERSION,
    VERSION as CANDIDATE_VERSION,
)

FORMAT = "bodyrig-photoidentity-multiperformer-target-isolation-attestation"
VERSION = 1
POLICY = "human-source-target-isolation-v1"


class PhotoIdentityMultiTargetAttestationError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityMultiTargetAttestationError(f"required target-isolation evidence is missing: {path}")
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
        raise PhotoIdentityMultiTargetAttestationError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityMultiTargetAttestationError(f"{label} must be a JSON object")
    return value


def _canonical_revision(value: object) -> str:
    revision = str(value or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise PhotoIdentityMultiTargetAttestationError("target isolation attestation requires exact BodyRig Git revision")
    return revision


def _sample_map(rows: object, *, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise PhotoIdentityMultiTargetAttestationError(f"{label} sample list is invalid")
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityMultiTargetAttestationError(f"{label} sample row is invalid")
        sample_id = str(raw.get("sample_id") or "")
        if not sample_id.startswith("targetsample-") or sample_id in result:
            raise PhotoIdentityMultiTargetAttestationError(f"{label} sample id is invalid/duplicate")
        result[sample_id] = dict(raw)
    return result


def _write_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise PhotoIdentityMultiTargetAttestationError(f"target isolation attestation already exists: {path}") from exc
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def record_target_isolation_attestation(
    *,
    candidate_root: Path,
    sample_ids: Sequence[str],
    current_revision: str,
    quality_note: str,
    confirm_target_isolation: bool,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if confirm_target_isolation is not True:
        raise PhotoIdentityMultiTargetAttestationError("explicit human target-isolation confirmation is required")
    note = str(quality_note or "").strip()
    if not 10 <= len(note) <= 1000:
        raise PhotoIdentityMultiTargetAttestationError("human target-isolation note must contain 10..1000 characters")
    revision = _canonical_revision(current_revision)
    root = candidate_root.expanduser().resolve()
    if not root.is_dir():
        raise PhotoIdentityMultiTargetAttestationError("target-isolation candidate root is missing")

    public_path = root / "multiperformer-target-isolation-candidates.json"
    private_path = root / "private-target-source" / "private-target-source-index.json"
    public = _read_json(public_path, label="Public target-isolation candidate manifest")
    private = _read_json(private_path, label="Private target-isolation candidate index")
    if public.get("format") != CANDIDATE_FORMAT or public.get("version") != CANDIDATE_VERSION:
        raise PhotoIdentityMultiTargetAttestationError("target-isolation candidate format/version is invalid")
    if private.get("format") != PRIVATE_CANDIDATE_FORMAT or private.get("version") != PRIVATE_CANDIDATE_VERSION:
        raise PhotoIdentityMultiTargetAttestationError("private target-isolation index format/version is invalid")
    if str(public.get("bodyrig_revision") or "") != revision or str(private.get("bodyrig_revision") or "") != revision:
        raise PhotoIdentityMultiTargetAttestationError("target-isolation candidates belong to a different BodyRig revision")
    if public.get("private_target_source_index_sha256") != _sha256_file(private_path):
        raise PhotoIdentityMultiTargetAttestationError("public candidates are not bound to private target-source bytes")
    for field in ("performer_id", "scene_id", "source_media_sha256", "track_candidate_id", "selected_track_id"):
        if public.get(field) != private.get(field):
            raise PhotoIdentityMultiTargetAttestationError(f"public/private target-isolation evidence differs on {field}")
    if public.get("target_track_identity_attested") is not True or public.get("all_samples_phalp_observed") is not True:
        raise PhotoIdentityMultiTargetAttestationError("target-isolation candidates lack human-track/observed-sample authority")
    if public.get("target_isolation_human_review_required") is not True:
        raise PhotoIdentityMultiTargetAttestationError("target-isolation candidates do not require human review")
    for field in (
        "bbox_interpolation_used",
        "source_pixels_resized",
        "occlusion_removal_used",
        "generative_pixels_used",
        "biometric_identity_inference_used",
        "generic_guessing_permitted",
        "target_isolated_source_authority",
        "photoidentity_source_evidence_authority",
        "reconstruction_permitted",
        "production_activation",
    ):
        if public.get(field) is not False:
            raise PhotoIdentityMultiTargetAttestationError(f"target-isolation candidates crossed authority boundary: {field}")

    public_map = _sample_map(public.get("samples"), label="public")
    private_map = _sample_map(private.get("samples"), label="private")
    if set(public_map) != set(private_map):
        raise PhotoIdentityMultiTargetAttestationError("public/private target-isolation sample sets differ")

    selected = [str(item or "").strip() for item in sample_ids]
    if not selected or any(not item for item in selected) or len(selected) != len(set(selected)):
        raise PhotoIdentityMultiTargetAttestationError("at least one unique target-isolation sample id is required")
    unknown = [item for item in selected if item not in public_map]
    if unknown:
        raise PhotoIdentityMultiTargetAttestationError(f"unknown target-isolation sample id: {unknown[0]}")

    accepted: list[dict[str, Any]] = []
    for sample_id in selected:
        public_row = public_map[sample_id]
        private_row = private_map[sample_id]
        frame = Path(str(private_row.get("reviewed_source_frame") or "")).expanduser().resolve()
        crop = Path(str(private_row.get("target_track_crop") or "")).expanduser().resolve()
        expected_root = root / "private-target-source" / sample_id
        if frame.parent != expected_root or crop.parent != expected_root:
            raise PhotoIdentityMultiTargetAttestationError("target-isolation private sample path escaped canonical root")
        if _sha256_file(frame) != str(public_row.get("source_frame_sha256") or ""):
            raise PhotoIdentityMultiTargetAttestationError("reviewed source-frame bytes changed after candidate materialization")
        if _sha256_file(crop) != str(public_row.get("target_crop_sha256") or ""):
            raise PhotoIdentityMultiTargetAttestationError("target crop bytes changed after candidate materialization")
        accepted.append(
            {
                "sample_id": sample_id,
                "timestamp_ms": int(public_row["timestamp_ms"]),
                "source_frame_sha256": str(public_row["source_frame_sha256"]),
                "target_crop_sha256": str(public_row["target_crop_sha256"]),
                "native_crop_width": int(public_row["native_crop_width"]),
                "native_crop_height": int(public_row["native_crop_height"]),
            }
        )

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policy": POLICY,
        "bodyrig_revision": revision,
        "performer_id": str(public["performer_id"]),
        "scene_id": str(public["scene_id"]),
        "source_media_sha256": str(public["source_media_sha256"]),
        "track_candidate_id": str(public["track_candidate_id"]),
        "selected_track_id": str(public["selected_track_id"]),
        "candidate_manifest_sha256": _sha256_file(public_path),
        "private_candidate_index_sha256": _sha256_file(private_path),
        "human_track_attestation_sha256": str(public["human_track_attestation_sha256"]),
        "accepted_sample_count": len(accepted),
        "accepted_samples": accepted,
        "human_target_isolation_attested": True,
        "cross_person_contamination_absent_attested": True,
        "authority_scope": "accepted-samples-only",
        "human_isolation_note": note,
        "attested_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "bbox_interpolation_used": False,
        "source_pixels_resized": False,
        "occlusion_removal_used": False,
        "generative_pixels_used": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "target_isolated_source_authority": True,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    output = (output_path or (root / "photoidentity-multiperformer-target-isolation-attestation.json")).expanduser().resolve()
    if output.parent != root:
        raise PhotoIdentityMultiTargetAttestationError("target isolation attestation must be published at canonical candidate root")
    _write_create_only(output, receipt)
    return {**receipt, "receipt": str(output), "receipt_sha256": _sha256_file(output)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record human source-only contamination review for target-isolation candidates.")
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--sample-id", action="append", required=True)
    parser.add_argument("--current-revision", required=True)
    parser.add_argument("--quality-note", required=True)
    parser.add_argument("--confirm-target-isolation", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    try:
        result = record_target_isolation_attestation(
            candidate_root=Path(args.candidate_root),
            sample_ids=args.sample_id,
            current_revision=args.current_revision,
            quality_note=args.quality_note,
            confirm_target_isolation=args.confirm_target_isolation,
            output_path=Path(args.out) if args.out else None,
        )
        print(result["receipt"])
        print(f"Receipt SHA-256: {result['receipt_sha256']}")
        print(f"Accepted target-isolated samples: {result['accepted_sample_count']}")
        print("Target-isolated source authority: TRUE (accepted samples only)")
        print("Photoidentity source sufficiency authority: FALSE")
        print("Reconstruction permitted: FALSE")
        return 0
    except (OSError, ValueError, PhotoIdentityMultiTargetAttestationError) as exc:
        print(f"BodyRig multi-performer target isolation attestation: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

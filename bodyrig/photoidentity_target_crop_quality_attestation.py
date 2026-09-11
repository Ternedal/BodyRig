from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoidentity_evidence import DETAIL_QUALITY_THRESHOLD
from .photoidentity_multiperformer_target_attestation import (
    FORMAT as ISOLATION_FORMAT,
    POLICY as ISOLATION_POLICY,
    VERSION as ISOLATION_VERSION,
)
from .photoidentity_target_crop_detail import (
    OPENPOSE_ADAPTER,
    OPENPOSE_REVISION,
    SCHP_ADAPTER,
    SCHP_REVISION,
    SUPPORTED_DOMAINS,
)
from .photoidentity_target_crop_enrich import (
    FORMAT as ENRICHMENT_FORMAT,
    PRIVATE_FORMAT as PRIVATE_ENRICHMENT_FORMAT,
    PRIVATE_VERSION as PRIVATE_ENRICHMENT_VERSION,
    VERSION as ENRICHMENT_VERSION,
)

FORMAT = "bodyrig-photoidentity-target-crop-detail-quality-attestation"
VERSION = 1
POLICY = "human-source-target-crop-detail-quality-v1"
ADAPTER = "human-reviewed-target-crop-detail-quality"
ADAPTER_REVISION = "1"
REF_RE = re.compile(r"^(targetsample-[A-Za-z0-9._-]{1,80}):(eyes_detail|hands|feet|hair_hairline|skin_detail)$")
DOMAIN_MACHINE_AUTHORITY = {
    "eyes_detail": (OPENPOSE_ADAPTER, OPENPOSE_REVISION),
    "hands": (OPENPOSE_ADAPTER, OPENPOSE_REVISION),
    "feet": (OPENPOSE_ADAPTER, OPENPOSE_REVISION),
    "hair_hairline": (SCHP_ADAPTER, SCHP_REVISION),
    "skin_detail": (SCHP_ADAPTER, SCHP_REVISION),
}


class PhotoIdentityTargetCropQualityAttestationError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityTargetCropQualityAttestationError(f"required source-detail evidence is missing: {path}")
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
        raise PhotoIdentityTargetCropQualityAttestationError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityTargetCropQualityAttestationError(f"{label} must be a JSON object")
    return value


def _canonical_revision(value: object) -> str:
    revision = str(value or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise PhotoIdentityTargetCropQualityAttestationError("source-detail attestation requires exact BodyRig Git revision")
    return revision


def _finite_quality(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotoIdentityTargetCropQualityAttestationError(f"{label} is not numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise PhotoIdentityTargetCropQualityAttestationError(f"{label} is outside 0..1")
    return result


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentityTargetCropQualityAttestationError(f"source-detail attestation already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise PhotoIdentityTargetCropQualityAttestationError(f"source-detail attestation already exists: {path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _rows_by_id(rows: object, *, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise PhotoIdentityTargetCropQualityAttestationError(f"{label} rows are invalid")
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityTargetCropQualityAttestationError(f"{label} row is invalid")
        sample_id = str(raw.get("sample_id") or "")
        if not sample_id.startswith("targetsample-") or sample_id in result:
            raise PhotoIdentityTargetCropQualityAttestationError(f"{label} sample id is invalid/duplicate")
        result[sample_id] = dict(raw)
    return result


def _candidate_map(sample: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw_candidates = sample.get("candidates")
    if not isinstance(raw_candidates, list):
        raise PhotoIdentityTargetCropQualityAttestationError("target-crop machine candidate list is invalid")
    result: dict[str, dict[str, Any]] = {}
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityTargetCropQualityAttestationError("target-crop machine candidate is invalid")
        domain = str(raw.get("domain") or "")
        if domain not in SUPPORTED_DOMAINS or domain in result:
            raise PhotoIdentityTargetCropQualityAttestationError("target-crop machine domain is invalid/duplicate")
        result[domain] = dict(raw)
    return result


def _parse_refs(values: Sequence[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    domains: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        match = REF_RE.fullmatch(text)
        if not match:
            raise PhotoIdentityTargetCropQualityAttestationError(f"invalid source-detail reference: {text or 'empty'}")
        sample_id, domain = match.groups()
        if domain in domains:
            raise PhotoIdentityTargetCropQualityAttestationError(f"source-detail attestation allows one selected crop per domain: {domain}")
        domains.add(domain)
        parsed.append((sample_id, domain))
    if not parsed:
        raise PhotoIdentityTargetCropQualityAttestationError("source-detail attestation requires at least one selected sample/domain")
    return parsed


def record_target_crop_quality_attestation(
    *,
    candidate_root: Path,
    enrichment_root: Path,
    selected_refs: Sequence[str],
    current_revision: str,
    quality_note: str,
    confirm_quality: bool,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if confirm_quality is not True:
        raise PhotoIdentityTargetCropQualityAttestationError("explicit human source-detail quality confirmation is required")
    note = str(quality_note or "").strip()
    if not 20 <= len(note) <= 2000 or (note.startswith("<") and note.endswith(">")):
        raise PhotoIdentityTargetCropQualityAttestationError("source-detail attestation requires a real quality note")
    revision = _canonical_revision(current_revision)
    candidate_root = candidate_root.expanduser().resolve()
    enrichment_root = enrichment_root.expanduser().resolve()
    if not candidate_root.is_dir() or not enrichment_root.is_dir():
        raise PhotoIdentityTargetCropQualityAttestationError("candidate/enrichment root is missing")

    isolation_path = candidate_root / "photoidentity-multiperformer-target-isolation-attestation.json"
    public_path = enrichment_root / "target-crop-detail-enrichment.json"
    private_path = enrichment_root / "private-analysis" / "private-analysis-index.json"
    isolation = _read_json(isolation_path, label="Human target-isolation attestation")
    public = _read_json(public_path, label="Target-crop detail enrichment")
    private = _read_json(private_path, label="Private target-crop detail enrichment")

    if isolation.get("format") != ISOLATION_FORMAT or isolation.get("version") != ISOLATION_VERSION or isolation.get("policy") != ISOLATION_POLICY:
        raise PhotoIdentityTargetCropQualityAttestationError("target-isolation authority format/version/policy is invalid")
    if public.get("format") != ENRICHMENT_FORMAT or public.get("version") != ENRICHMENT_VERSION:
        raise PhotoIdentityTargetCropQualityAttestationError("target-crop enrichment format/version is invalid")
    if private.get("format") != PRIVATE_ENRICHMENT_FORMAT or private.get("version") != PRIVATE_ENRICHMENT_VERSION:
        raise PhotoIdentityTargetCropQualityAttestationError("private target-crop enrichment format/version is invalid")
    for item in (isolation, public, private):
        if str(item.get("bodyrig_revision") or "") != revision:
            raise PhotoIdentityTargetCropQualityAttestationError("source-detail authority chain belongs to a different BodyRig revision")
    for field in ("performer_id", "scene_id"):
        if isolation.get(field) != public.get(field) or private.get(field) != public.get(field):
            raise PhotoIdentityTargetCropQualityAttestationError(f"source-detail authority chain differs on {field}")
    if public.get("human_target_isolation_attestation_sha256") != _sha256_file(isolation_path):
        raise PhotoIdentityTargetCropQualityAttestationError("target-crop enrichment is not bound to current human isolation receipt")
    if public.get("private_analysis_index_sha256") != _sha256_file(private_path):
        raise PhotoIdentityTargetCropQualityAttestationError("public/private target-crop enrichment binding changed")
    if isolation.get("target_isolated_source_authority") is not True or isolation.get("authority_scope") != "accepted-samples-only":
        raise PhotoIdentityTargetCropQualityAttestationError("source-detail attestation lacks accepted-samples-only target-isolation authority")
    if public.get("machine_observability_only") is not True or public.get("source_detail_quality_authority") is not False:
        raise PhotoIdentityTargetCropQualityAttestationError("target-crop enrichment crossed machine/source-quality authority boundary")
    for field in ("photoidentity_source_evidence_authority", "reconstruction_permitted", "production_activation"):
        if isolation.get(field) is not False or public.get(field) is not False:
            raise PhotoIdentityTargetCropQualityAttestationError(f"source-detail authority chain crossed downstream boundary: {field}")

    public_samples = _rows_by_id(public.get("samples"), label="public enrichment")
    private_samples = _rows_by_id(private.get("rows"), label="private enrichment")
    accepted_samples = _rows_by_id(isolation.get("accepted_samples"), label="human-isolated")
    selected: list[dict[str, Any]] = []
    private_root = (enrichment_root / "private-analysis").resolve()
    for sample_id, domain in _parse_refs(selected_refs):
        public_sample = public_samples.get(sample_id)
        private_sample = private_samples.get(sample_id)
        accepted_sample = accepted_samples.get(sample_id)
        if public_sample is None or private_sample is None or accepted_sample is None:
            raise PhotoIdentityTargetCropQualityAttestationError(f"selected source-detail sample is not in the human-isolated evidence chain: {sample_id}")
        expected_sha = str(public_sample.get("target_crop_sha256") or "")
        if expected_sha != str(accepted_sample.get("target_crop_sha256") or ""):
            raise PhotoIdentityTargetCropQualityAttestationError("selected source-detail crop hash differs from human isolation authority")
        crop = Path(str(private_sample.get("analysis_crop") or "")).expanduser().resolve()
        try:
            crop.relative_to(private_root)
        except ValueError as exc:
            raise PhotoIdentityTargetCropQualityAttestationError("selected source-detail crop escaped private enrichment root") from exc
        if _sha256_file(crop) != expected_sha:
            raise PhotoIdentityTargetCropQualityAttestationError("selected source-detail crop bytes changed after enrichment")

        candidate = _candidate_map(public_sample).get(domain)
        if candidate is None:
            raise PhotoIdentityTargetCropQualityAttestationError(f"selected domain has no machine observability candidate: {sample_id}:{domain}")
        score = _finite_quality(candidate.get("machine_observability_score"), label=f"{domain} machine observability score")
        if score < DETAIL_QUALITY_THRESHOLD:
            raise PhotoIdentityTargetCropQualityAttestationError(
                f"selected source detail is below canonical quality threshold: {sample_id}:{domain} score={score:.4f}"
            )
        expected_adapter, expected_revision = DOMAIN_MACHINE_AUTHORITY[domain]
        if (
            candidate.get("source_derived") is not True
            or str(candidate.get("adapter") or "") != expected_adapter
            or str(candidate.get("revision") or "") != expected_revision
            or candidate.get("source_detail_quality_authority") is not False
            or candidate.get("photoidentity_sufficiency_authority") is not False
        ):
            raise PhotoIdentityTargetCropQualityAttestationError(f"selected machine candidate has invalid source authority: {domain}")
        selected.append(
            {
                "sample_id": sample_id,
                "domain": domain,
                "scene_id": str(public["scene_id"]),
                "target_crop_sha256": expected_sha,
                "quality": round(score, 4),
                "machine_adapter": expected_adapter,
                "machine_revision": expected_revision,
                "source_derived": True,
                "adapter": ADAPTER,
                "revision": ADAPTER_REVISION,
            }
        )

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policy": POLICY,
        "bodyrig_revision": revision,
        "performer_id": str(public["performer_id"]),
        "scene_id": str(public["scene_id"]),
        "human_target_isolation_attestation_sha256": _sha256_file(isolation_path),
        "target_crop_detail_enrichment_sha256": _sha256_file(public_path),
        "private_analysis_index_sha256": _sha256_file(private_path),
        "adapter": ADAPTER,
        "adapter_revision": ADAPTER_REVISION,
        "selected_domains": sorted(item["domain"] for item in selected),
        "selected_claims": selected,
        "human_source_detail_quality_attested": True,
        "quality_note": note,
        "reviewed_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_detail_quality_authority": True,
        "photoidentity_source_evidence_authority": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    output = (output_path or (enrichment_root / "photoidentity-target-crop-detail-quality-attestation.json")).expanduser().resolve()
    if output.parent != enrichment_root:
        raise PhotoIdentityTargetCropQualityAttestationError("source-detail attestation must be published at the canonical enrichment root")
    _write_create_only(output, receipt)
    return {**receipt, "receipt": str(output), "receipt_sha256": _sha256_file(output)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record human source-detail quality authority for human-isolated target crops.")
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--enrichment-root", required=True)
    parser.add_argument("--detail-ref", action="append", default=[])
    parser.add_argument("--current-revision", required=True)
    parser.add_argument("--quality-note", required=True)
    parser.add_argument("--confirm-quality", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = record_target_crop_quality_attestation(
            candidate_root=Path(args.candidate_root),
            enrichment_root=Path(args.enrichment_root),
            selected_refs=args.detail_ref,
            current_revision=args.current_revision,
            quality_note=args.quality_note,
            confirm_quality=bool(args.confirm_quality),
        )
    except (OSError, PhotoIdentityTargetCropQualityAttestationError) as exc:
        print(f"BodyRig target-crop source-detail quality attestation: FAIL: {exc}", file=sys.stderr)
        return 1
    print("BodyRig target-crop source-detail quality attestation: RECORDED")
    print(f"Domains: {', '.join(result['selected_domains'])}")
    print(f"Receipt: {result['receipt']}")
    print("Source detail quality authority: TRUE")
    print("Photoidentity source evidence authority: FALSE")
    print("Reconstruction permitted: FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

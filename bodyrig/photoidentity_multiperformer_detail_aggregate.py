from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoidentity_authority import (
    validate_authoritative_bundle,
    validate_authoritative_observation_evidence,
)
from .photoidentity_evidence import (
    DETAIL_QUALITY_THRESHOLD,
    DOMAIN_REQUIREMENTS,
    PhotoIdentityEvidenceError,
    build_observation_evidence,
    evaluate_sufficiency,
    write_bundle,
)
from .photoidentity_multiperformer_target_attestation import (
    FORMAT as ISOLATION_FORMAT,
    POLICY as ISOLATION_POLICY,
    VERSION as ISOLATION_VERSION,
)
from .photoidentity_target_crop_detail import SUPPORTED_DOMAINS as TARGET_SUPPORTED_DOMAINS
from .photoidentity_target_crop_enrich import (
    FORMAT as ENRICHMENT_FORMAT,
    PRIVATE_FORMAT as PRIVATE_ENRICHMENT_FORMAT,
    PRIVATE_VERSION as PRIVATE_ENRICHMENT_VERSION,
    VERSION as ENRICHMENT_VERSION,
)
from .photoidentity_target_crop_quality_attestation import (
    ADAPTER as QUALITY_ADAPTER,
    ADAPTER_REVISION as QUALITY_ADAPTER_REVISION,
    DOMAIN_MACHINE_AUTHORITY,
    FORMAT as QUALITY_FORMAT,
    HUMAN_ONLY_DOMAINS,
    HUMAN_QUALITY_BASIS,
    POLICY as QUALITY_POLICY,
    SUPPORTED_QUALITY_DOMAINS,
    VERSION as QUALITY_VERSION,
)

FORMAT = "bodyrig-photoidentity-multiperformer-detail-aggregation"
VERSION = 1
POLICY_REVISION = "photoidentity-multiperformer-detail-aggregation-v1"
COMPOSITE_ADAPTER = "bodyrig-photoidentity-coarse-openpose-schp-human-target-detail-composite"
COMPOSITE_REVISION = "1"
BASE_ANALYZER = ("bodyrig-photoidentity-coarse-openpose-schp-composite", "1")
EVIDENCE_DIRNAME = "multiperformer-detail-evidence"
AUTHORITY_DIRNAME = "multiperformer-detail-source-authority"
RECEIPT_NAME = "photoidentity-multiperformer-detail-aggregation.json"
QUALITY_RECEIPT_NAME = "photoidentity-target-crop-detail-quality-attestation.json"
SUPPORTED_DOMAINS = frozenset(SUPPORTED_QUALITY_DOMAINS)


class PhotoIdentityMultiDetailAggregateError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityMultiDetailAggregateError(f"required multi-performer detail evidence is missing: {path}")
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
        raise PhotoIdentityMultiDetailAggregateError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityMultiDetailAggregateError(f"{label} must be a JSON object")
    return value


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentityMultiDetailAggregateError(f"multi-performer detail output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise PhotoIdentityMultiDetailAggregateError(f"multi-performer detail output already exists: {path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _canonical_sha(value: object, *, label: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise PhotoIdentityMultiDetailAggregateError(f"{label} is not a canonical SHA-256")
    return digest


def _quality(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotoIdentityMultiDetailAggregateError(f"{label} is not numeric")
    quality = float(value)
    if not math.isfinite(quality) or not 0.0 <= quality <= 1.0:
        raise PhotoIdentityMultiDetailAggregateError(f"{label} is outside 0..1")
    if quality < DETAIL_QUALITY_THRESHOLD:
        raise PhotoIdentityMultiDetailAggregateError(
            f"{label} is below source authority threshold {DETAIL_QUALITY_THRESHOLD:.2f}"
        )
    return round(quality, 4)


def _base_bundle(sweep_root: Path) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    observations_path = sweep_root / "human-parsing-evidence" / "photoidentity-observations.json"
    report_path = sweep_root / "human-parsing-evidence" / "photoidentity-evidence.json"
    try:
        report = validate_authoritative_bundle(report_path, observations_path, require_sufficient=False)
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityMultiDetailAggregateError(f"base human-parsing photoidentity evidence is invalid: {exc}") from exc
    observations = _read_json(observations_path, label="Base human-parsing photoidentity observations")
    analyzer = observations.get("analyzer")
    if not isinstance(analyzer, Mapping) or (
        str(analyzer.get("adapter") or ""), str(analyzer.get("revision") or "")
    ) != BASE_ANALYZER:
        raise PhotoIdentityMultiDetailAggregateError("multi-performer detail aggregation requires canonical SCHP base evidence")
    return observations_path, report_path, observations, report


def _rows_by_id(rows: object, *, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise PhotoIdentityMultiDetailAggregateError(f"{label} rows are invalid")
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityMultiDetailAggregateError(f"{label} row is invalid")
        sample_id = str(raw.get("sample_id") or "")
        if not sample_id.startswith("targetsample-") or sample_id in result:
            raise PhotoIdentityMultiDetailAggregateError(f"{label} sample id is invalid/duplicate")
        result[sample_id] = dict(raw)
    return result


def _candidate_map(sample: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw_candidates = sample.get("candidates")
    if not isinstance(raw_candidates, list):
        raise PhotoIdentityMultiDetailAggregateError("target-crop machine candidate list is invalid")
    result: dict[str, dict[str, Any]] = {}
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityMultiDetailAggregateError("target-crop machine candidate is invalid")
        domain = str(raw.get("domain") or "")
        if domain not in TARGET_SUPPORTED_DOMAINS or domain in result:
            raise PhotoIdentityMultiDetailAggregateError("target-crop machine domain is invalid/duplicate")
        result[domain] = dict(raw)
    return result


def _validate_human_only_claim(raw: Mapping[str, Any], *, domain: str) -> float:
    if domain not in HUMAN_ONLY_DOMAINS:
        raise PhotoIdentityMultiDetailAggregateError(f"human-only claim used for non-human domain: {domain}")
    if (
        raw.get("quality_basis") != HUMAN_QUALITY_BASIS
        or raw.get("human_visibility_attested") is not True
        or raw.get("machine_observability_used") is not False
    ):
        raise PhotoIdentityMultiDetailAggregateError(f"human-only hair claim authority boundary is invalid: {domain}")
    if "machine_adapter" in raw or "machine_revision" in raw:
        raise PhotoIdentityMultiDetailAggregateError(f"human-only hair claim must not carry machine authority: {domain}")
    return _quality(raw.get("quality"), label=f"{domain} human-reviewed source quality")


def _replay_quality_lineage(
    *,
    receipt_path: Path,
    candidate_root: Path,
    receipt: Mapping[str, Any],
    bodyrig_revision: str,
) -> None:
    candidate_root = candidate_root.expanduser().resolve()
    enrichment_root = receipt_path.parent.resolve()
    if receipt_path.name != QUALITY_RECEIPT_NAME:
        raise PhotoIdentityMultiDetailAggregateError("target-crop quality receipt filename is not canonical")
    if not candidate_root.is_dir() or not enrichment_root.is_dir():
        raise PhotoIdentityMultiDetailAggregateError("target-crop quality source roots are missing")

    isolation_path = candidate_root / "photoidentity-multiperformer-target-isolation-attestation.json"
    public_path = enrichment_root / "target-crop-detail-enrichment.json"
    private_path = enrichment_root / "private-analysis" / "private-analysis-index.json"
    isolation = _read_json(isolation_path, label="Human target-isolation attestation")
    public = _read_json(public_path, label="Target-crop detail enrichment")
    private = _read_json(private_path, label="Private target-crop detail enrichment")

    if (
        isolation.get("format") != ISOLATION_FORMAT
        or isolation.get("version") != ISOLATION_VERSION
        or isolation.get("policy") != ISOLATION_POLICY
    ):
        raise PhotoIdentityMultiDetailAggregateError("target-isolation authority format/version/policy is invalid")
    if public.get("format") != ENRICHMENT_FORMAT or public.get("version") != ENRICHMENT_VERSION:
        raise PhotoIdentityMultiDetailAggregateError("target-crop enrichment format/version is invalid")
    if private.get("format") != PRIVATE_ENRICHMENT_FORMAT or private.get("version") != PRIVATE_ENRICHMENT_VERSION:
        raise PhotoIdentityMultiDetailAggregateError("private target-crop enrichment format/version is invalid")
    for item in (isolation, public, private):
        if str(item.get("bodyrig_revision") or "") != bodyrig_revision:
            raise PhotoIdentityMultiDetailAggregateError("target-crop source lineage belongs to a different BodyRig revision")
    for field in ("performer_id", "scene_id"):
        if isolation.get(field) != public.get(field) or private.get(field) != public.get(field):
            raise PhotoIdentityMultiDetailAggregateError(f"target-crop source lineage differs on {field}")
        if str(receipt.get(field) or "") != str(public.get(field) or ""):
            raise PhotoIdentityMultiDetailAggregateError(f"target-crop quality receipt differs from source lineage on {field}")
    if receipt.get("human_target_isolation_attestation_sha256") != _sha256(isolation_path):
        raise PhotoIdentityMultiDetailAggregateError("target-crop quality receipt is not bound to current isolation receipt")
    if receipt.get("target_crop_detail_enrichment_sha256") != _sha256(public_path):
        raise PhotoIdentityMultiDetailAggregateError("target-crop quality receipt is not bound to current enrichment receipt")
    if receipt.get("private_analysis_index_sha256") != _sha256(private_path):
        raise PhotoIdentityMultiDetailAggregateError("target-crop quality receipt is not bound to current private analysis index")
    if public.get("human_target_isolation_attestation_sha256") != _sha256(isolation_path):
        raise PhotoIdentityMultiDetailAggregateError("target-crop enrichment is not bound to current human isolation receipt")
    if public.get("private_analysis_index_sha256") != _sha256(private_path):
        raise PhotoIdentityMultiDetailAggregateError("public/private target-crop enrichment binding changed")
    if isolation.get("target_isolated_source_authority") is not True or isolation.get("authority_scope") != "accepted-samples-only":
        raise PhotoIdentityMultiDetailAggregateError("target-crop lineage lacks accepted-samples-only target-isolation authority")
    if public.get("machine_observability_only") is not True or public.get("source_detail_quality_authority") is not False:
        raise PhotoIdentityMultiDetailAggregateError("target-crop enrichment crossed machine/source-quality authority boundary")
    for field in ("photoidentity_source_evidence_authority", "reconstruction_permitted", "production_activation"):
        if isolation.get(field) is not False or public.get(field) is not False:
            raise PhotoIdentityMultiDetailAggregateError(f"target-crop source lineage crossed downstream boundary: {field}")

    public_samples = _rows_by_id(public.get("samples"), label="public enrichment")
    private_samples = _rows_by_id(private.get("rows"), label="private enrichment")
    accepted_samples = _rows_by_id(isolation.get("accepted_samples"), label="human-isolated")
    raw_claims = receipt.get("selected_claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise PhotoIdentityMultiDetailAggregateError("target-crop quality receipt contains no selected claims")
    private_root = (enrichment_root / "private-analysis").resolve()
    for raw in raw_claims:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityMultiDetailAggregateError("target-crop quality claim is invalid")
        sample_id = str(raw.get("sample_id") or "")
        domain = str(raw.get("domain") or "")
        if domain not in SUPPORTED_DOMAINS:
            raise PhotoIdentityMultiDetailAggregateError(f"target-crop quality claim domain is unsupported: {domain}")
        public_sample = public_samples.get(sample_id)
        private_sample = private_samples.get(sample_id)
        accepted_sample = accepted_samples.get(sample_id)
        if public_sample is None or private_sample is None or accepted_sample is None:
            raise PhotoIdentityMultiDetailAggregateError(
                f"selected source-detail sample is not in the human-isolated evidence chain: {sample_id}"
            )
        expected_sha = str(public_sample.get("target_crop_sha256") or "")
        if expected_sha != str(accepted_sample.get("target_crop_sha256") or ""):
            raise PhotoIdentityMultiDetailAggregateError("selected source-detail crop hash differs from human isolation authority")
        if str(raw.get("target_crop_sha256") or "") != expected_sha:
            raise PhotoIdentityMultiDetailAggregateError("target-crop quality claim hash differs from current source crop")
        crop = Path(str(private_sample.get("analysis_crop") or "")).expanduser().resolve()
        try:
            crop.relative_to(private_root)
        except ValueError as exc:
            raise PhotoIdentityMultiDetailAggregateError("selected source-detail crop escaped private enrichment root") from exc
        if _sha256(crop) != expected_sha:
            raise PhotoIdentityMultiDetailAggregateError("selected source-detail crop bytes changed after enrichment")

        if domain in HUMAN_ONLY_DOMAINS:
            _validate_human_only_claim(raw, domain=domain)
            continue

        candidate = _candidate_map(public_sample).get(domain)
        if candidate is None:
            raise PhotoIdentityMultiDetailAggregateError(
                f"selected domain has no machine observability candidate: {sample_id}:{domain}"
            )
        expected_adapter, expected_revision = DOMAIN_MACHINE_AUTHORITY[domain]
        score = _quality(candidate.get("machine_observability_score"), label=f"{domain} machine observability score")
        if (
            candidate.get("source_derived") is not True
            or str(candidate.get("adapter") or "") != expected_adapter
            or str(candidate.get("revision") or "") != expected_revision
            or candidate.get("source_detail_quality_authority") is not False
            or candidate.get("photoidentity_sufficiency_authority") is not False
        ):
            raise PhotoIdentityMultiDetailAggregateError(f"selected machine candidate has invalid source authority: {domain}")
        if round(float(raw.get("quality", -1.0)), 4) != score:
            raise PhotoIdentityMultiDetailAggregateError("target-crop quality claim score differs from current machine candidate")
        if (
            str(raw.get("machine_adapter") or "") != expected_adapter
            or str(raw.get("machine_revision") or "") != expected_revision
        ):
            raise PhotoIdentityMultiDetailAggregateError("target-crop quality claim machine provenance changed")


def _validate_quality_receipt(
    path: Path,
    *,
    performer_id: str,
    bodyrig_revision: str,
    candidate_root: Path | None = None,
    replay_source: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    receipt = _read_json(path, label="Target-crop source-detail quality receipt")
    if (
        receipt.get("format") != QUALITY_FORMAT
        or receipt.get("version") != QUALITY_VERSION
        or receipt.get("policy") != QUALITY_POLICY
        or receipt.get("adapter") != QUALITY_ADAPTER
        or receipt.get("adapter_revision") != QUALITY_ADAPTER_REVISION
        or receipt.get("human_source_detail_quality_attested") is not True
        or receipt.get("source_detail_quality_authority") is not True
        or receipt.get("photoidentity_source_evidence_authority") is not False
        or receipt.get("generic_guessing_permitted") is not False
        or receipt.get("reconstruction_permitted") is not False
        or receipt.get("production_activation") is not False
    ):
        raise PhotoIdentityMultiDetailAggregateError("target-crop source-detail quality receipt authority boundary is invalid")
    if str(receipt.get("performer_id") or "") != performer_id:
        raise PhotoIdentityMultiDetailAggregateError("target-crop quality receipt belongs to a different performer")
    if str(receipt.get("bodyrig_revision") or "") != bodyrig_revision:
        raise PhotoIdentityMultiDetailAggregateError("target-crop quality receipt belongs to a different BodyRig revision")
    scene_id = str(receipt.get("scene_id") or "").strip()
    if not scene_id or len(scene_id) > 256:
        raise PhotoIdentityMultiDetailAggregateError("target-crop quality receipt scene identity is invalid")
    for field in (
        "human_target_isolation_attestation_sha256",
        "target_crop_detail_enrichment_sha256",
        "private_analysis_index_sha256",
    ):
        _canonical_sha(receipt.get(field), label=field)
    note = str(receipt.get("quality_note") or "").strip()
    if len(note) < 20 or (note.startswith("<") and note.endswith(">")):
        raise PhotoIdentityMultiDetailAggregateError("target-crop quality receipt lacks a real human source-review note")

    raw_claims = receipt.get("selected_claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise PhotoIdentityMultiDetailAggregateError("target-crop quality receipt contains no selected claims")
    domains: set[str] = set()
    claims: list[dict[str, Any]] = []
    for raw in raw_claims:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityMultiDetailAggregateError("target-crop quality claim is invalid")
        domain = str(raw.get("domain") or "")
        if domain not in SUPPORTED_DOMAINS or domain in domains:
            raise PhotoIdentityMultiDetailAggregateError("target-crop quality claim domain is invalid/duplicate")
        domains.add(domain)
        if str(raw.get("scene_id") or "") != scene_id:
            raise PhotoIdentityMultiDetailAggregateError("target-crop quality claim scene differs from receipt")
        if raw.get("source_derived") is not True:
            raise PhotoIdentityMultiDetailAggregateError("target-crop quality claim is not source-derived")
        if str(raw.get("adapter") or "") != QUALITY_ADAPTER or str(raw.get("revision") or "") != QUALITY_ADAPTER_REVISION:
            raise PhotoIdentityMultiDetailAggregateError("target-crop quality claim human adapter/revision changed")
        if domain in HUMAN_ONLY_DOMAINS:
            quality = _validate_human_only_claim(raw, domain=domain)
        else:
            machine_adapter, machine_revision = DOMAIN_MACHINE_AUTHORITY[domain]
            if str(raw.get("machine_adapter") or "") != machine_adapter or str(raw.get("machine_revision") or "") != machine_revision:
                raise PhotoIdentityMultiDetailAggregateError("target-crop quality claim machine provenance changed")
            quality = _quality(raw.get("quality"), label=f"{domain} quality")
        _canonical_sha(raw.get("target_crop_sha256"), label="target-crop SHA-256")
        claims.append(
            {
                "scene_id": scene_id,
                "quality": quality,
                "source_derived": True,
                "adapter": QUALITY_ADAPTER,
                "revision": QUALITY_ADAPTER_REVISION,
                "domain": domain,
            }
        )
    if set(receipt.get("selected_domains") or []) != domains:
        raise PhotoIdentityMultiDetailAggregateError("target-crop quality receipt selected-domain summary changed")
    if replay_source:
        if candidate_root is None:
            raise PhotoIdentityMultiDetailAggregateError("target-crop quality aggregation requires the corresponding candidate root")
        _replay_quality_lineage(
            receipt_path=path,
            candidate_root=candidate_root,
            receipt=receipt,
            bodyrig_revision=bodyrig_revision,
        )
    return receipt, sorted(claims, key=lambda item: item["domain"])


def _claim_without_domain(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scene_id": str(value["scene_id"]),
        "quality": round(float(value["quality"]), 4),
        "source_derived": True,
        "adapter": str(value["adapter"]),
        "revision": str(value["revision"]),
    }


def _merge_details(
    prior: Mapping[str, Any],
    new_claims: Sequence[Mapping[str, Any]],
    *,
    prior_rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, list[dict[str, Any]]] = {
        str(domain): [dict(item) for item in claims if isinstance(item, Mapping)]
        for domain, claims in prior.items()
        if isinstance(claims, list)
    }
    prior_row_scenes = {str(item.get("scene_id") or "") for item in prior_rows if isinstance(item, Mapping)}
    seen_new: set[tuple[str, str]] = set()
    for raw in new_claims:
        domain = str(raw["domain"])
        scene = str(raw["scene_id"])
        key = (domain, scene)
        if key in seen_new:
            raise PhotoIdentityMultiDetailAggregateError(f"duplicate multi-performer quality authority for {domain} in scene {scene}")
        seen_new.add(key)
        if scene in prior_row_scenes:
            raise PhotoIdentityMultiDetailAggregateError(
                f"multi-performer source scene overlaps the single-performer observation pool: {scene}"
            )
        existing = merged.setdefault(domain, [])
        if any(str(item.get("scene_id") or "") == scene for item in existing if isinstance(item, Mapping)):
            raise PhotoIdentityMultiDetailAggregateError(
                f"multi-performer source duplicates existing {domain} authority for scene {scene}"
            )
        existing.append(_claim_without_domain(raw))
    for claims in merged.values():
        claims.sort(
            key=lambda item: (
                str(item.get("scene_id") or ""),
                str(item.get("adapter") or ""),
                str(item.get("revision") or ""),
            )
        )
    return merged


def _expected_enriched(
    prior_observations: Mapping[str, Any],
    new_claims: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    analyzer = prior_observations.get("analyzer")
    details = prior_observations.get("detail_evidence")
    if not isinstance(analyzer, Mapping) or not isinstance(details, Mapping):
        raise PhotoIdentityMultiDetailAggregateError("base photoidentity analyzer/detail evidence is invalid")
    merged = _merge_details(details, new_claims, prior_rows=list(prior_observations.get("rows") or []))
    capabilities = {str(item) for item in analyzer.get("capabilities", [])}
    for raw in new_claims:
        domain = str(raw.get("domain") or "")
        if domain in HUMAN_ONLY_DOMAINS:
            capabilities.add(str(DOMAIN_REQUIREMENTS[domain]["capability"]))
    return build_observation_evidence(
        performer_id=str(prior_observations["performer_id"]),
        bodyrig_revision=str(prior_observations["bodyrig_revision"]),
        baseline_source_manifest_sha256=str(prior_observations["baseline_source_manifest_sha256"]),
        analyzer_adapter=COMPOSITE_ADAPTER,
        analyzer_revision=COMPOSITE_REVISION,
        analyzer_capabilities=sorted(capabilities),
        candidate_scenes=int(prior_observations["candidate_scenes"]),
        source_files_scanned=int(prior_observations["source_files_scanned"]),
        scan_exhausted=bool(prior_observations["scan_exhausted"]),
        rows=list(prior_observations["rows"]),
        detail_evidence=merged,
    )


def _require_target_detail_complete(evidence: Mapping[str, Any]) -> dict[str, Any]:
    try:
        validate_authoritative_observation_evidence(evidence)
        report = evaluate_sufficiency(evidence)
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityMultiDetailAggregateError(f"candidate aggregate authority is invalid: {exc}") from exc
    incomplete = {
        domain: report["domains"][domain]
        for domain in sorted(SUPPORTED_DOMAINS)
        if report["domains"][domain]["status"] != "pass"
    }
    if incomplete:
        detail = ", ".join(
            f"{domain}={item['qualifying_distinct_scenes']}/{item['minimum_distinct_scenes']} ({item['status']})"
            for domain, item in incomplete.items()
        )
        raise PhotoIdentityMultiDetailAggregateError(
            "multi-performer detail aggregation would publish incomplete create-only target-detail evidence: " + detail
        )
    return report


def aggregate_multiperformer_detail_evidence(
    *,
    sweep_root: Path,
    quality_receipts: Sequence[Path],
    candidate_roots: Sequence[Path] | None = None,
) -> dict[str, Any]:
    sweep_root = sweep_root.expanduser().resolve()
    if not sweep_root.is_dir():
        raise PhotoIdentityMultiDetailAggregateError("photoidentity sweep root is missing")
    if not quality_receipts:
        raise PhotoIdentityMultiDetailAggregateError("at least one target-crop quality receipt is required")
    if candidate_roots is None or len(candidate_roots) != len(quality_receipts):
        raise PhotoIdentityMultiDetailAggregateError(
            "each target-crop quality receipt requires its corresponding human-isolation candidate root"
        )
    observations_path, report_path, prior_observations, prior_report = _base_bundle(sweep_root)

    parsed_receipts: list[tuple[Path, dict[str, Any], list[dict[str, Any]], str]] = []
    all_claims: list[dict[str, Any]] = []
    receipt_hashes: set[str] = set()
    for raw_path, raw_candidate_root in zip(quality_receipts, candidate_roots):
        path = raw_path.expanduser().resolve()
        receipt, claims = _validate_quality_receipt(
            path,
            performer_id=str(prior_report["performer_id"]),
            bodyrig_revision=str(prior_report["bodyrig_revision"]),
            candidate_root=raw_candidate_root,
            replay_source=True,
        )
        digest = _sha256(path)
        if digest in receipt_hashes:
            raise PhotoIdentityMultiDetailAggregateError("duplicate target-crop quality receipt was supplied")
        receipt_hashes.add(digest)
        parsed_receipts.append((path, receipt, claims, digest))
        all_claims.extend(claims)
    expected = _expected_enriched(prior_observations, all_claims)

    # Aggregation is create-only. Prove the entire target-detail scope in memory
    # before creating any output path, otherwise a partial publication would
    # permanently prevent adding the missing source scenes later.
    _require_target_detail_complete(expected)

    evidence_root = sweep_root / EVIDENCE_DIRNAME
    authority_root = sweep_root / AUTHORITY_DIRNAME
    aggregate_receipt_path = sweep_root / RECEIPT_NAME
    if evidence_root.exists() or authority_root.exists() or aggregate_receipt_path.exists():
        raise PhotoIdentityMultiDetailAggregateError("multi-performer detail aggregation is create-only")
    copied_receipts: list[dict[str, Any]] = []
    try:
        enriched_observations_path, enriched_report_path, enriched_report = write_bundle(evidence_root, expected)
        validate_authoritative_bundle(
            enriched_report_path,
            enriched_observations_path,
            require_sufficient=False,
            expected_performer_id=str(prior_report["performer_id"]),
            expected_bodyrig_revision=str(prior_report["bodyrig_revision"]),
            expected_baseline_source_manifest_sha256=str(prior_report["baseline_source_manifest_sha256"]),
        )
        authority_root.mkdir(parents=True, exist_ok=False)
        for path, receipt, claims, digest in sorted(parsed_receipts, key=lambda item: item[3]):
            stored_name = f"quality-{digest}.json"
            stored_path = authority_root / stored_name
            shutil.copyfile(path, stored_path)
            if _sha256(stored_path) != digest:
                raise PhotoIdentityMultiDetailAggregateError("copied target-crop quality receipt hash mismatch")
            copied_receipts.append(
                {
                    "receipt_sha256": digest,
                    "stored_name": stored_name,
                    "scene_id": str(receipt["scene_id"]),
                    "domains": sorted(str(item["domain"]) for item in claims),
                }
            )
        aggregate_receipt = {
            "format": FORMAT,
            "version": VERSION,
            "policy_revision": POLICY_REVISION,
            "performer_id": str(prior_report["performer_id"]),
            "bodyrig_revision": str(prior_report["bodyrig_revision"]),
            "baseline_source_manifest_sha256": str(prior_report["baseline_source_manifest_sha256"]),
            "prior_stage": "human-parsing",
            "prior_observation_evidence_sha256": _sha256(observations_path),
            "prior_sufficiency_report_sha256": _sha256(report_path),
            "quality_receipts": copied_receipts,
            "quality_receipt_count": len(copied_receipts),
            "added_claim_counts": {
                domain: sum(1 for item in all_claims if item["domain"] == domain)
                for domain in sorted(SUPPORTED_DOMAINS)
            },
            "composite_analyzer": {
                "adapter": COMPOSITE_ADAPTER,
                "revision": COMPOSITE_REVISION,
                "capabilities": list(expected["analyzer"]["capabilities"]),
            },
            "enriched_observation_evidence_sha256": _sha256(enriched_observations_path),
            "enriched_sufficiency_report_sha256": _sha256(enriched_report_path),
            "source_grounded": True,
            "generic_guessing_permitted": False,
            "production_activation": False,
        }
        _write_create_only(aggregate_receipt_path, aggregate_receipt)
        return {
            **aggregate_receipt,
            "receipt": str(aggregate_receipt_path),
            "enriched_observation_evidence": str(enriched_observations_path),
            "enriched_sufficiency_report": str(enriched_report_path),
            "report": enriched_report,
        }
    except Exception:
        shutil.rmtree(evidence_root, ignore_errors=True)
        shutil.rmtree(authority_root, ignore_errors=True)
        aggregate_receipt_path.unlink(missing_ok=True)
        raise


def validate_multiperformer_detail_aggregation(sweep_root: Path) -> dict[str, Any] | None:
    sweep_root = sweep_root.expanduser().resolve()
    evidence_root = sweep_root / EVIDENCE_DIRNAME
    authority_root = sweep_root / AUTHORITY_DIRNAME
    receipt_path = sweep_root / RECEIPT_NAME
    observations_path = evidence_root / "photoidentity-observations.json"
    report_path = evidence_root / "photoidentity-evidence.json"
    present = [receipt_path.exists(), observations_path.exists(), report_path.exists(), authority_root.exists()]
    if not any(present):
        return None
    if not all(present) or not authority_root.is_dir():
        raise PhotoIdentityMultiDetailAggregateError("partial multi-performer detail aggregation state exists")

    base_observations_path, base_report_path, base_observations, base_report = _base_bundle(sweep_root)
    receipt = _read_json(receipt_path, label="Multi-performer detail aggregation receipt")
    if (
        receipt.get("format") != FORMAT
        or receipt.get("version") != VERSION
        or receipt.get("policy_revision") != POLICY_REVISION
        or receipt.get("prior_stage") != "human-parsing"
        or receipt.get("source_grounded") is not True
        or receipt.get("generic_guessing_permitted") is not False
        or receipt.get("production_activation") is not False
    ):
        raise PhotoIdentityMultiDetailAggregateError("multi-performer detail aggregation receipt authority boundary is invalid")
    for field in ("performer_id", "bodyrig_revision", "baseline_source_manifest_sha256"):
        if str(receipt.get(field) or "") != str(base_report[field]):
            raise PhotoIdentityMultiDetailAggregateError(f"multi-performer detail aggregation differs from base authority: {field}")
    if receipt.get("prior_observation_evidence_sha256") != _sha256(base_observations_path):
        raise PhotoIdentityMultiDetailAggregateError("multi-performer detail aggregation prior observation binding changed")
    if receipt.get("prior_sufficiency_report_sha256") != _sha256(base_report_path):
        raise PhotoIdentityMultiDetailAggregateError("multi-performer detail aggregation prior report binding changed")

    raw_entries = receipt.get("quality_receipts")
    if not isinstance(raw_entries, list) or not raw_entries or receipt.get("quality_receipt_count") != len(raw_entries):
        raise PhotoIdentityMultiDetailAggregateError("multi-performer detail quality receipt manifest is invalid")
    all_claims: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    normalized_entries: list[dict[str, Any]] = []
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityMultiDetailAggregateError("multi-performer quality receipt manifest row is invalid")
        digest = _canonical_sha(raw.get("receipt_sha256"), label="quality receipt SHA-256")
        if digest in seen_hashes:
            raise PhotoIdentityMultiDetailAggregateError("multi-performer quality receipt manifest contains duplicate hash")
        seen_hashes.add(digest)
        expected_name = f"quality-{digest}.json"
        if str(raw.get("stored_name") or "") != expected_name:
            raise PhotoIdentityMultiDetailAggregateError("multi-performer quality receipt stored name is not canonical")
        stored_path = authority_root / expected_name
        if _sha256(stored_path) != digest:
            raise PhotoIdentityMultiDetailAggregateError("persisted multi-performer quality receipt hash mismatch")
        quality_receipt, claims = _validate_quality_receipt(
            stored_path,
            performer_id=str(base_report["performer_id"]),
            bodyrig_revision=str(base_report["bodyrig_revision"]),
            replay_source=False,
        )
        domains = sorted(str(item["domain"]) for item in claims)
        if str(raw.get("scene_id") or "") != str(quality_receipt["scene_id"]) or list(raw.get("domains") or []) != domains:
            raise PhotoIdentityMultiDetailAggregateError("multi-performer quality receipt manifest metadata changed")
        normalized_entries.append(
            {
                "receipt_sha256": digest,
                "stored_name": expected_name,
                "scene_id": str(quality_receipt["scene_id"]),
                "domains": domains,
            }
        )
        all_claims.extend(claims)
    if normalized_entries != raw_entries:
        raise PhotoIdentityMultiDetailAggregateError("multi-performer quality receipt manifest ordering/content is non-canonical")

    expected = _expected_enriched(base_observations, all_claims)
    _require_target_detail_complete(expected)
    enriched_observations = _read_json(observations_path, label="Aggregated multi-performer photoidentity observations")
    if enriched_observations != expected:
        raise PhotoIdentityMultiDetailAggregateError("aggregated multi-performer observations do not match quality receipts")
    try:
        enriched_report = validate_authoritative_bundle(
            report_path,
            observations_path,
            require_sufficient=False,
            expected_performer_id=str(base_report["performer_id"]),
            expected_bodyrig_revision=str(base_report["bodyrig_revision"]),
            expected_baseline_source_manifest_sha256=str(base_report["baseline_source_manifest_sha256"]),
        )
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityMultiDetailAggregateError(f"aggregated multi-performer evidence is invalid: {exc}") from exc
    if receipt.get("enriched_observation_evidence_sha256") != _sha256(observations_path):
        raise PhotoIdentityMultiDetailAggregateError("multi-performer aggregation no longer binds enriched observations")
    if receipt.get("enriched_sufficiency_report_sha256") != _sha256(report_path):
        raise PhotoIdentityMultiDetailAggregateError("multi-performer aggregation no longer binds enriched sufficiency report")
    expected_counts = {
        domain: sum(1 for item in all_claims if item["domain"] == domain)
        for domain in sorted(SUPPORTED_DOMAINS)
    }
    if receipt.get("added_claim_counts") != expected_counts:
        raise PhotoIdentityMultiDetailAggregateError("multi-performer aggregation claim-count summary changed")
    analyzer = receipt.get("composite_analyzer")
    if analyzer != expected["analyzer"]:
        raise PhotoIdentityMultiDetailAggregateError("multi-performer aggregation composite analyzer summary changed")
    return {
        "receipt": receipt,
        "receipt_path": receipt_path,
        "observations_path": observations_path,
        "report_path": report_path,
        "report": enriched_report,
        "quality_receipt_paths": [authority_root / str(item["stored_name"]) for item in normalized_entries],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate human-quality-attested multi-performer target-crop claims into photoidentity evidence."
    )
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--quality-receipt", action="append", default=[])
    parser.add_argument("--candidate-root", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        result = aggregate_multiperformer_detail_evidence(
            sweep_root=Path(args.sweep_root),
            quality_receipts=[Path(value) for value in args.quality_receipt],
            candidate_roots=[Path(value) for value in args.candidate_root],
        )
    except (OSError, PhotoIdentityMultiDetailAggregateError) as exc:
        print(f"BodyRig multi-performer detail aggregation: FAIL: {exc}", file=sys.stderr)
        return 1
    report = result["report"]
    print(
        "BodyRig multi-performer detail aggregation: PASS | "
        f"quality_receipts={result['quality_receipt_count']} | "
        f"source_sufficient={str(bool(report['source_evidence_sufficient'])).lower()}"
    )
    print(f"Receipt: {result['receipt']}")
    print(f"Updated sufficiency: {result['enriched_sufficiency_report']}")
    print("Nail/anatomy authority: NOT CHANGED")
    print("Production activation: FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

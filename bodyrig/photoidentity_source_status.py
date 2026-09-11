from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_authority import PhotoIdentityAuthorityError, validate_authoritative_bundle
from .photoidentity_evidence import DETAIL_QUALITY_THRESHOLD, DOMAIN_REQUIREMENTS
from .photoidentity_multiperformer_detail_aggregate import (
    PhotoIdentityMultiDetailAggregateError,
    validate_multiperformer_detail_aggregation,
)
from .photoidentity_multiperformer_review_prepare import (
    FORMAT as MULTI_REVIEW_FORMAT,
    PRIVATE_FORMAT as MULTI_REVIEW_PRIVATE_FORMAT,
    PRIVATE_VERSION as MULTI_REVIEW_PRIVATE_VERSION,
    VERSION as MULTI_REVIEW_VERSION,
)
from .photoidentity_multiperformer_source_discovery import (
    FORMAT as MULTI_DISCOVERY_FORMAT,
    PRIVATE_FORMAT as MULTI_DISCOVERY_PRIVATE_FORMAT,
    PRIVATE_VERSION as MULTI_DISCOVERY_PRIVATE_VERSION,
    VERSION as MULTI_DISCOVERY_VERSION,
)
from .photoidentity_registry import (
    DIRNAME as REGISTRY_DIRNAME,
    PhotoIdentityRegistryError,
    _job_authority,
    require_body_job_photoidentity_evidence,
)
from .photoidentity_source_chain import PhotoIdentitySourceChainError, validate_registration_source_chain
from .photoidentity_target_crop_quality_attestation import (
    ADAPTER as TARGET_DETAIL_ADAPTER,
    ADAPTER_REVISION as TARGET_DETAIL_REVISION,
    FORMAT as TARGET_DETAIL_FORMAT,
    SUPPORTED_QUALITY_DOMAINS,
    VERSION as TARGET_DETAIL_VERSION,
)

FORMAT = "bodyrig-photoidentity-source-status"
VERSION = 1


class PhotoIdentitySourceStatusError(RuntimeError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentitySourceStatusError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentitySourceStatusError(f"{label} must be a JSON object")
    return value


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentitySourceStatusError(f"required source-status file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pair_state(paths: tuple[Path, ...], *, label: str) -> bool:
    present = [path.exists() for path in paths]
    if any(present) and not all(present):
        raise PhotoIdentitySourceStatusError(f"partial {label} state exists; refusing ambiguous source authority")
    return all(present)


def _stage(
    *,
    sweep_root: Path,
    base_report: Mapping[str, Any],
    name: str,
    next_action: str,
    human_review_required: bool = False,
    final_report: Mapping[str, Any] | None = None,
    body_job_id: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = dict(final_report or base_report)
    result = {
        "format": FORMAT,
        "version": VERSION,
        "stage": name,
        "next_action": next_action,
        "performer_id": str(base_report["performer_id"]),
        "bodyrig_revision": str(base_report["bodyrig_revision"]),
        "baseline_source_manifest_sha256": str(base_report["baseline_source_manifest_sha256"]),
        "sweep_root": str(sweep_root),
        "body_job_id": body_job_id,
        "source_evidence_sufficient": bool(report.get("source_evidence_sufficient", False)),
        "reconstruction_source_permitted": bool(report.get("reconstruction_permitted", False)),
        "human_review_required": bool(human_review_required),
        "avatar_render_permitted": name == "registered",
        "generic_guessing_permitted": False,
        "production_activation": False,
    }
    if extra:
        result.update(dict(extra))
    return result


def _assert_same_identity(value: Mapping[str, Any], *, base_report: Mapping[str, Any], label: str) -> None:
    if str(value.get("performer_id") or "") != str(base_report["performer_id"]):
        raise PhotoIdentitySourceStatusError(f"{label} belongs to a different performer")
    if str(value.get("bodyrig_revision") or "") != str(base_report["bodyrig_revision"]):
        raise PhotoIdentitySourceStatusError(f"{label} belongs to a different BodyRig revision")


def _quality_receipt_claims(
    path: Path,
    *,
    base_report: Mapping[str, Any],
) -> dict[str, set[str]]:
    value = _read_json(path, label="Target-crop source-detail quality receipt")
    if (
        value.get("format") != TARGET_DETAIL_FORMAT
        or value.get("version") != TARGET_DETAIL_VERSION
        or value.get("adapter") != TARGET_DETAIL_ADAPTER
        or value.get("adapter_revision") != TARGET_DETAIL_REVISION
        or value.get("human_source_detail_quality_attested") is not True
        or value.get("source_detail_quality_authority") is not True
        or value.get("photoidentity_source_evidence_authority") is not False
        or value.get("generic_guessing_permitted") is not False
        or value.get("reconstruction_permitted") is not False
        or value.get("production_activation") is not False
    ):
        raise PhotoIdentitySourceStatusError("target-crop source-detail quality receipt authority boundary is invalid")
    _assert_same_identity(value, base_report=base_report, label="Target-crop source-detail quality receipt")
    raw_claims = value.get("selected_claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise PhotoIdentitySourceStatusError("target-crop source-detail quality receipt has no selected claims")
    result: dict[str, set[str]] = {}
    for raw in raw_claims:
        if not isinstance(raw, Mapping):
            raise PhotoIdentitySourceStatusError("target-crop source-detail quality claim is invalid")
        domain = str(raw.get("domain") or "")
        scene_id = str(raw.get("scene_id") or "").strip()
        if domain not in SUPPORTED_QUALITY_DOMAINS or not scene_id:
            raise PhotoIdentitySourceStatusError("target-crop source-detail quality claim domain/scene is invalid")
        if raw.get("source_derived") is not True:
            raise PhotoIdentitySourceStatusError("target-crop source-detail quality claim is not source-derived")
        quality = raw.get("quality")
        if isinstance(quality, bool) or not isinstance(quality, (int, float)):
            raise PhotoIdentitySourceStatusError("target-crop source-detail quality claim is non-numeric")
        numeric = float(quality)
        if not math.isfinite(numeric) or not DETAIL_QUALITY_THRESHOLD <= numeric <= 1.0:
            raise PhotoIdentitySourceStatusError("target-crop source-detail quality claim is below authority threshold")
        result.setdefault(domain, set()).add(scene_id)
    return result


def _target_detail_progress(
    *,
    base_report: Mapping[str, Any],
    quality_claims: Mapping[str, set[str]],
) -> tuple[dict[str, dict[str, int]], list[str]]:
    domains = base_report.get("domains")
    if not isinstance(domains, Mapping):
        raise PhotoIdentitySourceStatusError("base photoidentity sufficiency report has invalid domain status")
    progress: dict[str, dict[str, int]] = {}
    missing: list[str] = []
    for domain in sorted(SUPPORTED_QUALITY_DOMAINS):
        requirement = DOMAIN_REQUIREMENTS.get(domain)
        domain_report = domains.get(domain)
        if not isinstance(requirement, Mapping) or not isinstance(domain_report, Mapping):
            raise PhotoIdentitySourceStatusError(f"target-detail domain contract is missing: {domain}")
        minimum = int(requirement["minimum_distinct_scenes"])
        base_count = int(domain_report.get("qualifying_distinct_scenes", 0))
        reviewed_count = len(quality_claims.get(domain, set()))
        observed = base_count + reviewed_count
        remaining = max(0, minimum - observed)
        progress[domain] = {
            "minimum_distinct_scenes": minimum,
            "base_qualifying_scenes": base_count,
            "reviewed_multiperformer_scenes": reviewed_count,
            "remaining_scenes": remaining,
        }
        if remaining:
            missing.append(domain)
    return progress, missing


def _inspect_multiperformer_pending(
    *,
    sweep_root: Path,
    base_report: Mapping[str, Any],
    multiperformer_root: Path | None,
) -> dict[str, Any]:
    if multiperformer_root is None:
        return _stage(
            sweep_root=sweep_root,
            base_report=base_report,
            name="multiperformer-discovery",
            next_action="discover_multiperformer_sources",
            extra={"multiperformer_root": None},
        )

    root = multiperformer_root.expanduser().resolve()
    if not root.is_dir():
        raise PhotoIdentitySourceStatusError(f"multi-performer workflow root is missing: {root}")

    discovery_path = root / "multiperformer-source-candidates.json"
    private_discovery_path = root / "private-multiperformer-source-candidates" / "private-candidate-index.json"
    if not _pair_state((discovery_path, private_discovery_path), label="multi-performer discovery"):
        return _stage(
            sweep_root=sweep_root,
            base_report=base_report,
            name="multiperformer-discovery",
            next_action="discover_multiperformer_sources",
            extra={"multiperformer_root": str(root)},
        )

    discovery = _read_json(discovery_path, label="Multi-performer source discovery")
    private_discovery = _read_json(private_discovery_path, label="Private multi-performer source discovery")
    if (
        discovery.get("format") != MULTI_DISCOVERY_FORMAT
        or discovery.get("version") != MULTI_DISCOVERY_VERSION
        or discovery.get("stash_inventory_exhausted") is not True
        or discovery.get("target_track_selected") is not False
        or discovery.get("generic_guessing_permitted") is not False
        or discovery.get("reconstruction_permitted") is not False
        or discovery.get("production_activation") is not False
    ):
        raise PhotoIdentitySourceStatusError("multi-performer discovery authority boundary is invalid")
    if (
        private_discovery.get("format") != MULTI_DISCOVERY_PRIVATE_FORMAT
        or private_discovery.get("version") != MULTI_DISCOVERY_PRIVATE_VERSION
        or private_discovery.get("public_manifest_sha256") != _sha256(discovery_path)
    ):
        raise PhotoIdentitySourceStatusError("private multi-performer discovery authority is invalid")
    _assert_same_identity(discovery, base_report=base_report, label="Multi-performer discovery")
    _assert_same_identity(private_discovery, base_report=base_report, label="Private multi-performer discovery")

    raw_candidates = discovery.get("candidates")
    if not isinstance(raw_candidates, list):
        raise PhotoIdentitySourceStatusError("multi-performer discovery candidate list is invalid")
    candidate_ids = sorted(
        str(item.get("candidate_id") or "")
        for item in raw_candidates
        if isinstance(item, Mapping) and str(item.get("candidate_id") or "")
    )
    if len(set(candidate_ids)) != len(candidate_ids) or int(discovery.get("candidate_count", -1)) != len(candidate_ids):
        raise PhotoIdentitySourceStatusError("multi-performer discovery candidate count/set changed")
    if not candidate_ids:
        return _stage(
            sweep_root=sweep_root,
            base_report=base_report,
            name="multiperformer-source-insufficient",
            next_action="capture_or_add_multiperformer_source_media",
            human_review_required=True,
            extra={
                "multiperformer_root": str(root),
                "missing_target_domains": sorted(SUPPORTED_QUALITY_DOMAINS),
                "available_source_candidate_ids": [],
            },
        )

    reviews_parent = root / "track-reviews"
    if not reviews_parent.exists():
        return _stage(
            sweep_root=sweep_root,
            base_report=base_report,
            name="multiperformer-track-review-prepare",
            next_action="prepare_multiperformer_track_review",
            human_review_required=True,
            extra={
                "multiperformer_root": str(root),
                "available_source_candidate_ids": candidate_ids,
                "reviewed_source_candidate_ids": [],
            },
        )
    if not reviews_parent.is_dir():
        raise PhotoIdentitySourceStatusError("multi-performer track-reviews path is not a directory")

    review_roots = sorted(path for path in reviews_parent.iterdir() if path.is_dir())
    if not review_roots:
        return _stage(
            sweep_root=sweep_root,
            base_report=base_report,
            name="multiperformer-track-review-prepare",
            next_action="prepare_multiperformer_track_review",
            human_review_required=True,
            extra={
                "multiperformer_root": str(root),
                "available_source_candidate_ids": candidate_ids,
                "reviewed_source_candidate_ids": [],
            },
        )

    reviewed_source_ids: set[str] = set()
    pending_track_review: list[str] = []
    pending_materialize: list[str] = []
    pending_isolation_review: list[str] = []
    pending_enrichment: list[str] = []
    pending_quality_review: list[str] = []
    quality_receipts: list[str] = []
    candidate_roots: list[str] = []
    quality_claims: dict[str, set[str]] = {}

    for review_root in review_roots:
        public_review_path = review_root / "multiperformer-track-review-candidates.json"
        private_review_path = review_root / "private-track-review" / "private-review-index.json"
        if not _pair_state((public_review_path, private_review_path), label=f"multi-performer track review {review_root.name}"):
            raise PhotoIdentitySourceStatusError(
                f"track review directory exists without complete public/private authority: {review_root}"
            )
        public_review = _read_json(public_review_path, label="Multi-performer track review")
        private_review = _read_json(private_review_path, label="Private multi-performer track review")
        if (
            public_review.get("format") != MULTI_REVIEW_FORMAT
            or public_review.get("version") != MULTI_REVIEW_VERSION
            or public_review.get("target_track_selected") is not False
            or public_review.get("generic_guessing_permitted") is not False
            or public_review.get("reconstruction_permitted") is not False
            or public_review.get("production_activation") is not False
        ):
            raise PhotoIdentitySourceStatusError("multi-performer track review authority boundary is invalid")
        if (
            private_review.get("format") != MULTI_REVIEW_PRIVATE_FORMAT
            or private_review.get("version") != MULTI_REVIEW_PRIVATE_VERSION
            or private_review.get("public_review_manifest_sha256") != _sha256(public_review_path)
        ):
            raise PhotoIdentitySourceStatusError("private multi-performer track review authority is invalid")
        _assert_same_identity(public_review, base_report=base_report, label="Multi-performer track review")
        _assert_same_identity(private_review, base_report=base_report, label="Private multi-performer track review")
        source_candidate_id = str(public_review.get("source_candidate_id") or "")
        if source_candidate_id not in candidate_ids:
            raise PhotoIdentitySourceStatusError("track review source candidate is not in exhaustive discovery")
        if source_candidate_id in reviewed_source_ids:
            raise PhotoIdentitySourceStatusError("duplicate track review exists for one source candidate")
        reviewed_source_ids.add(source_candidate_id)

        track_attestation = review_root / "photoidentity-multiperformer-track-attestation.json"
        if not track_attestation.is_file():
            pending_track_review.append(str(review_root))
            continue

        candidate_root = review_root / "target-isolation-candidates"
        isolation_manifest = candidate_root / "multiperformer-target-isolation-candidates.json"
        private_isolation = candidate_root / "private-target-source" / "private-target-source-index.json"
        if not candidate_root.exists():
            pending_materialize.append(str(review_root))
            continue
        if not candidate_root.is_dir():
            raise PhotoIdentitySourceStatusError("target-isolation candidate root is not a directory")
        if not _pair_state((isolation_manifest, private_isolation), label=f"target-isolation candidates {review_root.name}"):
            raise PhotoIdentitySourceStatusError("partial target-isolation candidate authority exists")

        isolation_receipt = candidate_root / "photoidentity-multiperformer-target-isolation-attestation.json"
        if not isolation_receipt.is_file():
            pending_isolation_review.append(str(candidate_root))
            continue

        enrichment_root = candidate_root / "target-crop-detail-enrichment"
        enrichment_receipt = enrichment_root / "target-crop-detail-enrichment.json"
        private_enrichment = enrichment_root / "private-analysis" / "private-analysis-index.json"
        if not enrichment_root.exists():
            pending_enrichment.append(str(candidate_root))
            continue
        if not enrichment_root.is_dir():
            raise PhotoIdentitySourceStatusError("target-crop enrichment root is not a directory")
        if not _pair_state((enrichment_receipt, private_enrichment), label=f"target-crop enrichment {review_root.name}"):
            raise PhotoIdentitySourceStatusError("partial target-crop enrichment authority exists")

        quality_receipt = enrichment_root / "photoidentity-target-crop-detail-quality-attestation.json"
        if not quality_receipt.is_file():
            pending_quality_review.append(str(candidate_root))
            continue
        claims = _quality_receipt_claims(quality_receipt, base_report=base_report)
        quality_receipts.append(str(quality_receipt))
        candidate_roots.append(str(candidate_root))
        for domain, scenes in claims.items():
            quality_claims.setdefault(domain, set()).update(scenes)

    remaining_candidates = sorted(set(candidate_ids) - reviewed_source_ids)

    if pending_track_review:
        return _stage(
            sweep_root=sweep_root,
            base_report=base_report,
            name="multiperformer-track-human-review",
            next_action="record_multiperformer_track_attestation",
            human_review_required=True,
            extra={"multiperformer_root": str(root), "pending_review_roots": pending_track_review},
        )
    if pending_materialize:
        return _stage(
            sweep_root=sweep_root,
            base_report=base_report,
            name="multiperformer-target-isolation-materialize",
            next_action="materialize_target_isolation_candidates",
            extra={"multiperformer_root": str(root), "pending_review_roots": pending_materialize},
        )
    if pending_isolation_review:
        return _stage(
            sweep_root=sweep_root,
            base_report=base_report,
            name="multiperformer-target-isolation-human-review",
            next_action="record_target_isolation_attestation",
            human_review_required=True,
            extra={"multiperformer_root": str(root), "pending_candidate_roots": pending_isolation_review},
        )
    if pending_enrichment:
        return _stage(
            sweep_root=sweep_root,
            base_report=base_report,
            name="multiperformer-target-crop-enrich",
            next_action="enrich_target_crops",
            extra={"multiperformer_root": str(root), "pending_candidate_roots": pending_enrichment},
        )
    if pending_quality_review:
        return _stage(
            sweep_root=sweep_root,
            base_report=base_report,
            name="multiperformer-target-detail-human-review",
            next_action="record_target_crop_detail_quality",
            human_review_required=True,
            extra={"multiperformer_root": str(root), "pending_candidate_roots": pending_quality_review},
        )

    progress, missing = _target_detail_progress(base_report=base_report, quality_claims=quality_claims)
    if missing:
        if remaining_candidates:
            return _stage(
                sweep_root=sweep_root,
                base_report=base_report,
                name="multiperformer-more-detail",
                next_action="prepare_additional_multiperformer_track_review",
                human_review_required=True,
                extra={
                    "multiperformer_root": str(root),
                    "missing_target_domains": missing,
                    "target_detail_progress": progress,
                    "available_source_candidate_ids": remaining_candidates,
                    "quality_receipts": quality_receipts,
                    "candidate_roots": candidate_roots,
                },
            )
        return _stage(
            sweep_root=sweep_root,
            base_report=base_report,
            name="multiperformer-source-insufficient",
            next_action="capture_or_add_multiperformer_source_media",
            human_review_required=True,
            extra={
                "multiperformer_root": str(root),
                "missing_target_domains": missing,
                "target_detail_progress": progress,
                "available_source_candidate_ids": [],
                "quality_receipts": quality_receipts,
                "candidate_roots": candidate_roots,
            },
        )

    return _stage(
        sweep_root=sweep_root,
        base_report=base_report,
        name="multiperformer-aggregation",
        next_action="aggregate_multiperformer_detail_evidence",
        extra={
            "multiperformer_root": str(root),
            "missing_target_domains": [],
            "target_detail_progress": progress,
            "quality_receipts": quality_receipts,
            "candidate_roots": candidate_roots,
        },
    )


def inspect_source_status(
    sweep_root: str | Path,
    *,
    multiperformer_root: str | Path | None = None,
    body_job_id: str | None = None,
) -> dict[str, Any]:
    root = Path(sweep_root).expanduser().resolve()
    if not root.is_dir():
        raise PhotoIdentitySourceStatusError("photoidentity sweep root is missing")

    base_observations = root / "human-parsing-evidence" / "photoidentity-observations.json"
    base_report_path = root / "human-parsing-evidence" / "photoidentity-evidence.json"
    if not _pair_state((base_observations, base_report_path), label="human-parsing evidence"):
        raise PhotoIdentitySourceStatusError(
            "photoidentity sweep has no completed OpenPose/SCHP evidence; run collect-photoidentity-evidence.ps1 first"
        )
    try:
        base_report = validate_authoritative_bundle(base_report_path, base_observations, require_sufficient=False)
    except PhotoIdentityAuthorityError as exc:
        raise PhotoIdentitySourceStatusError(f"base photoidentity evidence is invalid: {exc}") from exc

    try:
        aggregation = validate_multiperformer_detail_aggregation(root)
    except PhotoIdentityMultiDetailAggregateError as exc:
        raise PhotoIdentitySourceStatusError(f"multi-performer detail aggregation is invalid: {exc}") from exc
    if aggregation is None:
        normalized_multi_root = (
            Path(multiperformer_root).expanduser().resolve()
            if multiperformer_root is not None and str(multiperformer_root).strip()
            else None
        )
        return _inspect_multiperformer_pending(
            sweep_root=root,
            base_report=base_report,
            multiperformer_root=normalized_multi_root,
        )

    multi_report = dict(aggregation["report"])
    for field in ("performer_id", "bodyrig_revision", "baseline_source_manifest_sha256"):
        if str(multi_report.get(field) or "") != str(base_report.get(field) or ""):
            raise PhotoIdentitySourceStatusError(f"multi-performer aggregation changed base authority: {field}")

    nail_discovery = root / "nail-source-candidates.json"
    nail_private_index = root / "private-nail-source-candidates" / "private-candidate-index.json"
    nail_receipt = root / "photoidentity-nail-source-attestation.json"
    nail_observations = root / "nail-attested-evidence" / "photoidentity-observations.json"
    nail_report_path = root / "nail-attested-evidence" / "photoidentity-evidence.json"
    nail_review_index = root / "private-nail-source-review" / "review-index.json"

    if nail_receipt.exists() and not _pair_state(
        (nail_discovery, nail_private_index, nail_receipt, nail_observations, nail_report_path),
        label="nail attestation",
    ):
        raise AssertionError("unreachable")
    if not nail_receipt.exists():
        if nail_observations.exists() or nail_report_path.exists():
            raise PhotoIdentitySourceStatusError("nail-attested evidence exists without its human receipt")
        if not nail_discovery.exists():
            if nail_private_index.exists() or nail_review_index.exists():
                raise PhotoIdentitySourceStatusError("private nail state exists without public discovery authority")
            return _stage(
                sweep_root=root,
                base_report=base_report,
                final_report=multi_report,
                name="nail-discovery",
                next_action="discover_nail_sources",
            )
        if not nail_private_index.is_file():
            raise PhotoIdentitySourceStatusError("nail discovery exists without its private exact-source index")
        if not nail_review_index.exists():
            return _stage(
                sweep_root=root,
                base_report=base_report,
                final_report=multi_report,
                name="nail-review-prepare",
                next_action="prepare_nail_source_review",
            )
        return _stage(
            sweep_root=root,
            base_report=base_report,
            final_report=multi_report,
            name="nail-human-review",
            next_action="record_complete_nail_attestation_after_source_review",
            human_review_required=True,
        )

    nail_receipt_value = _read_json(nail_receipt, label="Nail source attestation receipt")
    if set(nail_receipt_value.get("attested_domains") or []) != {"fingernails_detail", "toenails_detail"}:
        raise PhotoIdentitySourceStatusError(
            "partial create-only nail attestation is noncanonical; complete fingernails and toenails must be attested atomically"
        )
    if nail_receipt_value.get("prior_stage") != "multiperformer-detail":
        raise PhotoIdentitySourceStatusError("nail authority did not select the multi-performer detail prior")
    if nail_receipt_value.get("prior_observation_evidence_sha256") != _sha256(Path(aggregation["observations_path"])):
        raise PhotoIdentitySourceStatusError("nail authority lost multi-performer observation binding")
    if nail_receipt_value.get("prior_sufficiency_report_sha256") != _sha256(Path(aggregation["report_path"])):
        raise PhotoIdentitySourceStatusError("nail authority lost multi-performer report binding")
    try:
        nail_report = validate_authoritative_bundle(nail_report_path, nail_observations, require_sufficient=False)
    except PhotoIdentityAuthorityError as exc:
        raise PhotoIdentitySourceStatusError(f"nail-attested evidence is invalid: {exc}") from exc
    for field in ("performer_id", "bodyrig_revision", "baseline_source_manifest_sha256"):
        if str(nail_report.get(field) or "") != str(base_report.get(field) or ""):
            raise PhotoIdentitySourceStatusError(f"nail evidence changed base authority: {field}")

    anatomy_discovery = root / "anatomy-source-candidates.json"
    anatomy_private_index = root / "private-anatomy-source-candidates" / "private-candidate-index.json"
    anatomy_receipt = root / "photoidentity-anatomy-source-attestation.json"
    anatomy_observations = root / "anatomy-attested-evidence" / "photoidentity-observations.json"
    anatomy_report_path = root / "anatomy-attested-evidence" / "photoidentity-evidence.json"
    anatomy_review_index = root / "private-anatomy-source-review" / "review-index.json"

    if anatomy_receipt.exists() and not _pair_state(
        (anatomy_discovery, anatomy_private_index, anatomy_receipt, anatomy_observations, anatomy_report_path),
        label="anatomy attestation",
    ):
        raise AssertionError("unreachable")
    if not anatomy_receipt.exists():
        if anatomy_observations.exists() or anatomy_report_path.exists():
            raise PhotoIdentitySourceStatusError("anatomy-attested evidence exists without its human receipt")
        if not anatomy_discovery.exists():
            if anatomy_private_index.exists() or anatomy_review_index.exists():
                raise PhotoIdentitySourceStatusError("private anatomy state exists without public discovery authority")
            return _stage(
                sweep_root=root,
                base_report=base_report,
                final_report=nail_report,
                name="anatomy-discovery",
                next_action="discover_rear_torso_waist_sources",
            )
        if not anatomy_private_index.is_file():
            raise PhotoIdentitySourceStatusError("anatomy discovery exists without its private exact-source index")
        if not anatomy_review_index.exists():
            return _stage(
                sweep_root=root,
                base_report=base_report,
                final_report=nail_report,
                name="anatomy-review-prepare",
                next_action="prepare_anatomy_source_review",
            )
        return _stage(
            sweep_root=root,
            base_report=base_report,
            final_report=nail_report,
            name="anatomy-human-review",
            next_action="record_atomic_anatomy_attestation_after_source_review",
            human_review_required=True,
        )

    try:
        chain = validate_registration_source_chain(
            anatomy_report_path,
            anatomy_observations,
            expected_performer_id=str(base_report["performer_id"]),
            expected_bodyrig_revision=str(base_report["bodyrig_revision"]),
            expected_baseline_source_manifest_sha256=str(base_report["baseline_source_manifest_sha256"]),
        )
    except PhotoIdentitySourceChainError as exc:
        raise PhotoIdentitySourceStatusError(f"final human source chain is invalid: {exc}") from exc
    final_report = dict(chain["report"])

    normalized_job_id = str(body_job_id or "").strip() or None
    if normalized_job_id is None:
        return _stage(
            sweep_root=root,
            base_report=base_report,
            final_report=final_report,
            name="ready-for-registration",
            next_action="register_source_authority_for_body_job",
        )

    try:
        job, _, _, job_root, _ = _job_authority(normalized_job_id)
    except PhotoIdentityRegistryError as exc:
        raise PhotoIdentitySourceStatusError(f"body-job authority is invalid: {exc}") from exc
    registry_root = job_root / REGISTRY_DIRNAME
    if not registry_root.exists():
        return _stage(
            sweep_root=root,
            base_report=base_report,
            final_report=final_report,
            body_job_id=normalized_job_id,
            name="ready-for-registration",
            next_action="register_source_authority_for_body_job",
        )
    try:
        require_body_job_photoidentity_evidence(str(job["person_id"]), normalized_job_id)
    except PhotoIdentityRegistryError as exc:
        raise PhotoIdentitySourceStatusError(f"registered photoidentity authority is invalid: {exc}") from exc
    return _stage(
        sweep_root=root,
        base_report=base_report,
        final_report=final_report,
        body_job_id=normalized_job_id,
        name="registered",
        next_action="high_fidelity_preview_gate_may_be_evaluated",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route the fail-closed BodyRig photoidentity source-sufficiency workflow.")
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--multiperformer-root", default=None)
    parser.add_argument("--body-job-id", default=None)
    args = parser.parse_args(argv)
    try:
        result = inspect_source_status(
            args.sweep_root,
            multiperformer_root=args.multiperformer_root,
            body_job_id=args.body_job_id,
        )
    except (OSError, ValueError, PhotoIdentitySourceStatusError) as exc:
        print(f"BodyRig photoidentity source status: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

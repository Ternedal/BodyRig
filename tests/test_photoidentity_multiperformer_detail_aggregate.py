from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoidentity_authority import (
    DETAIL_DOMAIN_AUTHORITY,
    PhotoIdentityAuthorityError,
    validate_authoritative_observation_evidence,
)
from bodyrig.photoidentity_evidence import build_observation_evidence, write_bundle
from bodyrig.photoidentity_multiperformer_detail_aggregate import (
    AUTHORITY_DIRNAME,
    EVIDENCE_DIRNAME,
    RECEIPT_NAME,
    PhotoIdentityMultiDetailAggregateError,
    aggregate_multiperformer_detail_evidence,
    validate_multiperformer_detail_aggregation,
)
from bodyrig.photoidentity_multiperformer_target_attestation import (
    FORMAT as ISOLATION_FORMAT,
    POLICY as ISOLATION_POLICY,
    VERSION as ISOLATION_VERSION,
)
from bodyrig.photoidentity_prior import resolve_pre_nail_bundle
from bodyrig.photoidentity_target_crop_enrich import (
    FORMAT as ENRICHMENT_FORMAT,
    PRIVATE_FORMAT as PRIVATE_ENRICHMENT_FORMAT,
    PRIVATE_VERSION as PRIVATE_ENRICHMENT_VERSION,
    VERSION as ENRICHMENT_VERSION,
)
from bodyrig.photoidentity_target_crop_quality_attestation import (
    ADAPTER as QUALITY_ADAPTER,
    ADAPTER_REVISION as QUALITY_ADAPTER_REVISION,
    DOMAIN_MACHINE_AUTHORITY,
    FORMAT as QUALITY_FORMAT,
    HUMAN_ONLY_DOMAINS,
    HUMAN_QUALITY_BASIS,
    POLICY as QUALITY_POLICY,
)

REVISION = "a" * 40
BASELINE_SHA = "b" * 64
MACHINE_TARGET_DOMAINS = tuple(sorted(DOMAIN_MACHINE_AUTHORITY))
HUMAN_TARGET_DOMAINS = tuple(sorted(HUMAN_ONLY_DOMAINS))
ALL_TARGET_DOMAINS = (*MACHINE_TARGET_DOMAINS, *HUMAN_TARGET_DOMAINS)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _row(scene: str) -> dict[str, object]:
    return {
        "scene_id": scene,
        "source_ordinal": 1,
        "start_seconds": 0.0,
        "duration_seconds": 4.0,
        "target_confidence": 0.95,
        "target_screen_fraction": 0.8,
        "face_visibility": 0.95,
        "full_body_visibility": 0.95,
        "sharpness": 0.9,
        "occlusion": 0.02,
        "motion": 0.1,
        "view": "front",
    }


def _claim(scene: str, domain: str, *, quality: float = 0.91) -> dict[str, object]:
    _, adapter, revision = DETAIL_DOMAIN_AUTHORITY[domain]
    return {
        "scene_id": scene,
        "quality": quality,
        "source_derived": True,
        "adapter": adapter,
        "revision": revision,
    }


def _base_sweep(tmp_path: Path) -> Path:
    sweep = tmp_path / "sweep"
    evidence = build_observation_evidence(
        performer_id="42",
        bodyrig_revision=REVISION,
        baseline_source_manifest_sha256=BASELINE_SHA,
        analyzer_adapter="bodyrig-photoidentity-coarse-openpose-schp-composite",
        analyzer_revision="1",
        analyzer_capabilities=[
            "coarse-face-view",
            "coarse-full-body-view",
            "eyes-detail",
            "hands-detail",
            "feet-detail",
            "hair-detail",
            "skin-detail",
        ],
        candidate_scenes=1,
        source_files_scanned=1,
        scan_exhausted=True,
        rows=[_row("single-1")],
        detail_evidence={
            domain: [_claim("single-1", domain)]
            for domain in MACHINE_TARGET_DOMAINS
        },
    )
    write_bundle(sweep / "human-parsing-evidence", evidence)
    return sweep


def _quality_lineage(
    tmp_path: Path,
    *,
    scene: str = "multi-1",
    domains: tuple[str, ...] = ALL_TARGET_DOMAINS,
    quality: float = 0.93,
) -> tuple[Path, Path]:
    candidate_root = tmp_path / f"candidate-{scene}"
    enrichment_root = candidate_root / "target-crop-detail-enrichment"
    private_root = enrichment_root / "private-analysis"
    sample_id = "targetsample-0001"

    crop = private_root / "crop.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(f"real-source-crop-bytes-{scene}".encode("utf-8"))
    crop_sha = _sha(crop)

    isolation_path = candidate_root / "photoidentity-multiperformer-target-isolation-attestation.json"
    isolation = {
        "format": ISOLATION_FORMAT,
        "version": ISOLATION_VERSION,
        "policy": ISOLATION_POLICY,
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "scene_id": scene,
        "accepted_samples": [{"sample_id": sample_id, "target_crop_sha256": crop_sha}],
        "target_isolated_source_authority": True,
        "authority_scope": "accepted-samples-only",
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    _write(isolation_path, isolation)

    private_path = private_root / "private-analysis-index.json"
    private = {
        "format": PRIVATE_ENRICHMENT_FORMAT,
        "version": PRIVATE_ENRICHMENT_VERSION,
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "scene_id": scene,
        "rows": [{"sample_id": sample_id, "analysis_crop": str(crop)}],
    }
    _write(private_path, private)

    machine_candidates: list[dict[str, object]] = []
    selected_claims: list[dict[str, object]] = []
    for domain in domains:
        if domain in DOMAIN_MACHINE_AUTHORITY:
            machine_adapter, machine_revision = DOMAIN_MACHINE_AUTHORITY[domain]
            machine_candidates.append(
                {
                    "domain": domain,
                    "machine_observability_score": quality,
                    "source_derived": True,
                    "adapter": machine_adapter,
                    "revision": machine_revision,
                    "source_detail_quality_authority": False,
                    "photoidentity_sufficiency_authority": False,
                }
            )
            selected_claims.append(
                {
                    "sample_id": sample_id,
                    "domain": domain,
                    "scene_id": scene,
                    "target_crop_sha256": crop_sha,
                    "quality": quality,
                    "machine_adapter": machine_adapter,
                    "machine_revision": machine_revision,
                    "source_derived": True,
                    "adapter": QUALITY_ADAPTER,
                    "revision": QUALITY_ADAPTER_REVISION,
                }
            )
        else:
            assert domain in HUMAN_ONLY_DOMAINS
            selected_claims.append(
                {
                    "sample_id": sample_id,
                    "domain": domain,
                    "scene_id": scene,
                    "target_crop_sha256": crop_sha,
                    "quality": quality,
                    "quality_basis": HUMAN_QUALITY_BASIS,
                    "human_visibility_attested": True,
                    "machine_observability_used": False,
                    "source_derived": True,
                    "adapter": QUALITY_ADAPTER,
                    "revision": QUALITY_ADAPTER_REVISION,
                }
            )

    public_path = enrichment_root / "target-crop-detail-enrichment.json"
    public = {
        "format": ENRICHMENT_FORMAT,
        "version": ENRICHMENT_VERSION,
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "scene_id": scene,
        "human_target_isolation_attestation_sha256": _sha(isolation_path),
        "private_analysis_index_sha256": _sha(private_path),
        "machine_observability_only": True,
        "source_detail_quality_authority": False,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
        "samples": [
            {
                "sample_id": sample_id,
                "target_crop_sha256": crop_sha,
                "candidates": machine_candidates,
            }
        ],
    }
    _write(public_path, public)

    receipt_path = enrichment_root / "photoidentity-target-crop-detail-quality-attestation.json"
    receipt = {
        "format": QUALITY_FORMAT,
        "version": 1,
        "policy": QUALITY_POLICY,
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "scene_id": scene,
        "human_target_isolation_attestation_sha256": _sha(isolation_path),
        "target_crop_detail_enrichment_sha256": _sha(public_path),
        "private_analysis_index_sha256": _sha(private_path),
        "adapter": QUALITY_ADAPTER,
        "adapter_revision": QUALITY_ADAPTER_REVISION,
        "selected_domains": sorted(domains),
        "selected_claims": selected_claims,
        "human_source_detail_quality_attested": True,
        "quality_note": "The real isolated source crop was reviewed and has sufficient native source detail for every selected domain.",
        "reviewed_utc": "2026-09-11T00:00:00Z",
        "source_detail_quality_authority": True,
        "photoidentity_source_evidence_authority": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    _write(receipt_path, receipt)
    return candidate_root, receipt_path


def _complete_lineages(tmp_path: Path) -> tuple[list[Path], list[Path]]:
    first_root, first_receipt = _quality_lineage(tmp_path, scene="multi-1")
    second_root, second_receipt = _quality_lineage(tmp_path, scene="multi-2")
    return [first_root, second_root], [first_receipt, second_receipt]


def test_aggregate_requires_complete_target_detail_scope_and_adds_human_hair_authority(tmp_path: Path) -> None:
    sweep = _base_sweep(tmp_path)
    candidate_roots, receipts = _complete_lineages(tmp_path)
    result = aggregate_multiperformer_detail_evidence(
        sweep_root=sweep,
        quality_receipts=receipts,
        candidate_roots=candidate_roots,
    )
    observations = json.loads(Path(result["enriched_observation_evidence"]).read_text(encoding="utf-8"))
    report = result["report"]
    assert observations["rows"] == [_row("single-1")]
    eyes = observations["detail_evidence"]["eyes_detail"]
    assert [item["scene_id"] for item in eyes] == ["multi-1", "multi-2", "single-1"]
    assert {item["adapter"] for item in eyes} == {
        "openpose-body25-face-hand-detail",
        QUALITY_ADAPTER,
    }
    for domain in ALL_TARGET_DOMAINS:
        assert report["domains"][domain]["status"] == "pass"
    for domain in HUMAN_TARGET_DOMAINS:
        claims = observations["detail_evidence"][domain]
        assert [item["scene_id"] for item in claims] == ["multi-1", "multi-2"]
        assert {item["adapter"] for item in claims} == {QUALITY_ADAPTER}
        capability = report["domains"][domain]["required_capability"]
        assert capability in observations["analyzer"]["capabilities"]
    validated = validate_multiperformer_detail_aggregation(sweep)
    assert validated is not None
    _, _, _, prior_report, stage = resolve_pre_nail_bundle(sweep)
    assert stage == "multiperformer-detail"
    assert prior_report["domains"]["body_hair_detail"]["qualifying_distinct_scenes"] == 2


def test_incomplete_create_only_aggregation_writes_nothing(tmp_path: Path) -> None:
    sweep = _base_sweep(tmp_path)
    candidate_root, receipt = _quality_lineage(tmp_path, scene="multi-1")
    with pytest.raises(PhotoIdentityMultiDetailAggregateError, match="incomplete create-only target-detail evidence") as raised:
        aggregate_multiperformer_detail_evidence(
            sweep_root=sweep,
            quality_receipts=[receipt],
            candidate_roots=[candidate_root],
        )
    assert "eyebrows_detail=1/2" in str(raised.value)
    assert "facial_hair_detail=1/2" in str(raised.value)
    assert "body_hair_detail=1/2" in str(raised.value)
    assert not (sweep / EVIDENCE_DIRNAME).exists()
    assert not (sweep / AUTHORITY_DIRNAME).exists()
    assert not (sweep / RECEIPT_NAME).exists()


def test_machine_only_claim_cannot_impersonate_human_hair_authority(tmp_path: Path) -> None:
    sweep = _base_sweep(tmp_path)
    candidate_root, receipt = _quality_lineage(tmp_path, scene="multi-1", domains=("eyebrows_detail",))
    value = json.loads(receipt.read_text(encoding="utf-8"))
    claim = value["selected_claims"][0]
    claim.pop("quality_basis")
    claim.pop("human_visibility_attested")
    claim.pop("machine_observability_used")
    claim["machine_adapter"] = "schp-atr18-source-observability"
    claim["machine_revision"] = "1"
    _write(receipt, value)
    with pytest.raises(PhotoIdentityMultiDetailAggregateError, match="human-only hair claim"):
        aggregate_multiperformer_detail_evidence(
            sweep_root=sweep,
            quality_receipts=[receipt],
            candidate_roots=[candidate_root],
        )


def test_aggregate_rejects_overlap_with_single_person_observation_pool(tmp_path: Path) -> None:
    sweep = _base_sweep(tmp_path)
    candidate_root, receipt = _quality_lineage(tmp_path, scene="single-1")
    with pytest.raises(PhotoIdentityMultiDetailAggregateError, match="overlaps the single-performer observation pool"):
        aggregate_multiperformer_detail_evidence(
            sweep_root=sweep,
            quality_receipts=[receipt],
            candidate_roots=[candidate_root],
        )


def test_aggregate_prior_fails_closed_when_persisted_quality_receipt_is_tampered(tmp_path: Path) -> None:
    sweep = _base_sweep(tmp_path)
    candidate_roots, receipts = _complete_lineages(tmp_path)
    aggregate_multiperformer_detail_evidence(
        sweep_root=sweep,
        quality_receipts=receipts,
        candidate_roots=candidate_roots,
    )
    authority = sweep / AUTHORITY_DIRNAME
    stored = next(authority.glob("quality-*.json"))
    stored.write_text(stored.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(PhotoIdentityMultiDetailAggregateError, match="hash mismatch"):
        validate_multiperformer_detail_aggregation(sweep)


def test_aggregate_rejects_detached_quality_receipt_with_fabricated_source_hash(tmp_path: Path) -> None:
    sweep = _base_sweep(tmp_path)
    candidate_roots, receipts = _complete_lineages(tmp_path)
    value = json.loads(receipts[0].read_text(encoding="utf-8"))
    value["human_target_isolation_attestation_sha256"] = "0" * 64
    _write(receipts[0], value)
    with pytest.raises(PhotoIdentityMultiDetailAggregateError, match="not bound to current isolation receipt"):
        aggregate_multiperformer_detail_evidence(
            sweep_root=sweep,
            quality_receipts=receipts,
            candidate_roots=candidate_roots,
        )


def test_aggregate_requires_candidate_root_for_every_quality_receipt(tmp_path: Path) -> None:
    sweep = _base_sweep(tmp_path)
    _, receipt = _quality_lineage(tmp_path)
    with pytest.raises(PhotoIdentityMultiDetailAggregateError, match="corresponding human-isolation candidate root"):
        aggregate_multiperformer_detail_evidence(
            sweep_root=sweep,
            quality_receipts=[receipt],
            candidate_roots=[],
        )


def test_human_target_detail_adapter_is_not_authority_for_nails_or_anatomy() -> None:
    evidence = build_observation_evidence(
        performer_id="42",
        bodyrig_revision=REVISION,
        baseline_source_manifest_sha256=BASELINE_SHA,
        analyzer_adapter="bodyrig-photoidentity-source-human-anatomy-composite",
        analyzer_revision="1",
        analyzer_capabilities=[
            "coarse-face-view",
            "coarse-full-body-view",
            "eyes-detail",
            "hands-detail",
            "feet-detail",
            "hair-detail",
            "eyebrows-detail",
            "facial-hair-detail",
            "body-hair-detail",
            "skin-detail",
            "fingernails-detail",
            "toenails-detail",
            "rear-body-view",
            "torso-chest-detail",
            "waist-hips-detail",
        ],
        candidate_scenes=1,
        source_files_scanned=1,
        scan_exhausted=True,
        rows=[_row("single-1")],
        detail_evidence={
            "fingernails_detail": [{
                "scene_id": "multi-1",
                "quality": 0.95,
                "source_derived": True,
                "adapter": QUALITY_ADAPTER,
                "revision": QUALITY_ADAPTER_REVISION,
            }]
        },
    )
    with pytest.raises(PhotoIdentityAuthorityError, match="does not match registered domain authority"):
        validate_authoritative_observation_evidence(evidence)

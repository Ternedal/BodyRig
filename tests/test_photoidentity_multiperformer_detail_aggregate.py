from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.photoidentity_authority import PhotoIdentityAuthorityError, validate_authoritative_observation_evidence
from bodyrig.photoidentity_evidence import build_observation_evidence, write_bundle
from bodyrig.photoidentity_multiperformer_detail_aggregate import (
    AUTHORITY_DIRNAME,
    PhotoIdentityMultiDetailAggregateError,
    aggregate_multiperformer_detail_evidence,
    validate_multiperformer_detail_aggregation,
)
from bodyrig.photoidentity_prior import resolve_pre_nail_bundle
from bodyrig.photoidentity_target_crop_detail import OPENPOSE_ADAPTER as TARGET_OPENPOSE_ADAPTER
from bodyrig.photoidentity_target_crop_detail import OPENPOSE_REVISION as TARGET_OPENPOSE_REVISION
from bodyrig.photoidentity_target_crop_quality_attestation import (
    ADAPTER as QUALITY_ADAPTER,
    ADAPTER_REVISION as QUALITY_ADAPTER_REVISION,
    FORMAT as QUALITY_FORMAT,
    POLICY as QUALITY_POLICY,
)

REVISION = "a" * 40
BASELINE_SHA = "b" * 64


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
    adapter = "openpose-body25-face-hand-detail" if domain in {"eyes_detail", "hands", "feet"} else "schp-atr18-source-observability"
    return {
        "scene_id": scene,
        "quality": quality,
        "source_derived": True,
        "adapter": adapter,
        "revision": "1",
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
        detail_evidence={"eyes_detail": [_claim("single-1", "eyes_detail")]},
    )
    write_bundle(sweep / "human-parsing-evidence", evidence)
    return sweep


def _quality_receipt(tmp_path: Path, *, scene: str = "multi-1", domain: str = "eyes_detail", quality: float = 0.93) -> Path:
    path = tmp_path / f"quality-{scene}-{domain}.json"
    machine_adapter = TARGET_OPENPOSE_ADAPTER
    machine_revision = TARGET_OPENPOSE_REVISION
    receipt = {
        "format": QUALITY_FORMAT,
        "version": 1,
        "policy": QUALITY_POLICY,
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "scene_id": scene,
        "human_target_isolation_attestation_sha256": "c" * 64,
        "target_crop_detail_enrichment_sha256": "d" * 64,
        "private_analysis_index_sha256": "e" * 64,
        "adapter": QUALITY_ADAPTER,
        "adapter_revision": QUALITY_ADAPTER_REVISION,
        "selected_domains": [domain],
        "selected_claims": [{
            "sample_id": "targetsample-0001",
            "domain": domain,
            "scene_id": scene,
            "target_crop_sha256": "f" * 64,
            "quality": quality,
            "machine_adapter": machine_adapter,
            "machine_revision": machine_revision,
            "source_derived": True,
            "adapter": QUALITY_ADAPTER,
            "revision": QUALITY_ADAPTER_REVISION,
        }],
        "human_source_detail_quality_attested": True,
        "quality_note": "The real isolated source crop was reviewed and has sufficient native source detail.",
        "reviewed_utc": "2026-09-11T00:00:00Z",
        "source_detail_quality_authority": True,
        "photoidentity_source_evidence_authority": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_aggregate_adds_distinct_human_reviewed_scene_without_mutating_base_rows(tmp_path: Path) -> None:
    sweep = _base_sweep(tmp_path)
    receipt = _quality_receipt(tmp_path)
    result = aggregate_multiperformer_detail_evidence(sweep_root=sweep, quality_receipts=[receipt])
    observations = json.loads(Path(result["enriched_observation_evidence"]).read_text(encoding="utf-8"))
    report = result["report"]
    assert observations["rows"] == [_row("single-1")]
    claims = observations["detail_evidence"]["eyes_detail"]
    assert [item["scene_id"] for item in claims] == ["multi-1", "single-1"]
    assert {item["adapter"] for item in claims} == {"openpose-body25-face-hand-detail", QUALITY_ADAPTER}
    assert report["domains"]["eyes_detail"]["qualifying_distinct_scenes"] == 2
    assert report["domains"]["eyes_detail"]["status"] == "pass"
    validated = validate_multiperformer_detail_aggregation(sweep)
    assert validated is not None
    _, _, _, prior_report, stage = resolve_pre_nail_bundle(sweep)
    assert stage == "multiperformer-detail"
    assert prior_report["domains"]["eyes_detail"]["qualifying_distinct_scenes"] == 2


def test_aggregate_rejects_overlap_with_single_person_observation_pool(tmp_path: Path) -> None:
    sweep = _base_sweep(tmp_path)
    receipt = _quality_receipt(tmp_path, scene="single-1")
    with pytest.raises(PhotoIdentityMultiDetailAggregateError, match="overlaps the single-performer observation pool"):
        aggregate_multiperformer_detail_evidence(sweep_root=sweep, quality_receipts=[receipt])


def test_aggregate_prior_fails_closed_when_persisted_quality_receipt_is_tampered(tmp_path: Path) -> None:
    sweep = _base_sweep(tmp_path)
    receipt = _quality_receipt(tmp_path)
    aggregate_multiperformer_detail_evidence(sweep_root=sweep, quality_receipts=[receipt])
    authority = sweep / AUTHORITY_DIRNAME
    stored = next(authority.glob("quality-*.json"))
    stored.write_text(stored.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(PhotoIdentityMultiDetailAggregateError, match="hash mismatch"):
        validate_multiperformer_detail_aggregation(sweep)


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

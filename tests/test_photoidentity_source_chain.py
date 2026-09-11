from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from bodyrig.photoidentity_authority import DETAIL_DOMAIN_AUTHORITY
from bodyrig.photoidentity_evidence import DOMAIN_REQUIREMENTS, build_observation_evidence, write_bundle
from bodyrig.photoidentity_multiperformer_detail_aggregate import (
    COMPOSITE_ADAPTER,
    COMPOSITE_REVISION,
    FORMAT as MULTIPERFORMER_FORMAT,
    POLICY_REVISION as MULTIPERFORMER_POLICY,
    RECEIPT_NAME as MULTIPERFORMER_RECEIPT_NAME,
    VERSION as MULTIPERFORMER_VERSION,
)
from bodyrig.photoidentity_source_chain import (
    PhotoIdentitySourceChainError,
    validate_registration_source_chain,
)
from bodyrig.photoidentity_target_crop_quality_attestation import (
    ADAPTER as TARGET_DETAIL_ADAPTER,
    ADAPTER_REVISION as TARGET_DETAIL_REVISION,
    FORMAT as TARGET_DETAIL_FORMAT,
    HUMAN_ONLY_DOMAINS,
    HUMAN_QUALITY_BASIS,
    POLICY as TARGET_DETAIL_POLICY,
    SUPPORTED_QUALITY_DOMAINS,
    VERSION as TARGET_DETAIL_VERSION,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _row(scene: str, ordinal: int, view: str) -> dict[str, object]:
    return {
        "scene_id": scene,
        "source_ordinal": ordinal,
        "start_seconds": 1.0,
        "duration_seconds": 6.0,
        "target_confidence": 0.95,
        "target_screen_fraction": 0.45,
        "face_visibility": 0.95,
        "full_body_visibility": 0.92,
        "sharpness": 0.92,
        "occlusion": 0.04,
        "motion": 0.15,
        "view": view,
    }


def _claim(domain: str, scene: str, quality: float = 0.91) -> dict[str, object]:
    _, adapter, revision = DETAIL_DOMAIN_AUTHORITY[domain]
    return {
        "scene_id": scene,
        "quality": quality,
        "source_derived": True,
        "adapter": adapter,
        "revision": revision,
    }


def _selected(region: str, scene: str, salt: str, quality: float = 0.91) -> dict[str, object]:
    return {
        "candidate_id": f"candidate-{salt}",
        "region": region,
        "scene_id": scene,
        "source_media_sha256": hashlib.sha256(f"source-{salt}".encode()).hexdigest(),
        "image_sha256": hashlib.sha256(f"image-{salt}".encode()).hexdigest(),
        "source_quality": quality,
        "native_crop_width": 640,
        "native_crop_height": 640,
    }


def _machine_base_details() -> dict[str, list[dict[str, object]]]:
    domains = ("eyes_detail", "hands", "feet", "hair_hairline", "skin_detail")
    return {
        domain: [_claim(domain, f"{domain}-a"), _claim(domain, f"{domain}-b")]
        for domain in domains
    }


def _human_hair_claim(domain: str, scene: str, quality: float = 0.93) -> dict[str, object]:
    return {
        "scene_id": scene,
        "quality": quality,
        "source_derived": True,
        "adapter": TARGET_DETAIL_ADAPTER,
        "revision": TARGET_DETAIL_REVISION,
    }


def _persist_multiperformer_hair_stage(
    sweep: Path,
    *,
    rows: list[dict[str, object]],
    base_details: dict[str, list[dict[str, object]]],
) -> tuple[Path, Path, dict[str, list[dict[str, object]]]]:
    base_capabilities = {
        "coarse-face-view",
        "coarse-full-body-view",
        "eyes-detail",
        "hands-detail",
        "feet-detail",
        "hair-detail",
        "skin-detail",
    }
    base_evidence = build_observation_evidence(
        performer_id="42",
        bodyrig_revision="a" * 40,
        baseline_source_manifest_sha256="b" * 64,
        analyzer_adapter="bodyrig-photoidentity-coarse-openpose-schp-composite",
        analyzer_revision="1",
        analyzer_capabilities=sorted(base_capabilities),
        candidate_scenes=20,
        source_files_scanned=20,
        scan_exhausted=True,
        rows=rows,
        detail_evidence=base_details,
    )
    base_observations, base_report, _ = write_bundle(sweep / "human-parsing-evidence", base_evidence)

    hair_details = {domain: [dict(item) for item in claims] for domain, claims in base_details.items()}
    for domain in sorted(HUMAN_ONLY_DOMAINS):
        hair_details[domain] = [
            _human_hair_claim(domain, "multi-hair-a"),
            _human_hair_claim(domain, "multi-hair-b"),
        ]
    human_capabilities = {
        str(DOMAIN_REQUIREMENTS[domain]["capability"])
        for domain in HUMAN_ONLY_DOMAINS
    }
    enriched = build_observation_evidence(
        performer_id="42",
        bodyrig_revision="a" * 40,
        baseline_source_manifest_sha256="b" * 64,
        analyzer_adapter=COMPOSITE_ADAPTER,
        analyzer_revision=COMPOSITE_REVISION,
        analyzer_capabilities=sorted(base_capabilities | human_capabilities),
        candidate_scenes=20,
        source_files_scanned=20,
        scan_exhausted=True,
        rows=rows,
        detail_evidence=hair_details,
    )
    enriched_observations, enriched_report, _ = write_bundle(
        sweep / "multiperformer-detail-evidence", enriched
    )

    authority_root = sweep / "multiperformer-detail-source-authority"
    authority_root.mkdir()
    manifest: list[dict[str, object]] = []
    receipt_paths: list[Path] = []
    for index, scene in enumerate(("multi-hair-a", "multi-hair-b")):
        claims: list[dict[str, object]] = []
        for domain in sorted(HUMAN_ONLY_DOMAINS):
            claims.append(
                {
                    "sample_id": f"targetsample-{index:04d}",
                    "domain": domain,
                    "scene_id": scene,
                    "target_crop_sha256": hashlib.sha256(f"crop-{scene}-{domain}".encode()).hexdigest(),
                    "quality": 0.93,
                    "quality_basis": HUMAN_QUALITY_BASIS,
                    "human_visibility_attested": True,
                    "machine_observability_used": False,
                    "source_derived": True,
                    "adapter": TARGET_DETAIL_ADAPTER,
                    "revision": TARGET_DETAIL_REVISION,
                }
            )
        receipt = {
            "format": TARGET_DETAIL_FORMAT,
            "version": TARGET_DETAIL_VERSION,
            "policy": TARGET_DETAIL_POLICY,
            "bodyrig_revision": "a" * 40,
            "performer_id": "42",
            "scene_id": scene,
            "human_target_isolation_attestation_sha256": hashlib.sha256(f"isolation-{scene}".encode()).hexdigest(),
            "target_crop_detail_enrichment_sha256": hashlib.sha256(f"enrichment-{scene}".encode()).hexdigest(),
            "private_analysis_index_sha256": hashlib.sha256(f"private-{scene}".encode()).hexdigest(),
            "adapter": TARGET_DETAIL_ADAPTER,
            "adapter_revision": TARGET_DETAIL_REVISION,
            "selected_domains": sorted(HUMAN_ONLY_DOMAINS),
            "selected_claims": claims,
            "human_source_detail_quality_attested": True,
            "quality_note": "Reviewed the exact isolated source crop and confirmed eyebrow, facial-hair and body-hair identity visibility.",
            "source_detail_quality_authority": True,
            "photoidentity_source_evidence_authority": False,
            "generic_guessing_permitted": False,
            "reconstruction_permitted": False,
            "production_activation": False,
        }
        temp = authority_root / f"temp-{index}.json"
        _write(temp, receipt)
        digest = _sha(temp)
        stored = authority_root / f"quality-{digest}.json"
        temp.rename(stored)
        receipt_paths.append(stored)
        manifest.append(
            {
                "receipt_sha256": digest,
                "stored_name": stored.name,
                "scene_id": scene,
                "domains": sorted(HUMAN_ONLY_DOMAINS),
            }
        )
    manifest.sort(key=lambda item: str(item["receipt_sha256"]))
    added_counts = {
        domain: (2 if domain in HUMAN_ONLY_DOMAINS else 0)
        for domain in sorted(SUPPORTED_QUALITY_DOMAINS)
    }
    aggregation = {
        "format": MULTIPERFORMER_FORMAT,
        "version": MULTIPERFORMER_VERSION,
        "policy_revision": MULTIPERFORMER_POLICY,
        "performer_id": "42",
        "bodyrig_revision": "a" * 40,
        "baseline_source_manifest_sha256": "b" * 64,
        "prior_stage": "human-parsing",
        "prior_observation_evidence_sha256": _sha(base_observations),
        "prior_sufficiency_report_sha256": _sha(base_report),
        "quality_receipts": manifest,
        "quality_receipt_count": len(manifest),
        "added_claim_counts": added_counts,
        "composite_analyzer": dict(enriched["analyzer"]),
        "enriched_observation_evidence_sha256": _sha(enriched_observations),
        "enriched_sufficiency_report_sha256": _sha(enriched_report),
        "source_grounded": True,
        "generic_guessing_permitted": False,
        "production_activation": False,
    }
    _write(sweep / MULTIPERFORMER_RECEIPT_NAME, aggregation)
    return enriched_observations, enriched_report, hair_details


def _build_chain(
    tmp_path: Path,
    *,
    fingernail_regions: tuple[str, str] = ("left_fingernails", "right_fingernails"),
    final_fingernail_quality: float = 0.91,
    remove_multiperformer_lineage: bool = False,
) -> tuple[Path, Path, Path]:
    sweep = tmp_path / "sweep"
    sweep.mkdir()
    rows = [
        _row("front-a", 1, "front"),
        _row("front-b", 2, "front"),
        _row("left-a", 3, "left_profile"),
        _row("right-a", 4, "right_profile"),
    ]

    multi_observations, multi_report, hair_details = _persist_multiperformer_hair_stage(
        sweep,
        rows=rows,
        base_details=_machine_base_details(),
    )

    nail_details = {domain: [dict(item) for item in claims] for domain, claims in hair_details.items()}
    nail_details["fingernails_detail"] = [
        _claim("fingernails_detail", "fingernails-a"),
        _claim("fingernails_detail", "fingernails-b"),
    ]
    nail_details["toenails_detail"] = [
        _claim("toenails_detail", "toenails-a"),
        _claim("toenails_detail", "toenails-b"),
    ]
    nail_capabilities = {
        "coarse-face-view",
        "coarse-full-body-view",
        "eyes-detail",
        "hands-detail",
        "feet-detail",
        "hair-detail",
        "skin-detail",
        "fingernails-detail",
        "toenails-detail",
        *{
            str(DOMAIN_REQUIREMENTS[domain]["capability"])
            for domain in HUMAN_ONLY_DOMAINS
        },
    }
    nail_evidence = build_observation_evidence(
        performer_id="42",
        bodyrig_revision="a" * 40,
        baseline_source_manifest_sha256="b" * 64,
        analyzer_adapter="bodyrig-photoidentity-coarse-openpose-schp-human-nails-composite",
        analyzer_revision="1",
        analyzer_capabilities=sorted(nail_capabilities),
        candidate_scenes=20,
        source_files_scanned=20,
        scan_exhausted=True,
        rows=rows,
        detail_evidence=nail_details,
    )
    nail_observations, nail_report, _ = write_bundle(sweep / "nail-attested-evidence", nail_evidence)

    selected_fingernails = [
        _selected(fingernail_regions[0], "fingernails-a", "finger-a"),
        _selected(fingernail_regions[1], "fingernails-b", "finger-b"),
    ]
    selected_toenails = [
        _selected("left_toenails", "toenails-a", "toe-a"),
        _selected("right_toenails", "toenails-b", "toe-b"),
    ]
    nail_receipt = {
        "format": "bodyrig-photoidentity-nail-source-attestation",
        "version": 1,
        "policy_revision": "photoidentity-nail-source-attestation-v1",
        "performer_id": "42",
        "bodyrig_revision": "a" * 40,
        "prior_stage": "multiperformer-detail",
        "prior_observation_evidence_sha256": _sha(multi_observations),
        "prior_sufficiency_report_sha256": _sha(multi_report),
        "adapter": "human-source-nail-detail-attestation",
        "adapter_revision": "1",
        "attested_domains": ["fingernails_detail", "toenails_detail"],
        "selected_fingernails": selected_fingernails,
        "selected_toenails": selected_toenails,
        "quality_note": "Reviewed real fingernail and toenail source detail from both sides.",
        "operator_supplied": True,
        "source_grounded": True,
        "generic_guessing_permitted": False,
        "production_activation": False,
        "enriched_observation_evidence_sha256": _sha(nail_observations),
        "enriched_sufficiency_report_sha256": _sha(nail_report),
    }
    nail_receipt_path = sweep / "photoidentity-nail-source-attestation.json"
    _write(nail_receipt_path, nail_receipt)

    final_details = {domain: [dict(item) for item in claims] for domain, claims in nail_details.items()}
    final_details["fingernails_detail"][0]["quality"] = final_fingernail_quality
    final_details.update(
        {
            "body_rear": [_claim("body_rear", "rear-a")],
            "torso_chest": [
                _claim("torso_chest", "torso-a"),
                _claim("torso_chest", "torso-b"),
            ],
            "waist_hips": [
                _claim("waist_hips", "waist-a"),
                _claim("waist_hips", "waist-b"),
            ],
        }
    )
    all_capabilities = sorted({str(item["capability"]) for item in DOMAIN_REQUIREMENTS.values()})
    final_evidence = build_observation_evidence(
        performer_id="42",
        bodyrig_revision="a" * 40,
        baseline_source_manifest_sha256="b" * 64,
        analyzer_adapter="bodyrig-photoidentity-source-human-anatomy-composite",
        analyzer_revision="1",
        analyzer_capabilities=all_capabilities,
        candidate_scenes=20,
        source_files_scanned=20,
        scan_exhausted=True,
        rows=rows,
        detail_evidence=final_details,
    )
    final_observations, final_report, final_status = write_bundle(
        sweep / "anatomy-attested-evidence", final_evidence
    )
    assert final_status["source_evidence_sufficient"] is True

    anatomy_receipt = {
        "format": "bodyrig-photoidentity-anatomy-source-attestation",
        "version": 1,
        "policy_revision": "photoidentity-anatomy-source-attestation-v1",
        "performer_id": "42",
        "bodyrig_revision": "a" * 40,
        "prior_stage": "nail-attested",
        "prior_observation_evidence_sha256": _sha(nail_observations),
        "prior_sufficiency_report_sha256": _sha(nail_report),
        "adapter": "human-source-anatomy-observability-attestation",
        "adapter_revision": "1",
        "attested_domains": ["body_rear", "torso_chest", "waist_hips"],
        "selected_body_rear": [_selected("rear_body", "rear-a", "rear-a")],
        "selected_torso_chest": [
            _selected("torso_chest", "torso-a", "torso-a"),
            _selected("torso_chest", "torso-b", "torso-b"),
        ],
        "selected_waist_hips": [
            _selected("waist_hips", "waist-a", "waist-a"),
            _selected("waist_hips", "waist-b", "waist-b"),
        ],
        "confirm_rear_view": True,
        "confirm_torso_chest_anatomy_visible": True,
        "confirm_waist_hips_anatomy_visible": True,
        "quality_note": "Reviewed real rear, torso/chest and waist/hips source anatomy in sufficient detail.",
        "operator_supplied": True,
        "source_grounded": True,
        "generic_guessing_permitted": False,
        "production_activation": False,
        "enriched_observation_evidence_sha256": _sha(final_observations),
        "enriched_sufficiency_report_sha256": _sha(final_report),
    }
    anatomy_receipt_path = sweep / "photoidentity-anatomy-source-attestation.json"
    _write(anatomy_receipt_path, anatomy_receipt)

    if remove_multiperformer_lineage:
        shutil.rmtree(sweep / "multiperformer-detail-evidence")
        shutil.rmtree(sweep / "multiperformer-detail-source-authority")
        (sweep / MULTIPERFORMER_RECEIPT_NAME).unlink()
    return sweep, final_observations, final_report


def test_valid_registration_chain_requires_hair_nails_and_anatomy_receipts(tmp_path: Path) -> None:
    _, observations, report = _build_chain(tmp_path)
    result = validate_registration_source_chain(
        report,
        observations,
        expected_performer_id="42",
        expected_bodyrig_revision="a" * 40,
        expected_baseline_source_manifest_sha256="b" * 64,
    )
    assert result["report"]["source_evidence_sufficient"] is True
    assert result["policy_revision"] == "photoidentity-human-source-chain-v2"
    assert result["multiperformer_detail"] is not None


def test_tampered_nail_receipt_binding_fails_closed(tmp_path: Path) -> None:
    sweep, observations, report = _build_chain(tmp_path)
    receipt_path = sweep / "photoidentity-nail-source-attestation.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["enriched_observation_evidence_sha256"] = "0" * 64
    _write(receipt_path, receipt)
    with pytest.raises(PhotoIdentitySourceChainError, match="nail receipt no longer binds exact nail observation"):
        validate_registration_source_chain(report, observations)


def test_final_claims_must_match_human_receipt_semantics(tmp_path: Path) -> None:
    _, observations, report = _build_chain(tmp_path, final_fingernail_quality=0.92)
    with pytest.raises(PhotoIdentitySourceChainError, match="final fingernails_detail claims do not match human source receipt"):
        validate_registration_source_chain(report, observations)


def test_fingernail_attestation_requires_left_and_right_source_coverage(tmp_path: Path) -> None:
    _, observations, report = _build_chain(
        tmp_path,
        fingernail_regions=("left_fingernails", "left_fingernails"),
    )
    with pytest.raises(PhotoIdentitySourceChainError, match="Fingernail attestation source coverage is incomplete"):
        validate_registration_source_chain(report, observations)


def test_target_detail_claims_without_aggregation_lineage_fail_closed(tmp_path: Path) -> None:
    _, observations, report = _build_chain(tmp_path, remove_multiperformer_lineage=True)
    with pytest.raises(
        PhotoIdentitySourceChainError,
        match="target-detail claims exist without persisted multi-performer aggregation lineage",
    ):
        validate_registration_source_chain(report, observations)

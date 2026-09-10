from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoidentity_authority import DETAIL_DOMAIN_AUTHORITY
from bodyrig.photoidentity_evidence import DOMAIN_REQUIREMENTS, build_observation_evidence, write_bundle
from bodyrig.photoidentity_source_chain import (
    PhotoIdentitySourceChainError,
    validate_registration_source_chain,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _build_chain(
    tmp_path: Path,
    *,
    fingernail_regions: tuple[str, str] = ("left_fingernails", "right_fingernails"),
    final_fingernail_quality: float = 0.91,
) -> tuple[Path, Path, Path]:
    sweep = tmp_path / "sweep"
    sweep.mkdir()
    rows = [
        _row("front-a", 1, "front"),
        _row("front-b", 2, "front"),
        _row("left-a", 3, "left_profile"),
        _row("right-a", 4, "right_profile"),
    ]

    base_detail_domains = ("eyes_detail", "hands", "feet", "hair_hairline", "skin_detail")
    nail_details: dict[str, list[dict[str, object]]] = {
        domain: [
            _claim(domain, f"{domain}-a"),
            _claim(domain, f"{domain}-b"),
        ]
        for domain in base_detail_domains
    }
    nail_details["fingernails_detail"] = [
        _claim("fingernails_detail", "fingernails-a", final_fingernail_quality),
        _claim("fingernails_detail", "fingernails-b", 0.91),
    ]
    nail_details["toenails_detail"] = [
        _claim("toenails_detail", "toenails-a"),
        _claim("toenails_detail", "toenails-b"),
    ]
    nail_capabilities = sorted(
        {
            "coarse-face-view",
            "coarse-full-body-view",
            "eyes-detail",
            "hands-detail",
            "feet-detail",
            "hair-detail",
            "skin-detail",
            "fingernails-detail",
            "toenails-detail",
        }
    )
    nail_evidence = build_observation_evidence(
        performer_id="42",
        bodyrig_revision="a" * 40,
        baseline_source_manifest_sha256="b" * 64,
        analyzer_adapter="bodyrig-photoidentity-coarse-openpose-schp-human-nails-composite",
        analyzer_revision="1",
        analyzer_capabilities=nail_capabilities,
        candidate_scenes=20,
        source_files_scanned=20,
        scan_exhausted=True,
        rows=rows,
        detail_evidence=nail_details,
    )
    nail_observations, nail_report, _ = write_bundle(sweep / "nail-attested-evidence", nail_evidence)

    selected_fingernails = [
        _selected(fingernail_regions[0], "fingernails-a", "finger-a", final_fingernail_quality),
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
    nail_receipt_path.write_text(json.dumps(nail_receipt, sort_keys=True), encoding="utf-8")

    final_details = {domain: [dict(item) for item in claims] for domain, claims in nail_details.items()}
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
    anatomy_receipt_path.write_text(json.dumps(anatomy_receipt, sort_keys=True), encoding="utf-8")
    return sweep, final_observations, final_report


def test_valid_registration_chain_requires_both_human_receipts(tmp_path: Path) -> None:
    _, observations, report = _build_chain(tmp_path)
    result = validate_registration_source_chain(
        report,
        observations,
        expected_performer_id="42",
        expected_bodyrig_revision="a" * 40,
        expected_baseline_source_manifest_sha256="b" * 64,
    )
    assert result["report"]["source_evidence_sufficient"] is True
    assert result["policy_revision"] == "photoidentity-human-source-chain-v1"


def test_tampered_nail_receipt_binding_fails_closed(tmp_path: Path) -> None:
    sweep, observations, report = _build_chain(tmp_path)
    receipt_path = sweep / "photoidentity-nail-source-attestation.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["enriched_observation_evidence_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
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

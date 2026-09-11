from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoidentity_authority import (
    DETAIL_DOMAIN_AUTHORITY,
    PhotoIdentityAuthorityError,
    validate_authoritative_bundle,
)
from bodyrig.photoidentity_evidence import DOMAIN_REQUIREMENTS, build_observation_evidence, write_bundle
from bodyrig.photoidentity_multiperformer_detail_aggregate import (
    FORMAT as MULTIPERFORMER_DETAIL_FORMAT,
    POLICY_REVISION as MULTIPERFORMER_DETAIL_POLICY_REVISION,
    VERSION as MULTIPERFORMER_DETAIL_VERSION,
)
from bodyrig.photoidentity_registry import (
    PhotoIdentityRegistryError,
    register_body_job_photoidentity_evidence,
    require_body_job_photoidentity_evidence,
)
from bodyrig.photoidentity_target_crop_quality_attestation import (
    ADAPTER as TARGET_DETAIL_ADAPTER,
    ADAPTER_REVISION as TARGET_DETAIL_REVISION,
    DOMAIN_MACHINE_AUTHORITY as TARGET_DETAIL_MACHINE_AUTHORITY,
    FORMAT as TARGET_DETAIL_FORMAT,
    HUMAN_ONLY_DOMAINS as TARGET_DETAIL_HUMAN_ONLY_DOMAINS,
    HUMAN_QUALITY_BASIS as TARGET_DETAIL_HUMAN_QUALITY_BASIS,
    POLICY as TARGET_DETAIL_POLICY,
    SUPPORTED_QUALITY_DOMAINS as TARGET_DETAIL_SUPPORTED_DOMAINS,
    VERSION as TARGET_DETAIL_VERSION,
)
import bodyrig.photoidentity_registry as registry


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _row(scene: str, view: str) -> dict[str, object]:
    return {
        "scene_id": scene,
        "source_ordinal": int(scene.removeprefix("scene")),
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


def _sufficient_bundle(
    tmp_path: Path,
    *,
    analyzer_adapter: str = "bodyrig-photoidentity-source-human-anatomy-composite",
    claim_adapter_override: tuple[str, str] | None = None,
) -> tuple[Path, Path]:
    capabilities = sorted({str(item["capability"]) for item in DOMAIN_REQUIREMENTS.values()})
    rows = [
        _row("scene1", "front"),
        _row("scene2", "front"),
        _row("scene3", "left_profile"),
        _row("scene4", "right_profile"),
    ]
    details: dict[str, list[dict[str, object]]] = {}
    for domain, requirement in DOMAIN_REQUIREMENTS.items():
        if requirement["capability"] in {"coarse-face-view", "coarse-full-body-view"}:
            continue
        _, authority_adapter, authority_revision = DETAIL_DOMAIN_AUTHORITY[domain]
        if claim_adapter_override is not None and domain == claim_adapter_override[0]:
            authority_adapter = claim_adapter_override[1]
        details[domain] = [
            {
                "scene_id": f"{domain}-{index}",
                "quality": 0.97,
                "source_derived": True,
                "adapter": authority_adapter,
                "revision": authority_revision,
            }
            for index in range(int(requirement["minimum_distinct_scenes"]))
        ]
    evidence = build_observation_evidence(
        performer_id="42",
        bodyrig_revision="a" * 40,
        baseline_source_manifest_sha256="b" * 64,
        analyzer_adapter=analyzer_adapter,
        analyzer_revision="1",
        analyzer_capabilities=capabilities,
        candidate_scenes=80,
        source_files_scanned=50,
        scan_exhausted=True,
        rows=rows,
        detail_evidence=details,
    )
    observations, report, _ = write_bundle(tmp_path / "source-bundle", evidence)
    return observations, report


def _patch_job_authority(monkeypatch: pytest.MonkeyPatch, job_root: Path) -> None:
    job = {
        "kind": "body-build",
        "status": "succeeded",
        "person_id": "person-fixture",
        "bodyrig_revision": "a" * 40,
    }
    monkeypatch.setattr(
        registry,
        "_job_authority",
        lambda body_job_id: (job, "42", "a" * 40, job_root, "b" * 64),
    )


def _human_receipts(
    tmp_path: Path,
    *,
    nail_extra: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    receipt_root = tmp_path / "human-source-receipts"
    receipt_root.mkdir(exist_ok=True)
    nail = receipt_root / "nail.json"
    anatomy = receipt_root / "anatomy.json"
    boundary = {
        "version": 1,
        "operator_supplied": True,
        "source_grounded": True,
        "generic_guessing_permitted": False,
        "production_activation": False,
    }
    _write(
        nail,
        {
            **boundary,
            "format": "bodyrig-photoidentity-nail-source-attestation",
            **(nail_extra or {}),
        },
    )
    _write(
        anatomy,
        {**boundary, "format": "bodyrig-photoidentity-anatomy-source-attestation"},
    )
    return nail, anatomy


def _target_claims(observations: Path) -> dict[str, list[dict[str, object]]]:
    value = json.loads(observations.read_text(encoding="utf-8"))
    details = value["detail_evidence"]
    result: dict[str, list[dict[str, object]]] = {}
    for domain, claims in details.items():
        selected = [
            dict(claim)
            for claim in claims
            if claim.get("adapter") == TARGET_DETAIL_ADAPTER
            and claim.get("revision") == TARGET_DETAIL_REVISION
        ]
        if selected:
            result[domain] = selected
    return result


def _patch_valid_multiperformer_source_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    observations: Path,
    report: Path,
) -> None:
    aggregation_observations_sha = "c" * 64
    aggregation_report_sha = "d" * 64
    nail, anatomy = _human_receipts(
        tmp_path,
        nail_extra={
            "prior_stage": "multiperformer-detail",
            "prior_observation_evidence_sha256": aggregation_observations_sha,
            "prior_sufficiency_report_sha256": aggregation_report_sha,
        },
    )
    authority_root = tmp_path / "live-multiperformer-authority"
    authority_root.mkdir()

    target_claims = _target_claims(observations)
    by_scene: dict[str, list[tuple[str, dict[str, object]]]] = {}
    for domain, claims in target_claims.items():
        for claim in claims:
            by_scene.setdefault(str(claim["scene_id"]), []).append((domain, claim))

    quality_entries: list[dict[str, object]] = []
    quality_paths: list[Path] = []
    for index, (scene, scene_claims) in enumerate(sorted(by_scene.items())):
        selected_claims: list[dict[str, object]] = []
        for domain, claim in sorted(scene_claims, key=lambda item: item[0]):
            selected: dict[str, object] = {
                "sample_id": f"targetsample-{index:04d}",
                "domain": domain,
                "scene_id": scene,
                "target_crop_sha256": hashlib.sha256(f"crop-{scene}-{domain}".encode()).hexdigest(),
                "quality": float(claim["quality"]),
                "source_derived": True,
                "adapter": TARGET_DETAIL_ADAPTER,
                "revision": TARGET_DETAIL_REVISION,
            }
            if domain in TARGET_DETAIL_HUMAN_ONLY_DOMAINS:
                selected.update(
                    {
                        "quality_basis": TARGET_DETAIL_HUMAN_QUALITY_BASIS,
                        "human_visibility_attested": True,
                        "machine_observability_used": False,
                    }
                )
            else:
                machine_adapter, machine_revision = TARGET_DETAIL_MACHINE_AUTHORITY[domain]
                selected.update(
                    {
                        "machine_adapter": machine_adapter,
                        "machine_revision": machine_revision,
                    }
                )
            selected_claims.append(selected)

        path = authority_root / f"source-quality-{index}.json"
        domains = sorted(domain for domain, _ in scene_claims)
        quality = {
            "format": TARGET_DETAIL_FORMAT,
            "version": TARGET_DETAIL_VERSION,
            "policy": TARGET_DETAIL_POLICY,
            "bodyrig_revision": "a" * 40,
            "performer_id": "42",
            "scene_id": scene,
            "human_target_isolation_attestation_sha256": hashlib.sha256(f"isolation-{index}".encode()).hexdigest(),
            "target_crop_detail_enrichment_sha256": hashlib.sha256(f"enrichment-{index}".encode()).hexdigest(),
            "private_analysis_index_sha256": hashlib.sha256(f"private-{index}".encode()).hexdigest(),
            "adapter": TARGET_DETAIL_ADAPTER,
            "adapter_revision": TARGET_DETAIL_REVISION,
            "selected_domains": domains,
            "selected_claims": selected_claims,
            "human_source_detail_quality_attested": True,
            "quality_note": "Reviewed the exact isolated target crop and confirmed sufficient native source detail for the selected identity domain.",
            "source_detail_quality_authority": True,
            "photoidentity_source_evidence_authority": False,
            "generic_guessing_permitted": False,
            "reconstruction_permitted": False,
            "production_activation": False,
        }
        _write(path, quality)
        quality_paths.append(path)
        quality_entries.append(
            {
                "receipt_sha256": _sha(path),
                "stored_name": f"quality-{_sha(path)}.json",
                "scene_id": scene,
                "domains": domains,
            }
        )

    quality_entries.sort(key=lambda item: str(item["receipt_sha256"]))
    quality_paths_by_hash = sorted(quality_paths, key=_sha)
    added_counts = {
        domain: len(target_claims.get(domain, []))
        for domain in sorted(TARGET_DETAIL_SUPPORTED_DOMAINS)
    }
    aggregation = {
        "format": MULTIPERFORMER_DETAIL_FORMAT,
        "version": MULTIPERFORMER_DETAIL_VERSION,
        "policy_revision": MULTIPERFORMER_DETAIL_POLICY_REVISION,
        "performer_id": "42",
        "bodyrig_revision": "a" * 40,
        "baseline_source_manifest_sha256": "b" * 64,
        "prior_stage": "human-parsing",
        "prior_observation_evidence_sha256": "e" * 64,
        "prior_sufficiency_report_sha256": "f" * 64,
        "quality_receipts": quality_entries,
        "quality_receipt_count": len(quality_entries),
        "added_claim_counts": added_counts,
        "composite_analyzer": {
            "adapter": "bodyrig-photoidentity-coarse-openpose-schp-human-target-detail-composite",
            "revision": "1",
            "capabilities": [],
        },
        "enriched_observation_evidence_sha256": aggregation_observations_sha,
        "enriched_sufficiency_report_sha256": aggregation_report_sha,
        "source_grounded": True,
        "generic_guessing_permitted": False,
        "production_activation": False,
    }
    aggregation_path = authority_root / "aggregation.json"
    _write(aggregation_path, aggregation)

    report_value = json.loads(report.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        registry,
        "validate_registration_source_chain",
        lambda *args, **kwargs: {
            "report": report_value,
            "policy_revision": "photoidentity-human-source-chain-v2",
            "nail_attestation": str(nail),
            "nail_attestation_sha256": _sha(nail),
            "anatomy_attestation": str(anatomy),
            "anatomy_attestation_sha256": _sha(anatomy),
            "multiperformer_detail": {
                "receipt": str(aggregation_path),
                "receipt_sha256": _sha(aggregation_path),
                "quality_receipts": [str(path) for path in quality_paths_by_hash],
                "quality_receipt_sha256s": [_sha(path) for path in quality_paths_by_hash],
                "observation_evidence_sha256": aggregation_observations_sha,
                "sufficiency_report_sha256": aggregation_report_sha,
            },
        },
    )


def test_register_and_require_bind_exact_sufficient_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observations, report = _sufficient_bundle(tmp_path)
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)
    _patch_valid_multiperformer_source_chain(monkeypatch, tmp_path, observations, report)

    result = register_body_job_photoidentity_evidence(
        "job-" + "1" * 32,
        report_path=report,
        observation_path=observations,
    )

    assert result["version"] == 3
    assert result["source_chain_policy_revision"] == "photoidentity-human-source-chain-v2"
    assert result["multiperformer_detail"] is not None
    assert result["source_evidence_sufficient"] is True
    assert result["human_review_render_permitted"] is True
    assert result["generic_guessing_permitted"] is False
    assert result["production_activation"] is False
    required = require_body_job_photoidentity_evidence("person-fixture", "job-" + "1" * 32)
    assert required["source_evidence_sufficient"] is True
    assert required["human_review_render_permitted"] is True


def test_authority_rejects_forged_complete_analyzer_name(tmp_path: Path) -> None:
    observations, report = _sufficient_bundle(tmp_path, analyzer_adapter="fixture-complete")
    with pytest.raises(PhotoIdentityAuthorityError, match="analyzer is not registered authority"):
        validate_authoritative_bundle(report, observations, require_sufficient=True)


def test_authority_rejects_forged_human_nail_claim_adapter(tmp_path: Path) -> None:
    observations, report = _sufficient_bundle(
        tmp_path,
        claim_adapter_override=("fingernails_detail", "generic-nail-prior"),
    )
    with pytest.raises(
        PhotoIdentityAuthorityError,
        match="fingernails_detail requires human-source-nail-detail-attestation@1",
    ):
        validate_authoritative_bundle(report, observations, require_sufficient=True)


def test_authority_rejects_forged_human_anatomy_claim_adapter(tmp_path: Path) -> None:
    observations, report = _sufficient_bundle(
        tmp_path,
        claim_adapter_override=("torso_chest", "generic-body-prior"),
    )
    with pytest.raises(
        PhotoIdentityAuthorityError,
        match="torso_chest requires human-source-anatomy-observability-attestation@1",
    ):
        validate_authoritative_bundle(report, observations, require_sufficient=True)


def test_registry_is_create_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observations, report = _sufficient_bundle(tmp_path)
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)
    _patch_valid_multiperformer_source_chain(monkeypatch, tmp_path, observations, report)
    job_id = "job-" + "2" * 32

    register_body_job_photoidentity_evidence(job_id, report_path=report, observation_path=observations)
    with pytest.raises(PhotoIdentityRegistryError, match="create-only"):
        register_body_job_photoidentity_evidence(job_id, report_path=report, observation_path=observations)


def test_registry_fails_closed_if_registered_report_is_tampered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observations, report = _sufficient_bundle(tmp_path)
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)
    _patch_valid_multiperformer_source_chain(monkeypatch, tmp_path, observations, report)
    job_id = "job-" + "3" * 32
    register_body_job_photoidentity_evidence(job_id, report_path=report, observation_path=observations)

    stored = job_root / "photoidentity-evidence" / "photoidentity-evidence.json"
    value = json.loads(stored.read_text(encoding="utf-8"))
    value["human_review_render_permitted"] = False
    stored.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(PhotoIdentityRegistryError, match="mismatch|inconsistent"):
        require_body_job_photoidentity_evidence("person-fixture", job_id)


def test_registry_fails_closed_if_registered_human_receipt_is_tampered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observations, report = _sufficient_bundle(tmp_path)
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)
    _patch_valid_multiperformer_source_chain(monkeypatch, tmp_path, observations, report)
    job_id = "job-" + "8" * 32
    register_body_job_photoidentity_evidence(job_id, report_path=report, observation_path=observations)

    stored = job_root / "photoidentity-evidence" / "source-authority" / "nail-source-attestation.json"
    stored.write_text(stored.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(
        PhotoIdentityRegistryError,
        match="nail_attestation_sha256|nail source attestation receipt hash mismatch",
    ):
        require_body_job_photoidentity_evidence("person-fixture", job_id)


def test_registry_persists_and_requires_multiperformer_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observations, report = _sufficient_bundle(
        tmp_path,
        claim_adapter_override=("eyes_detail", TARGET_DETAIL_ADAPTER),
    )
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)
    _patch_valid_multiperformer_source_chain(monkeypatch, tmp_path, observations, report)
    job_id = "job-" + "9" * 32

    result = register_body_job_photoidentity_evidence(
        job_id,
        report_path=report,
        observation_path=observations,
    )
    assert result["multiperformer_detail"] is not None
    required = require_body_job_photoidentity_evidence("person-fixture", job_id)
    assert required["source_evidence_sufficient"] is True

    quality_root = (
        job_root
        / "photoidentity-evidence"
        / "source-authority"
        / "multiperformer-detail"
        / "quality-receipts"
    )
    next(quality_root.glob("quality-*.json")).unlink()
    with pytest.raises(PhotoIdentityRegistryError, match="quality receipt set changed"):
        require_body_job_photoidentity_evidence("person-fixture", job_id)


def test_registry_human_only_quality_receipt_rejects_machine_provenance(tmp_path: Path) -> None:
    path = tmp_path / "quality.json"
    domain = "eyebrows_detail"
    receipt = {
        "format": TARGET_DETAIL_FORMAT,
        "version": TARGET_DETAIL_VERSION,
        "policy": TARGET_DETAIL_POLICY,
        "bodyrig_revision": "a" * 40,
        "performer_id": "42",
        "scene_id": "eyebrows_detail-0",
        "human_target_isolation_attestation_sha256": "1" * 64,
        "target_crop_detail_enrichment_sha256": "2" * 64,
        "private_analysis_index_sha256": "3" * 64,
        "adapter": TARGET_DETAIL_ADAPTER,
        "adapter_revision": TARGET_DETAIL_REVISION,
        "selected_domains": [domain],
        "selected_claims": [{
            "sample_id": "targetsample-0000",
            "domain": domain,
            "scene_id": "eyebrows_detail-0",
            "target_crop_sha256": "4" * 64,
            "quality": 0.97,
            "quality_basis": TARGET_DETAIL_HUMAN_QUALITY_BASIS,
            "human_visibility_attested": True,
            "machine_observability_used": False,
            "machine_adapter": "schp-atr18-source-observability",
            "source_derived": True,
            "adapter": TARGET_DETAIL_ADAPTER,
            "revision": TARGET_DETAIL_REVISION,
        }],
        "human_source_detail_quality_attested": True,
        "quality_note": "Reviewed the exact isolated eyebrow crop with sufficient source visibility.",
        "source_detail_quality_authority": True,
        "photoidentity_source_evidence_authority": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    _write(path, receipt)
    with pytest.raises(PhotoIdentityRegistryError, match="human-only hair claim authority boundary changed"):
        registry._quality_receipt_claims(path, performer_id="42", revision="a" * 40)


def test_missing_registry_blocks_preview_authority(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)
    with pytest.raises(PhotoIdentityRegistryError, match="remains blocked"):
        require_body_job_photoidentity_evidence("person-fixture", "job-" + "4" * 32)

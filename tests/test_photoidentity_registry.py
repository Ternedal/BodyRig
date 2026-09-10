from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.photoidentity_authority import DETAIL_DOMAIN_AUTHORITY
from bodyrig.photoidentity_evidence import DOMAIN_REQUIREMENTS, build_observation_evidence, write_bundle
from bodyrig.photoidentity_registry import (
    PhotoIdentityRegistryError,
    register_body_job_photoidentity_evidence,
    require_body_job_photoidentity_evidence,
)
import bodyrig.photoidentity_registry as registry


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


def test_register_and_require_bind_exact_sufficient_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observations, report = _sufficient_bundle(tmp_path)
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)

    result = register_body_job_photoidentity_evidence(
        "job-" + "1" * 32,
        report_path=report,
        observation_path=observations,
    )

    assert result["source_evidence_sufficient"] is True
    assert result["human_review_render_permitted"] is True
    assert result["generic_guessing_permitted"] is False
    assert result["production_activation"] is False
    required = require_body_job_photoidentity_evidence("person-fixture", "job-" + "1" * 32)
    assert required["source_evidence_sufficient"] is True
    assert required["human_review_render_permitted"] is True


def test_registry_rejects_forged_complete_analyzer_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observations, report = _sufficient_bundle(tmp_path, analyzer_adapter="fixture-complete")
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)

    with pytest.raises(PhotoIdentityRegistryError, match="analyzer is not registered authority"):
        register_body_job_photoidentity_evidence(
            "job-" + "5" * 32,
            report_path=report,
            observation_path=observations,
        )
    assert not (job_root / "photoidentity-evidence").exists()


def test_registry_rejects_forged_human_nail_claim_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observations, report = _sufficient_bundle(
        tmp_path,
        claim_adapter_override=("fingernails_detail", "generic-nail-prior"),
    )
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)

    with pytest.raises(PhotoIdentityRegistryError, match="fingernails_detail requires human-source-nail-detail-attestation@1"):
        register_body_job_photoidentity_evidence(
            "job-" + "6" * 32,
            report_path=report,
            observation_path=observations,
        )
    assert not (job_root / "photoidentity-evidence").exists()


def test_registry_rejects_forged_human_anatomy_claim_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observations, report = _sufficient_bundle(
        tmp_path,
        claim_adapter_override=("torso_chest", "generic-body-prior"),
    )
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)

    with pytest.raises(
        PhotoIdentityRegistryError,
        match="torso_chest requires human-source-anatomy-observability-attestation@1",
    ):
        register_body_job_photoidentity_evidence(
            "job-" + "7" * 32,
            report_path=report,
            observation_path=observations,
        )
    assert not (job_root / "photoidentity-evidence").exists()


def test_registry_is_create_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observations, report = _sufficient_bundle(tmp_path)
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)
    job_id = "job-" + "2" * 32

    register_body_job_photoidentity_evidence(job_id, report_path=report, observation_path=observations)
    with pytest.raises(PhotoIdentityRegistryError, match="create-only"):
        register_body_job_photoidentity_evidence(job_id, report_path=report, observation_path=observations)


def test_registry_fails_closed_if_registered_report_is_tampered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observations, report = _sufficient_bundle(tmp_path)
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)
    job_id = "job-" + "3" * 32
    register_body_job_photoidentity_evidence(job_id, report_path=report, observation_path=observations)

    stored = job_root / "photoidentity-evidence" / "photoidentity-evidence.json"
    value = json.loads(stored.read_text(encoding="utf-8"))
    value["human_review_render_permitted"] = False
    stored.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(PhotoIdentityRegistryError, match="mismatch|inconsistent"):
        require_body_job_photoidentity_evidence("person-fixture", job_id)


def test_missing_registry_blocks_preview_authority(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    job_root = tmp_path / "job-root"
    job_root.mkdir()
    _patch_job_authority(monkeypatch, job_root)
    with pytest.raises(PhotoIdentityRegistryError, match="remains blocked"):
        require_body_job_photoidentity_evidence("person-fixture", "job-" + "4" * 32)

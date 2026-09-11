from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoidentity_source_status as status_module
from bodyrig.photoidentity_authority import DETAIL_DOMAIN_AUTHORITY
from bodyrig.photoidentity_evidence import DOMAIN_REQUIREMENTS, build_observation_evidence, write_bundle
from bodyrig.photoidentity_multiperformer_review_prepare import (
    FORMAT as MULTI_REVIEW_FORMAT,
    PRIVATE_FORMAT as MULTI_REVIEW_PRIVATE_FORMAT,
    PRIVATE_VERSION as MULTI_REVIEW_PRIVATE_VERSION,
    VERSION as MULTI_REVIEW_VERSION,
)
from bodyrig.photoidentity_multiperformer_source_discovery import (
    FORMAT as MULTI_DISCOVERY_FORMAT,
    PRIVATE_FORMAT as MULTI_DISCOVERY_PRIVATE_FORMAT,
    PRIVATE_VERSION as MULTI_DISCOVERY_PRIVATE_VERSION,
    VERSION as MULTI_DISCOVERY_VERSION,
)
from bodyrig.photoidentity_source_status import PhotoIdentitySourceStatusError, inspect_source_status
from bodyrig.photoidentity_target_crop_quality_attestation import (
    ADAPTER as TARGET_DETAIL_ADAPTER,
    ADAPTER_REVISION as TARGET_DETAIL_REVISION,
    FORMAT as TARGET_DETAIL_FORMAT,
    HUMAN_ONLY_DOMAINS,
    HUMAN_QUALITY_BASIS,
    POLICY as TARGET_DETAIL_POLICY,
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


def _claim(domain: str, scene: str) -> dict[str, object]:
    _, adapter, revision = DETAIL_DOMAIN_AUTHORITY[domain]
    return {
        "scene_id": scene,
        "quality": 0.91,
        "source_derived": True,
        "adapter": adapter,
        "revision": revision,
    }


def _rows() -> list[dict[str, object]]:
    return [
        _row("front-a", 1, "front"),
        _row("front-b", 2, "front"),
        _row("left-a", 3, "left_profile"),
        _row("right-a", 4, "right_profile"),
    ]


def _base_details() -> dict[str, list[dict[str, object]]]:
    domains = ("eyes_detail", "hands", "feet", "hair_hairline", "skin_detail")
    return {
        domain: [_claim(domain, f"{domain}-a"), _claim(domain, f"{domain}-b")]
        for domain in domains
    }


def _base_root(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "sweep"
    root.mkdir()
    evidence = build_observation_evidence(
        performer_id="42",
        bodyrig_revision="a" * 40,
        baseline_source_manifest_sha256="b" * 64,
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
        candidate_scenes=20,
        source_files_scanned=20,
        scan_exhausted=True,
        rows=_rows(),
        detail_evidence=_base_details(),
    )
    _, _, report = write_bundle(root / "human-parsing-evidence", evidence)
    return root, report


def _discovery_root(tmp_path: Path, *, candidates: int = 2) -> Path:
    root = tmp_path / "multi"
    root.mkdir()
    public_rows = [
        {
            "candidate_id": f"multicand-{index:032x}",
            "scene_id": f"scene-multi-{index}",
            "performer_count": 2,
            "width": 1920,
            "height": 1080,
            "duration": 60.0,
            "framerate": 30.0,
            "review_priority_score": 10.0 - index,
        }
        for index in range(1, candidates + 1)
    ]
    public = {
        "format": MULTI_DISCOVERY_FORMAT,
        "version": MULTI_DISCOVERY_VERSION,
        "bodyrig_revision": "a" * 40,
        "performer_id": "42",
        "stash_scene_count": candidates,
        "inventory_page_count": 1,
        "inventory_page_size": 250,
        "inventory_schema": "fixture",
        "stash_inventory_exhausted": True,
        "candidate_count": len(public_rows),
        "candidates": public_rows,
        "source_paths_persisted": False,
        "source_media_hashed_at_discovery": False,
        "target_track_selected": False,
        "human_identity_attestation_required": bool(public_rows),
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "human_review_render_permitted": False,
        "production_activation": False,
    }
    public_path = root / "multiperformer-source-candidates.json"
    _write(public_path, public)
    private = {
        "format": MULTI_DISCOVERY_PRIVATE_FORMAT,
        "version": MULTI_DISCOVERY_PRIVATE_VERSION,
        "bodyrig_revision": "a" * 40,
        "performer_id": "42",
        "public_manifest_sha256": _sha(public_path),
        "candidate_count": len(public_rows),
        "candidates": [
            {
                "candidate_id": row["candidate_id"],
                "scene_id": row["scene_id"],
                "source_path": f"C:/fixture/{index}.mp4",
                "performer_ids": ["42", "99"],
            }
            for index, row in enumerate(public_rows, start=1)
        ],
        "source_paths_private": True,
        "target_track_selected": False,
        "production_activation": False,
    }
    _write(root / "private-multiperformer-source-candidates" / "private-candidate-index.json", private)
    return root


def _review_root(discovery_root: Path, index: int) -> Path:
    candidate_id = f"multicand-{index:032x}"
    root = discovery_root / "track-reviews" / candidate_id
    public = {
        "format": MULTI_REVIEW_FORMAT,
        "version": MULTI_REVIEW_VERSION,
        "bodyrig_revision": "a" * 40,
        "performer_id": "42",
        "source_candidate_id": candidate_id,
        "scene_id": f"scene-multi-{index}",
        "source_media_sha256": hashlib.sha256(f"source-{index}".encode()).hexdigest(),
        "track_candidate_count": 1,
        "tracks": [],
        "source_paths_persisted": False,
        "target_track_selected": False,
        "human_identity_attestation_required": True,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "target_isolated_source_authority": False,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    public_path = root / "multiperformer-track-review-candidates.json"
    _write(public_path, public)
    private = {
        "format": MULTI_REVIEW_PRIVATE_FORMAT,
        "version": MULTI_REVIEW_PRIVATE_VERSION,
        "bodyrig_revision": "a" * 40,
        "performer_id": "42",
        "public_review_manifest_sha256": _sha(public_path),
        "source_candidate_id": candidate_id,
        "scene_id": public["scene_id"],
        "source_media_sha256": public["source_media_sha256"],
        "source_path": f"C:/fixture/{index}.mp4",
        "tracks": [],
        "source_paths_private": True,
        "production_activation": False,
    }
    _write(root / "private-track-review" / "private-review-index.json", private)
    return root


def _advance_to_quality(review_root: Path, index: int) -> tuple[Path, Path]:
    _write(review_root / "photoidentity-multiperformer-track-attestation.json", {"human_identity_attested": True})
    candidate_root = review_root / "target-isolation-candidates"
    _write(candidate_root / "multiperformer-target-isolation-candidates.json", {"format": "fixture"})
    _write(candidate_root / "private-target-source" / "private-target-source-index.json", {"format": "fixture"})
    _write(
        candidate_root / "photoidentity-multiperformer-target-isolation-attestation.json",
        {"human_target_isolation_attested": True},
    )
    enrichment = candidate_root / "target-crop-detail-enrichment"
    _write(enrichment / "target-crop-detail-enrichment.json", {"format": "fixture"})
    _write(enrichment / "private-analysis" / "private-analysis-index.json", {"format": "fixture"})
    scene = f"scene-multi-{index}"
    claims = [
        {
            "sample_id": f"targetsample-{index:04d}",
            "domain": domain,
            "scene_id": scene,
            "target_crop_sha256": hashlib.sha256(f"{scene}-{domain}".encode()).hexdigest(),
            "quality": 0.91,
            "quality_basis": HUMAN_QUALITY_BASIS,
            "human_visibility_attested": True,
            "machine_observability_used": False,
            "source_derived": True,
            "adapter": TARGET_DETAIL_ADAPTER,
            "revision": TARGET_DETAIL_REVISION,
        }
        for domain in sorted(HUMAN_ONLY_DOMAINS)
    ]
    quality = {
        "format": TARGET_DETAIL_FORMAT,
        "version": TARGET_DETAIL_VERSION,
        "policy": TARGET_DETAIL_POLICY,
        "bodyrig_revision": "a" * 40,
        "performer_id": "42",
        "scene_id": scene,
        "adapter": TARGET_DETAIL_ADAPTER,
        "adapter_revision": TARGET_DETAIL_REVISION,
        "selected_domains": sorted(HUMAN_ONLY_DOMAINS),
        "selected_claims": claims,
        "human_source_detail_quality_attested": True,
        "quality_note": "Human review confirms visible source-grounded hair identity detail in this isolated crop.",
        "source_detail_quality_authority": True,
        "photoidentity_source_evidence_authority": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    receipt = enrichment / "photoidentity-target-crop-detail-quality-attestation.json"
    _write(receipt, quality)
    return candidate_root, receipt


def _fake_aggregation(monkeypatch: pytest.MonkeyPatch, root: Path, base_report: dict[str, object]) -> dict[str, object]:
    aggregate_root = root / "fixture-multiperformer-aggregate"
    observations = aggregate_root / "photoidentity-observations.json"
    report_path = aggregate_root / "photoidentity-evidence.json"
    _write(observations, {"fixture": "observations"})
    _write(report_path, {"fixture": "report"})
    report = {
        **base_report,
        "source_evidence_sufficient": False,
        "reconstruction_permitted": False,
        "human_review_render_permitted": False,
    }
    result: dict[str, object] = {
        "report": report,
        "observations_path": observations,
        "report_path": report_path,
    }
    monkeypatch.setattr(status_module, "validate_multiperformer_detail_aggregation", lambda *_args, **_kwargs: result)
    return result


def _write_nail_stage(root: Path, aggregation: dict[str, object], *, prior_stage: str = "multiperformer-detail") -> None:
    (root / "nail-source-candidates.json").write_text("{}\n", encoding="utf-8")
    _write(root / "private-nail-source-candidates" / "private-candidate-index.json", {})
    details = _base_details()
    for domain in sorted(HUMAN_ONLY_DOMAINS):
        details[domain] = [_claim(domain, f"{domain}-a"), _claim(domain, f"{domain}-b")]
    details["fingernails_detail"] = [_claim("fingernails_detail", "finger-a"), _claim("fingernails_detail", "finger-b")]
    details["toenails_detail"] = [_claim("toenails_detail", "toe-a"), _claim("toenails_detail", "toe-b")]
    evidence = build_observation_evidence(
        performer_id="42",
        bodyrig_revision="a" * 40,
        baseline_source_manifest_sha256="b" * 64,
        analyzer_adapter="bodyrig-photoidentity-coarse-openpose-schp-human-nails-composite",
        analyzer_revision="1",
        analyzer_capabilities=sorted({
            "coarse-face-view", "coarse-full-body-view", "eyes-detail", "hands-detail", "feet-detail",
            "hair-detail", "skin-detail", "eyebrows-detail", "facial-hair-detail", "body-hair-detail",
            "fingernails-detail", "toenails-detail",
        }),
        candidate_scenes=20,
        source_files_scanned=20,
        scan_exhausted=True,
        rows=_rows(),
        detail_evidence=details,
    )
    write_bundle(root / "nail-attested-evidence", evidence)
    _write(
        root / "photoidentity-nail-source-attestation.json",
        {
            "attested_domains": ["fingernails_detail", "toenails_detail"],
            "prior_stage": prior_stage,
            "prior_observation_evidence_sha256": _sha(Path(aggregation["observations_path"])),
            "prior_sufficiency_report_sha256": _sha(Path(aggregation["report_path"])),
        },
    )


def test_base_evidence_cannot_skip_directly_to_nails(tmp_path: Path) -> None:
    root, _ = _base_root(tmp_path)
    result = inspect_source_status(root)
    assert result["stage"] == "multiperformer-discovery"
    assert result["avatar_render_permitted"] is False
    assert result["generic_guessing_permitted"] is False


def test_discovery_requires_human_track_choice(tmp_path: Path) -> None:
    root, _ = _base_root(tmp_path)
    multi = _discovery_root(tmp_path)
    result = inspect_source_status(root, multiperformer_root=multi)
    assert result["stage"] == "multiperformer-track-review-prepare"
    assert result["human_review_required"] is True
    assert len(result["available_source_candidate_ids"]) == 2


def test_track_review_walks_target_isolation_and_quality_stages(tmp_path: Path) -> None:
    root, _ = _base_root(tmp_path)
    multi = _discovery_root(tmp_path)
    review = _review_root(multi, 1)
    assert inspect_source_status(root, multiperformer_root=multi)["stage"] == "multiperformer-track-human-review"

    _write(review / "photoidentity-multiperformer-track-attestation.json", {"human_identity_attested": True})
    assert inspect_source_status(root, multiperformer_root=multi)["stage"] == "multiperformer-target-isolation-materialize"

    candidate = review / "target-isolation-candidates"
    _write(candidate / "multiperformer-target-isolation-candidates.json", {"format": "fixture"})
    _write(candidate / "private-target-source" / "private-target-source-index.json", {"format": "fixture"})
    assert inspect_source_status(root, multiperformer_root=multi)["stage"] == "multiperformer-target-isolation-human-review"

    _write(candidate / "photoidentity-multiperformer-target-isolation-attestation.json", {"human_target_isolation_attested": True})
    assert inspect_source_status(root, multiperformer_root=multi)["stage"] == "multiperformer-target-crop-enrich"

    _write(candidate / "target-crop-detail-enrichment" / "target-crop-detail-enrichment.json", {"format": "fixture"})
    _write(candidate / "target-crop-detail-enrichment" / "private-analysis" / "private-analysis-index.json", {"format": "fixture"})
    result = inspect_source_status(root, multiperformer_root=multi)
    assert result["stage"] == "multiperformer-target-detail-human-review"
    assert result["human_review_required"] is True


def test_one_hair_scene_never_routes_to_create_only_aggregation(tmp_path: Path) -> None:
    root, _ = _base_root(tmp_path)
    multi = _discovery_root(tmp_path, candidates=2)
    review = _review_root(multi, 1)
    _advance_to_quality(review, 1)
    result = inspect_source_status(root, multiperformer_root=multi)
    assert result["stage"] == "multiperformer-more-detail"
    assert set(result["missing_target_domains"]) == set(HUMAN_ONLY_DOMAINS)
    assert result["available_source_candidate_ids"] == [f"multicand-{2:032x}"]


def test_two_hair_scenes_route_to_atomic_aggregation(tmp_path: Path) -> None:
    root, _ = _base_root(tmp_path)
    multi = _discovery_root(tmp_path, candidates=2)
    for index in (1, 2):
        review = _review_root(multi, index)
        _advance_to_quality(review, index)
    result = inspect_source_status(root, multiperformer_root=multi)
    assert result["stage"] == "multiperformer-aggregation"
    assert result["missing_target_domains"] == []
    assert len(result["quality_receipts"]) == 2
    assert len(result["candidate_roots"]) == 2


def test_subthreshold_human_quality_fails_closed(tmp_path: Path) -> None:
    root, _ = _base_root(tmp_path)
    multi = _discovery_root(tmp_path, candidates=2)
    review = _review_root(multi, 1)
    _, receipt = _advance_to_quality(review, 1)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["selected_claims"][0]["quality"] = 0.20
    _write(receipt, value)
    with pytest.raises(PhotoIdentitySourceStatusError, match="below authority threshold"):
        inspect_source_status(root, multiperformer_root=multi)


def test_validated_aggregation_is_required_before_nails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, base_report = _base_root(tmp_path)
    aggregation = _fake_aggregation(monkeypatch, root, base_report)
    assert inspect_source_status(root)["stage"] == "nail-discovery"

    _write_nail_stage(root, aggregation, prior_stage="human-parsing")
    with pytest.raises(PhotoIdentitySourceStatusError, match="did not select the multi-performer detail prior"):
        inspect_source_status(root)

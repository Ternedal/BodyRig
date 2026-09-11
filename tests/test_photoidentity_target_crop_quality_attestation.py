from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoidentity_evidence import DETAIL_QUALITY_THRESHOLD
from bodyrig.photoidentity_multiperformer_target_attestation import FORMAT as ISOLATION_FORMAT
from bodyrig.photoidentity_multiperformer_target_attestation import POLICY as ISOLATION_POLICY
from bodyrig.photoidentity_target_crop_detail import OPENPOSE_ADAPTER, OPENPOSE_REVISION
from bodyrig.photoidentity_target_crop_enrich import FORMAT as ENRICHMENT_FORMAT
from bodyrig.photoidentity_target_crop_enrich import PRIVATE_FORMAT as PRIVATE_ENRICHMENT_FORMAT
from bodyrig.photoidentity_target_crop_quality_attestation import (
    HUMAN_QUALITY_BASIS,
    PhotoIdentityTargetCropQualityAttestationError,
    record_target_crop_quality_attestation,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path, *, score: float = 0.91, adapter: str = OPENPOSE_ADAPTER) -> tuple[Path, Path, str, Path]:
    revision = "a" * 40
    candidate_root = tmp_path / "candidate"
    enrichment_root = candidate_root / "target-crop-detail-enrichment"
    private_root = enrichment_root / "private-analysis"
    sample_id = "targetsample-0001"
    sample_root = private_root / sample_id
    sample_root.mkdir(parents=True)
    crop = sample_root / "accepted-target-crop.png"
    crop.write_bytes(b"exact-human-isolated-source-crop")
    crop_sha = _sha(crop)

    isolation = {
        "format": ISOLATION_FORMAT,
        "version": 1,
        "policy": ISOLATION_POLICY,
        "bodyrig_revision": revision,
        "performer_id": "42",
        "scene_id": "scene-multi-1",
        "authority_scope": "accepted-samples-only",
        "accepted_samples": [{"sample_id": sample_id, "target_crop_sha256": crop_sha}],
        "target_isolated_source_authority": True,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    isolation_path = candidate_root / "photoidentity-multiperformer-target-isolation-attestation.json"
    isolation_path.write_text(json.dumps(isolation, sort_keys=True) + "\n", encoding="utf-8")

    private = {
        "format": PRIVATE_ENRICHMENT_FORMAT,
        "version": 1,
        "bodyrig_revision": revision,
        "performer_id": "42",
        "scene_id": "scene-multi-1",
        "rows": [{"sample_id": sample_id, "analysis_crop": str(crop.resolve()), "openpose_keypoints": str((sample_root / "accepted-target-crop_keypoints.json").resolve())}],
        "source_paths_private": True,
        "production_activation": False,
    }
    private_path = private_root / "private-analysis-index.json"
    private_path.write_text(json.dumps(private, sort_keys=True) + "\n", encoding="utf-8")

    public = {
        "format": ENRICHMENT_FORMAT,
        "version": 1,
        "bodyrig_revision": revision,
        "performer_id": "42",
        "scene_id": "scene-multi-1",
        "source_media_sha256": "b" * 64,
        "human_target_isolation_attestation_sha256": _sha(isolation_path),
        "accepted_sample_count": 1,
        "supported_domains": ["eyes_detail", "feet", "hair_hairline", "hands", "skin_detail"],
        "domain_candidate_counts": {"eyes_detail": 1, "feet": 0, "hair_hairline": 0, "hands": 0, "skin_detail": 0},
        "domain_best_machine_observability_score": {"eyes_detail": score, "feet": 0.0, "hair_hairline": 0.0, "hands": 0.0, "skin_detail": 0.0},
        "samples": [{
            "sample_id": sample_id,
            "scene_id": "scene-multi-1",
            "target_crop_sha256": crop_sha,
            "native_crop_width": 640,
            "native_crop_height": 960,
            "candidates": [{
                "domain": "eyes_detail",
                "machine_observability_score": score,
                "source_derived": True,
                "adapter": adapter,
                "revision": OPENPOSE_REVISION,
                "source_detail_quality_authority": False,
                "photoidentity_sufficiency_authority": False,
                "metrics": {"pixel_extent": 180.0},
            }],
        }],
        "private_analysis_index_sha256": _sha(private_path),
        "machine_observability_only": True,
        "source_detail_quality_authority": False,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "human_review_render_permitted": False,
        "generic_guessing_permitted": False,
        "production_activation": False,
    }
    public_path = enrichment_root / "target-crop-detail-enrichment.json"
    public_path.write_text(json.dumps(public, sort_keys=True) + "\n", encoding="utf-8")
    return candidate_root, enrichment_root, sample_id, crop


def test_quality_attestation_binds_human_isolation_crop_and_stays_pre_sufficiency(tmp_path: Path) -> None:
    candidate_root, enrichment_root, sample_id, crop = _fixture(tmp_path)
    result = record_target_crop_quality_attestation(
        candidate_root=candidate_root,
        enrichment_root=enrichment_root,
        selected_refs=[f"{sample_id}:eyes_detail"],
        current_revision="a" * 40,
        quality_note="The actual human-isolated source crop has clear, native eye detail and is suitable as source evidence.",
        confirm_quality=True,
    )
    receipt = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))
    assert receipt["human_source_detail_quality_attested"] is True
    assert receipt["source_detail_quality_authority"] is True
    assert receipt["photoidentity_source_evidence_authority"] is False
    assert receipt["reconstruction_permitted"] is False
    assert receipt["production_activation"] is False
    assert receipt["selected_domains"] == ["eyes_detail"]
    assert receipt["selected_claims"][0]["target_crop_sha256"] == _sha(crop)
    assert receipt["selected_claims"][0]["quality"] == pytest.approx(0.91)
    assert str(crop.resolve()) not in Path(result["receipt"]).read_text(encoding="utf-8")


def test_human_only_hair_attestation_uses_explicit_review_not_machine_authority(tmp_path: Path) -> None:
    candidate_root, enrichment_root, sample_id, crop = _fixture(tmp_path)
    result = record_target_crop_quality_attestation(
        candidate_root=candidate_root,
        enrichment_root=enrichment_root,
        selected_refs=[f"{sample_id}:eyebrows_detail:0.92"],
        current_revision="a" * 40,
        quality_note=(
            "The exact isolated source crop clearly exposes the subject's eyebrow state; "
            "this is an explicit human source review, including a valid no-hair state if observed."
        ),
        confirm_quality=True,
    )
    receipt = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))
    claim = receipt["selected_claims"][0]
    assert receipt["selected_domains"] == ["eyebrows_detail"]
    assert claim["target_crop_sha256"] == _sha(crop)
    assert claim["quality"] == pytest.approx(0.92)
    assert claim["quality_basis"] == HUMAN_QUALITY_BASIS
    assert claim["human_visibility_attested"] is True
    assert claim["machine_observability_used"] is False
    assert "machine_adapter" not in claim
    assert "machine_revision" not in claim


def test_human_only_hair_requires_explicit_quality_and_canonical_threshold(tmp_path: Path) -> None:
    candidate_root, enrichment_root, sample_id, _ = _fixture(tmp_path / "missing")
    with pytest.raises(PhotoIdentityTargetCropQualityAttestationError, match="requires explicit reviewed quality"):
        record_target_crop_quality_attestation(
            candidate_root=candidate_root,
            enrichment_root=enrichment_root,
            selected_refs=[f"{sample_id}:facial_hair_detail"],
            current_revision="a" * 40,
            quality_note="The reviewer must provide an explicit source quality for human-only hair evidence.",
            confirm_quality=True,
        )

    candidate_root, enrichment_root, sample_id, _ = _fixture(tmp_path / "low")
    with pytest.raises(PhotoIdentityTargetCropQualityAttestationError, match="below canonical quality threshold"):
        record_target_crop_quality_attestation(
            candidate_root=candidate_root,
            enrichment_root=enrichment_root,
            selected_refs=[f"{sample_id}:body_hair_detail:0.79"],
            current_revision="a" * 40,
            quality_note="The crop is source-derived but does not expose enough body-hair detail for identity authority.",
            confirm_quality=True,
        )


def test_machine_assisted_domain_rejects_human_override_score(tmp_path: Path) -> None:
    candidate_root, enrichment_root, sample_id, _ = _fixture(tmp_path)
    with pytest.raises(PhotoIdentityTargetCropQualityAttestationError, match="must not supply a human override score"):
        record_target_crop_quality_attestation(
            candidate_root=candidate_root,
            enrichment_root=enrichment_root,
            selected_refs=[f"{sample_id}:eyes_detail:0.95"],
            current_revision="a" * 40,
            quality_note="Machine-assisted eye observability must retain exact machine provenance without score override.",
            confirm_quality=True,
        )


def test_quality_attestation_requires_explicit_human_confirmation(tmp_path: Path) -> None:
    candidate_root, enrichment_root, sample_id, _ = _fixture(tmp_path)
    with pytest.raises(PhotoIdentityTargetCropQualityAttestationError, match="explicit human"):
        record_target_crop_quality_attestation(
            candidate_root=candidate_root,
            enrichment_root=enrichment_root,
            selected_refs=[f"{sample_id}:eyes_detail"],
            current_revision="a" * 40,
            quality_note="This is a deliberate source-quality review note with enough detail to be valid.",
            confirm_quality=False,
        )


def test_quality_attestation_rejects_subthreshold_machine_observability(tmp_path: Path) -> None:
    candidate_root, enrichment_root, sample_id, _ = _fixture(tmp_path, score=DETAIL_QUALITY_THRESHOLD - 0.01)
    with pytest.raises(PhotoIdentityTargetCropQualityAttestationError, match="below canonical quality threshold"):
        record_target_crop_quality_attestation(
            candidate_root=candidate_root,
            enrichment_root=enrichment_root,
            selected_refs=[f"{sample_id}:eyes_detail"],
            current_revision="a" * 40,
            quality_note="The source crop was reviewed, but machine observability must still satisfy the canonical threshold.",
            confirm_quality=True,
        )


def test_quality_attestation_rejects_wrong_machine_adapter_and_crop_tamper(tmp_path: Path) -> None:
    candidate_root, enrichment_root, sample_id, _ = _fixture(tmp_path / "adapter", adapter="generic-eye-prior")
    with pytest.raises(PhotoIdentityTargetCropQualityAttestationError, match="invalid source authority"):
        record_target_crop_quality_attestation(
            candidate_root=candidate_root,
            enrichment_root=enrichment_root,
            selected_refs=[f"{sample_id}:eyes_detail"],
            current_revision="a" * 40,
            quality_note="This deliberate note cannot make an unregistered machine adapter authoritative.",
            confirm_quality=True,
        )

    candidate_root, enrichment_root, sample_id, crop = _fixture(tmp_path / "tamper")
    crop.write_bytes(crop.read_bytes() + b"tamper")
    with pytest.raises(PhotoIdentityTargetCropQualityAttestationError, match="bytes changed"):
        record_target_crop_quality_attestation(
            candidate_root=candidate_root,
            enrichment_root=enrichment_root,
            selected_refs=[f"{sample_id}:eyes_detail"],
            current_revision="a" * 40,
            quality_note="This deliberate note cannot authorize target-crop bytes that changed after enrichment.",
            confirm_quality=True,
        )


def test_quality_attestation_is_create_only(tmp_path: Path) -> None:
    candidate_root, enrichment_root, sample_id, _ = _fixture(tmp_path)
    kwargs = dict(
        candidate_root=candidate_root,
        enrichment_root=enrichment_root,
        selected_refs=[f"{sample_id}:eyes_detail"],
        current_revision="a" * 40,
        quality_note="The exact source crop has sufficient eye detail and the receipt must remain create-only.",
        confirm_quality=True,
    )
    record_target_crop_quality_attestation(**kwargs)
    with pytest.raises(PhotoIdentityTargetCropQualityAttestationError, match="already exists"):
        record_target_crop_quality_attestation(**kwargs)

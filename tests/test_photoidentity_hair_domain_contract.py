from __future__ import annotations

import pytest

from bodyrig.photoidentity_authority import (
    PhotoIdentityAuthorityError,
    validate_authoritative_observation_evidence,
)
from bodyrig.photoidentity_evidence import build_observation_evidence, evaluate_sufficiency

REVISION = "a" * 40
BASELINE_SHA = "b" * 64


def _row(scene: str = "scene-1") -> dict[str, object]:
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


def _claim(scene: str, adapter: str) -> dict[str, object]:
    return {
        "scene_id": scene,
        "quality": 0.92,
        "source_derived": True,
        "adapter": adapter,
        "revision": "1",
    }


def test_schp_hair_capability_does_not_cover_eyebrows_facial_or_body_hair() -> None:
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
        rows=[_row()],
        detail_evidence={
            "hair_hairline": [
                {
                    "scene_id": "scene-1",
                    "quality": 0.92,
                    "source_derived": True,
                    "adapter": "schp-atr18-source-observability",
                    "revision": "1",
                }
            ]
        },
    )
    report = evaluate_sufficiency(evidence)
    assert report["domains"]["hair_hairline"]["required_capability"] == "hair-detail"
    assert report["domains"]["eyebrows_detail"]["status"] == "analyzer_cannot_prove"
    assert report["domains"]["facial_hair_detail"]["status"] == "analyzer_cannot_prove"
    assert report["domains"]["body_hair_detail"]["status"] == "analyzer_cannot_prove"


def test_new_hair_domains_require_exact_human_target_detail_authority() -> None:
    capabilities = [
        "coarse-face-view",
        "coarse-full-body-view",
        "eyes-detail",
        "hands-detail",
        "feet-detail",
        "hair-detail",
        "skin-detail",
        "eyebrows-detail",
        "facial-hair-detail",
        "body-hair-detail",
    ]
    evidence = build_observation_evidence(
        performer_id="42",
        bodyrig_revision=REVISION,
        baseline_source_manifest_sha256=BASELINE_SHA,
        analyzer_adapter="bodyrig-photoidentity-coarse-openpose-schp-human-target-detail-composite",
        analyzer_revision="1",
        analyzer_capabilities=capabilities,
        candidate_scenes=1,
        source_files_scanned=1,
        scan_exhausted=True,
        rows=[_row()],
        detail_evidence={
            "eyebrows_detail": [_claim("multi-1", "schp-atr18-source-observability")],
        },
    )
    with pytest.raises(PhotoIdentityAuthorityError, match="eyebrows_detail requires human-reviewed-target-crop-detail-quality@1"):
        validate_authoritative_observation_evidence(evidence)

    valid = build_observation_evidence(
        performer_id="42",
        bodyrig_revision=REVISION,
        baseline_source_manifest_sha256=BASELINE_SHA,
        analyzer_adapter="bodyrig-photoidentity-coarse-openpose-schp-human-target-detail-composite",
        analyzer_revision="1",
        analyzer_capabilities=capabilities,
        candidate_scenes=1,
        source_files_scanned=1,
        scan_exhausted=True,
        rows=[_row()],
        detail_evidence={
            "eyebrows_detail": [_claim("multi-1", "human-reviewed-target-crop-detail-quality")],
            "facial_hair_detail": [_claim("multi-1", "human-reviewed-target-crop-detail-quality")],
            "body_hair_detail": [_claim("multi-1", "human-reviewed-target-crop-detail-quality")],
        },
    )
    validate_authoritative_observation_evidence(valid)

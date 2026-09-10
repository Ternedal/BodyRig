from __future__ import annotations

from bodyrig.photoidentity_evidence import DOMAIN_REQUIREMENTS, build_observation_evidence, evaluate_sufficiency


def _row() -> dict[str, object]:
    return {
        "scene_id": "scene1",
        "source_ordinal": 1,
        "start_seconds": 2.0,
        "duration_seconds": 6.0,
        "target_confidence": 0.95,
        "target_screen_fraction": 0.5,
        "face_visibility": 0.95,
        "full_body_visibility": 0.95,
        "sharpness": 0.95,
        "occlusion": 0.0,
        "motion": 0.1,
        "view": "front",
    }


def test_fingernails_and_toenails_are_explicit_photoidentity_domains() -> None:
    assert DOMAIN_REQUIREMENTS["fingernails_detail"] == {
        "capability": "fingernails-detail",
        "minimum_distinct_scenes": 2,
    }
    assert DOMAIN_REQUIREMENTS["toenails_detail"] == {
        "capability": "toenails-detail",
        "minimum_distinct_scenes": 2,
    }


def test_missing_nail_capabilities_block_reconstruction_and_render() -> None:
    capabilities = sorted(
        {
            str(requirement["capability"])
            for domain, requirement in DOMAIN_REQUIREMENTS.items()
            if domain not in {"fingernails_detail", "toenails_detail"}
        }
    )
    evidence = build_observation_evidence(
        performer_id="42",
        bodyrig_revision="a" * 40,
        baseline_source_manifest_sha256="b" * 64,
        analyzer_adapter="detail-test",
        analyzer_revision="1",
        analyzer_capabilities=capabilities,
        candidate_scenes=20,
        source_files_scanned=10,
        scan_exhausted=True,
        rows=[_row()],
        detail_evidence={},
    )
    report = evaluate_sufficiency(evidence)

    assert report["domains"]["fingernails_detail"]["status"] == "analyzer_cannot_prove"
    assert report["domains"]["toenails_detail"]["status"] == "analyzer_cannot_prove"
    assert "fingernails_detail" in report["analyzer_blockers"]
    assert "toenails_detail" in report["analyzer_blockers"]
    assert report["source_evidence_sufficient"] is False
    assert report["reconstruction_permitted"] is False
    assert report["human_review_render_permitted"] is False
    assert report["generic_guessing_permitted"] is False

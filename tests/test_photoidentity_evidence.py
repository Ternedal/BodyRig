from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoidentity_evidence import (
    DOMAIN_REQUIREMENTS,
    PhotoIdentityEvidenceError,
    build_observation_evidence,
    evaluate_sufficiency,
    validate_bundle,
    write_bundle,
)


def _row(scene: str, view: str, *, face: float = 0.9, body: float = 0.9) -> dict[str, object]:
    return {
        "scene_id": scene,
        "source_ordinal": int(scene.removeprefix("scene")) if scene.removeprefix("scene").isdigit() else 1,
        "start_seconds": 2.0,
        "duration_seconds": 6.0,
        "target_confidence": 0.92,
        "target_screen_fraction": 0.4,
        "face_visibility": face,
        "full_body_visibility": body,
        "sharpness": 0.9,
        "occlusion": 0.05,
        "motion": 0.2,
        "view": view,
    }


def _evidence(*, capabilities: list[str], rows: list[dict[str, object]], details=None, exhausted=True):
    return build_observation_evidence(
        performer_id="42",
        bodyrig_revision="a" * 40,
        baseline_source_manifest_sha256="b" * 64,
        analyzer_adapter="test-adapter",
        analyzer_revision="1",
        analyzer_capabilities=capabilities,
        candidate_scenes=50,
        source_files_scanned=20,
        scan_exhausted=exhausted,
        rows=rows,
        detail_evidence=details or {},
    )


def test_current_coarse_capability_can_never_authorize_photoidentity_render() -> None:
    rows = [
        _row("scene1", "front"),
        _row("scene2", "front"),
        _row("scene3", "left_profile"),
        _row("scene4", "right_profile"),
    ]
    report = evaluate_sufficiency(
        _evidence(capabilities=["coarse-face-view", "coarse-full-body-view"], rows=rows)
    )

    assert report["source_evidence_sufficient"] is False
    assert report["reconstruction_permitted"] is False
    assert report["human_review_render_permitted"] is False
    assert report["generic_guessing_permitted"] is False
    assert report["production_activation"] is False
    assert report["next_action"] == "upgrade_identity_analyzer"
    assert "eyes_detail" in report["analyzer_blockers"]
    assert "hair_hairline" in report["analyzer_blockers"]
    assert "torso_chest" in report["analyzer_blockers"]
    assert "body_rear" in report["analyzer_blockers"]


def test_missing_source_and_missing_analyzer_capability_are_distinct_states() -> None:
    report = evaluate_sufficiency(
        _evidence(
            capabilities=["coarse-face-view", "coarse-full-body-view"],
            rows=[_row("scene1", "front")],
            exhausted=False,
        )
    )

    assert report["domains"]["face_front"]["status"] == "source_missing"
    assert report["domains"]["face_left_profile"]["status"] == "source_missing"
    assert report["domains"]["eyes_detail"]["status"] == "analyzer_cannot_prove"
    assert "face_front" in report["source_blockers"]
    assert "eyes_detail" in report["analyzer_blockers"]


def test_complete_source_derived_detail_evidence_can_pass_without_generic_guessing() -> None:
    capabilities = sorted({str(item["capability"]) for item in DOMAIN_REQUIREMENTS.values()})
    rows = [
        _row("scene1", "front"),
        _row("scene2", "front"),
        _row("scene3", "left_profile"),
        _row("scene4", "right_profile"),
    ]
    details: dict[str, list[dict[str, object]]] = {}
    for domain, requirement in DOMAIN_REQUIREMENTS.items():
        capability = str(requirement["capability"])
        if capability in {"coarse-face-view", "coarse-full-body-view"}:
            continue
        minimum = int(requirement["minimum_distinct_scenes"])
        details[domain] = [
            {
                "scene_id": f"detail-{domain}-{index}",
                "quality": 0.95,
                "source_derived": True,
                "adapter": "detail-test",
                "revision": "1",
            }
            for index in range(minimum)
        ]

    report = evaluate_sufficiency(_evidence(capabilities=capabilities, rows=rows, details=details))

    assert report["analyzer_blockers"] == []
    assert report["source_blockers"] == []
    assert report["source_evidence_sufficient"] is True
    assert report["reconstruction_permitted"] is True
    assert report["human_review_render_permitted"] is True
    assert report["generic_guessing_permitted"] is False
    assert report["next_action"] == "source_evidence_ready_for_reconstruction"
    assert report["production_activation"] is False


def test_scan_exhaustion_changes_missing_source_recovery_action_when_analyzer_is_capable() -> None:
    capabilities = sorted({str(item["capability"]) for item in DOMAIN_REQUIREMENTS.values()})
    report = evaluate_sufficiency(
        _evidence(capabilities=capabilities, rows=[_row("scene1", "front")], exhausted=False)
    )
    assert report["analyzer_blockers"] == []
    assert report["source_blockers"]
    assert report["next_action"] == "scan_additional_stash_sources"

    exhausted = evaluate_sufficiency(
        _evidence(capabilities=capabilities, rows=[_row("scene1", "front")], exhausted=True)
    )
    assert exhausted["next_action"] == "acquire_more_source_media"


def test_bundle_recomputes_report_and_fails_closed_on_tamper(tmp_path: Path) -> None:
    evidence = _evidence(
        capabilities=["coarse-face-view", "coarse-full-body-view"],
        rows=[_row("scene1", "front"), _row("scene2", "front")],
    )
    observations, report_path, report = write_bundle(tmp_path / "bundle", evidence)
    assert validate_bundle(report_path, observations) == report

    tampered = json.loads(report_path.read_text(encoding="utf-8"))
    tampered["human_review_render_permitted"] = True
    report_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(PhotoIdentityEvidenceError, match="inconsistent"):
        validate_bundle(report_path, observations)


def test_detail_claim_must_be_source_derived() -> None:
    details = {
        "eyes_detail": [
            {
                "scene_id": "scene-eyes",
                "quality": 0.99,
                "source_derived": False,
                "adapter": "bad",
                "revision": "1",
            }
        ]
    }
    with pytest.raises(PhotoIdentityEvidenceError, match="not source-derived"):
        _evidence(capabilities=["eyes-detail"], rows=[_row("scene1", "front")], details=details)

def test_huge_row_timing_integer_fails_with_domain_error() -> None:
    row = _row("scene1", "front")
    row["start_seconds"] = 10**400

    with pytest.raises(PhotoIdentityEvidenceError, match="photoidentity observation start is invalid"):
        _evidence(capabilities=["coarse-face-view"], rows=[row])


def test_huge_quality_integer_fails_with_domain_error() -> None:
    row = _row("scene1", "front")
    row["target_confidence"] = 10**400

    with pytest.raises(PhotoIdentityEvidenceError, match=r"target_confidence is outside 0\.0\.\.1\.0"):
        _evidence(capabilities=["coarse-face-view"], rows=[row])


def test_bundle_huge_bound_numeric_fails_after_sha_binding(tmp_path: Path) -> None:
    evidence = _evidence(
        capabilities=["coarse-face-view", "coarse-full-body-view"],
        rows=[_row("scene1", "front"), _row("scene2", "front")],
    )
    observations, report_path, _ = write_bundle(tmp_path / "bundle-overflow", evidence)

    raw = json.loads(observations.read_text(encoding="utf-8"))
    raw["rows"][0]["target_confidence"] = 10**400
    observation_bytes = (json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    observations.write_bytes(observation_bytes)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["observation_evidence_sha256"] = hashlib.sha256(observation_bytes).hexdigest()
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PhotoIdentityEvidenceError, match=r"target_confidence is outside 0\.0\.\.1\.0"):
        validate_bundle(report_path, observations)

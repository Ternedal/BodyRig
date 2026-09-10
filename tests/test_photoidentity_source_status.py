from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.photoidentity_source_status as status_module
from bodyrig.photoidentity_authority import DETAIL_DOMAIN_AUTHORITY
from bodyrig.photoidentity_evidence import DOMAIN_REQUIREMENTS, build_observation_evidence, write_bundle
from bodyrig.photoidentity_source_status import PhotoIdentitySourceStatusError, inspect_source_status


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
    return {domain: [_claim(domain, f"{domain}-a"), _claim(domain, f"{domain}-b")] for domain in domains}


def _write_stage(root: Path, stage: str) -> tuple[Path, Path, dict]:
    details = _base_details()
    if stage in {"nail", "final"}:
        details["fingernails_detail"] = [
            _claim("fingernails_detail", "finger-a"),
            _claim("fingernails_detail", "finger-b"),
        ]
        details["toenails_detail"] = [
            _claim("toenails_detail", "toe-a"),
            _claim("toenails_detail", "toe-b"),
        ]
    if stage == "final":
        details["body_rear"] = [_claim("body_rear", "rear-a")]
        details["torso_chest"] = [_claim("torso_chest", "torso-a"), _claim("torso_chest", "torso-b")]
        details["waist_hips"] = [_claim("waist_hips", "waist-a"), _claim("waist_hips", "waist-b")]

    if stage == "base":
        adapter = "bodyrig-photoidentity-coarse-openpose-schp-composite"
        capabilities = {
            "coarse-face-view",
            "coarse-full-body-view",
            "eyes-detail",
            "hands-detail",
            "feet-detail",
            "hair-detail",
            "skin-detail",
        }
        output = root / "human-parsing-evidence"
    elif stage == "nail":
        adapter = "bodyrig-photoidentity-coarse-openpose-schp-human-nails-composite"
        capabilities = {
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
        output = root / "nail-attested-evidence"
    else:
        adapter = "bodyrig-photoidentity-source-human-anatomy-composite"
        capabilities = {str(item["capability"]) for item in DOMAIN_REQUIREMENTS.values()}
        output = root / "anatomy-attested-evidence"

    evidence = build_observation_evidence(
        performer_id="42",
        bodyrig_revision="a" * 40,
        baseline_source_manifest_sha256="b" * 64,
        analyzer_adapter=adapter,
        analyzer_revision="1",
        analyzer_capabilities=sorted(capabilities),
        candidate_scenes=20,
        source_files_scanned=20,
        scan_exhausted=True,
        rows=_rows(),
        detail_evidence=details,
    )
    return write_bundle(output, evidence)


def _base_root(tmp_path: Path) -> Path:
    root = tmp_path / "sweep"
    root.mkdir()
    _write_stage(root, "base")
    return root


def _add_nail_state(root: Path) -> dict:
    (root / "nail-source-candidates.json").write_text("{}", encoding="utf-8")
    private = root / "private-nail-source-candidates"
    private.mkdir()
    (private / "private-candidate-index.json").write_text("{}", encoding="utf-8")
    _, _, report = _write_stage(root, "nail")
    (root / "photoidentity-nail-source-attestation.json").write_text(
        json.dumps({"attested_domains": ["fingernails_detail", "toenails_detail"]}),
        encoding="utf-8",
    )
    return report


def test_base_evidence_routes_to_nail_discovery(tmp_path: Path) -> None:
    root = _base_root(tmp_path)
    result = inspect_source_status(root)
    assert result["stage"] == "nail-discovery"
    assert result["avatar_render_permitted"] is False
    assert result["generic_guessing_permitted"] is False


def test_nail_discovery_routes_to_review_then_human_review(tmp_path: Path) -> None:
    root = _base_root(tmp_path)
    (root / "nail-source-candidates.json").write_text("{}", encoding="utf-8")
    private = root / "private-nail-source-candidates"
    private.mkdir()
    (private / "private-candidate-index.json").write_text("{}", encoding="utf-8")
    assert inspect_source_status(root)["stage"] == "nail-review-prepare"

    review = root / "private-nail-source-review"
    review.mkdir()
    (review / "review-index.json").write_text("{}", encoding="utf-8")
    result = inspect_source_status(root)
    assert result["stage"] == "nail-human-review"
    assert result["human_review_required"] is True
    assert result["avatar_render_permitted"] is False


def test_partial_create_only_nail_receipt_is_rejected(tmp_path: Path) -> None:
    root = _base_root(tmp_path)
    (root / "nail-source-candidates.json").write_text("{}", encoding="utf-8")
    private = root / "private-nail-source-candidates"
    private.mkdir()
    (private / "private-candidate-index.json").write_text("{}", encoding="utf-8")
    _write_stage(root, "nail")
    (root / "photoidentity-nail-source-attestation.json").write_text(
        json.dumps({"attested_domains": ["fingernails_detail"]}),
        encoding="utf-8",
    )
    with pytest.raises(PhotoIdentitySourceStatusError, match="partial create-only nail attestation"):
        inspect_source_status(root)


def test_complete_nail_state_routes_through_anatomy_review(tmp_path: Path) -> None:
    root = _base_root(tmp_path)
    _add_nail_state(root)
    assert inspect_source_status(root)["stage"] == "anatomy-discovery"

    (root / "anatomy-source-candidates.json").write_text("{}", encoding="utf-8")
    private = root / "private-anatomy-source-candidates"
    private.mkdir()
    (private / "private-candidate-index.json").write_text("{}", encoding="utf-8")
    assert inspect_source_status(root)["stage"] == "anatomy-review-prepare"

    review = root / "private-anatomy-source-review"
    review.mkdir()
    (review / "review-index.json").write_text("{}", encoding="utf-8")
    result = inspect_source_status(root)
    assert result["stage"] == "anatomy-human-review"
    assert result["human_review_required"] is True


def test_final_chain_routes_to_registration_and_only_registered_state_allows_render(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _base_root(tmp_path)
    _add_nail_state(root)
    (root / "anatomy-source-candidates.json").write_text("{}", encoding="utf-8")
    private = root / "private-anatomy-source-candidates"
    private.mkdir()
    (private / "private-candidate-index.json").write_text("{}", encoding="utf-8")
    final_observations, final_report_path, final_report = _write_stage(root, "final")
    (root / "photoidentity-anatomy-source-attestation.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        status_module,
        "validate_registration_source_chain",
        lambda *args, **kwargs: {"report": final_report},
    )
    result = inspect_source_status(root)
    assert result["stage"] == "ready-for-registration"
    assert result["source_evidence_sufficient"] is True
    assert result["avatar_render_permitted"] is False

    job_root = tmp_path / "job"
    registry_root = job_root / "photoidentity-evidence"
    registry_root.mkdir(parents=True)
    monkeypatch.setattr(
        status_module,
        "_job_authority",
        lambda body_job_id: ({"person_id": "person-fixture"}, "42", "a" * 40, job_root, "b" * 64),
    )
    monkeypatch.setattr(
        status_module,
        "require_body_job_photoidentity_evidence",
        lambda person_id, body_job_id: {"source_evidence_sufficient": True},
    )
    registered = inspect_source_status(root, body_job_id="job-" + "1" * 32)
    assert registered["stage"] == "registered"
    assert registered["avatar_render_permitted"] is True
    assert registered["production_activation"] is False

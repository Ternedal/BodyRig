from __future__ import annotations

from pathlib import Path

from bodyrig.app import app


ROOT = Path(__file__).resolve().parents[1]


def test_continuation_status_route_is_strictly_read_only() -> None:
    paths = app.openapi()["paths"]
    route = paths["/api/v1/high-fidelity-preview-jobs/{job_id}/continuation-status"]

    assert "get" in route
    assert "post" not in route
    assert "put" not in route
    assert "patch" not in route
    assert "delete" not in route


def test_person_studio_loads_unified_continuation_as_isolated_extension() -> None:
    gallery = (ROOT / "bodyrig" / "ui" / "body_review_gallery.js").read_text(encoding="utf-8")
    ui = (ROOT / "bodyrig" / "ui" / "high_fidelity_continuation.js").read_text(encoding="utf-8")

    assert 'import("/ui/high_fidelity_continuation.js")' in gallery
    assert "/continuation-status" in ui
    assert "HIGH-FIDELITY PACKAGE COMPLETE · HUMAN REVIEW REQUIRED · PRODUCTION LOCKED" in ui
    assert "SOFTWARE READY FOR PHYSICAL ACCEPTANCE · PRODUCTION LOCKED" in ui
    assert "production_ready=false" in ui
    assert "Windows acceptance" in ui
    assert "Quest acceptance" in ui
    assert "final release" in ui
    assert "operator_input_required" in ui


def test_continuation_adapter_revalidates_hair_package_instead_of_using_anatomy_candidate() -> None:
    source = (ROOT / "bodyrig" / "high_fidelity_continuation_status.py").read_text(encoding="utf-8")

    assert "read_promotion as read_hair_promotion" in source
    assert "promoted_package_sha256" in source
    assert 'context["hair_package"]' in source
    assert "target_package_path=hair_package" in source
    assert "hair promotion status does not bind its exact promoted package bytes" in source


def test_face_secondary_preview_paths_match_atomic_operator_layout() -> None:
    source = (ROOT / "bodyrig" / "high_fidelity_continuation_status.py").read_text(encoding="utf-8")

    assert '"face_preview_root": face_preview' in source
    assert '"face_preparation": face_preview / "preparation"' in source
    assert '"face_render": face_preview / "render"' in source
    assert "-OutputDir {_quote(paths['face_preview_root'])}" in source


def test_eye_only_rebuild_command_contains_every_canonical_authority_input() -> None:
    source = (ROOT / "bodyrig" / "high_fidelity_continuation_status.py").read_text(encoding="utf-8")

    for token in (
        "-PackagePath",
        "-BaseRuntimeDir",
        "-IrisCandidateDir",
        "-EyeGeometryDir",
        "-EyeAppearanceDir",
        "-ReviewedRuntimeDir",
        "-CandidateWorkspace",
        "-OutputDir",
    ):
        assert token in source


def test_component_status_never_claims_production_authority() -> None:
    source = (ROOT / "bodyrig" / "high_fidelity_continuation_status.py").read_text(encoding="utf-8")

    assert '"production_ready": False' in source
    assert '"production_activation": False' in source
    assert '"physical_windows_acceptance_required": True' in source
    assert '"quest_acceptance_required": True' in source
    assert '"final_release_required": True' in source


def test_release_readiness_adds_package_bound_human_review_without_production_activation() -> None:
    source = (ROOT / "bodyrig" / "high_fidelity_release_readiness.py").read_text(encoding="utf-8")

    assert 'FINAL_REVIEW_GATE = "high_fidelity_human_review"' in source
    assert "record-high-fidelity-human-review.ps1" in source
    assert "-PackagePath" in source
    assert '"component_package_complete"' in source
    assert '"high_fidelity_human_review_complete"' in source
    assert '"software_ready_for_physical_acceptance"' in source
    assert '"production_ready"] = False' in source
    assert '"production_activation"] = False' in source

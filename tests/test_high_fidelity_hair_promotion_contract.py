from __future__ import annotations

from pathlib import Path

from bodyrig.app import app

ROOT = Path(__file__).resolve().parents[1]


def test_hair_promotion_status_route_is_read_only() -> None:
    paths = app.openapi()["paths"]
    route = paths["/api/v1/high-fidelity-preview-jobs/{job_id}/hair-promotion"]

    assert "get" in route
    assert "post" not in route
    assert "put" not in route
    assert "patch" not in route
    assert "delete" not in route


def test_person_studio_surfaces_exact_hair_promotion_command_and_eye_boundary() -> None:
    gallery = (ROOT / "bodyrig" / "ui" / "body_review_gallery.js").read_text(encoding="utf-8")
    ui = (ROOT / "bodyrig" / "ui" / "high_fidelity_hair_promotion.js").read_text(encoding="utf-8")

    assert 'import("/ui/high_fidelity_hair_promotion.js")' in gallery
    assert "promote-high-fidelity-hair.ps1" in ui
    assert "-PreviewJobId" in ui
    assert "hair-only runtime" in ui
    assert "combined hair+eye VRM" in ui
    assert "kopieres aldrig" in ui
    assert "Eye review runtime er ikke importeret" in ui
    assert "production_activation=false" in ui


def test_hair_promotion_wrapper_rebuilds_hair_only_and_checks_exact_hash() -> None:
    wrapper = (ROOT / "promote-high-fidelity-hair.ps1").read_text(encoding="utf-8")

    assert "Assert-CheckoutAuthority" in wrapper
    assert "git -C $RepoRoot rev-parse HEAD" in wrapper
    assert "git -C $RepoRoot status --porcelain" in wrapper
    assert "build-source-hair-review-runtime.ps1" in wrapper
    assert "bodyrig.high_fidelity_hair_promotion_cli prepare" in wrapper
    assert "bodyrig.high_fidelity_hair_promotion_cli promote" in wrapper
    assert "--promotion-bodyrig-revision $initialHead" in wrapper
    assert "expected_hair_review_bridge_sha256" in wrapper
    assert "rebuilt_hair_bridge_canonical_sha256" in wrapper
    assert "does not match the exact physically reviewed hair stage" in wrapper
    assert "components_after.body_anatomy" in wrapper
    assert "components_after.hair" in wrapper
    assert "eyes_imported -ne $false" in wrapper
    assert "production_activation -ne $false" in wrapper
    assert "Remove-Item -LiteralPath $promotionRoot -Recurse -Force" in wrapper


def test_hair_promotion_source_rejects_combined_eye_authority_and_keeps_two_revisions() -> None:
    source = (ROOT / "bodyrig" / "high_fidelity_hair_promotion.py").read_text(encoding="utf-8")

    assert "hairReviewBridgeSha256" in source
    assert "_canonical_json_sha256" in source
    assert '"eyeReviewRuntime"' in source
    assert "BodyRigSourceEyeReview" in source
    assert "BodyRigCorneaReview" in source
    assert "source_bodyrig_revision" in source
    assert "promotion_bodyrig_revision" in source
    assert '"eyesImported": False' in source
    assert '"productionActivation": False' in source
    assert "body_anatomy" in source
    assert 'component="hair", status="complete"' in source

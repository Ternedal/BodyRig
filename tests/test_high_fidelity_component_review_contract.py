from __future__ import annotations

from pathlib import Path

from bodyrig.app import app

ROOT = Path(__file__).resolve().parents[1]


def test_component_review_status_route_is_read_only() -> None:
    paths = app.openapi()["paths"]
    route = paths["/api/v1/high-fidelity-preview-jobs/{job_id}/component-review"]

    assert "get" in route
    assert "post" not in route
    assert "put" not in route
    assert "patch" not in route
    assert "delete" not in route


def test_person_studio_surfaces_checkout_bound_component_review_command() -> None:
    gallery = (ROOT / "bodyrig" / "ui" / "body_review_gallery.js").read_text(encoding="utf-8")
    ui = (ROOT / "bodyrig" / "ui" / "high_fidelity_component_review.js").read_text(encoding="utf-8")

    assert 'import("/ui/high_fidelity_component_review.js")' in gallery
    assert "record-high-fidelity-component-review.ps1" in ui
    assert "-PreviewJobId" in ui
    assert "-ConfirmVisualChecklist" in ui
    assert "body_anatomy er nu promotion-eligible" in ui
    assert "runtime deformation review" in ui
    assert "iris authority" in ui
    assert "production_activation=false" in ui


def test_component_review_wrapper_preserves_exact_checkout_and_non_activation_boundary() -> None:
    wrapper = (ROOT / "record-high-fidelity-component-review.ps1").read_text(encoding="utf-8")

    assert "Assert-CheckoutAuthority" in wrapper
    assert "git -C $RepoRoot rev-parse HEAD" in wrapper
    assert "git -C $RepoRoot status --porcelain" in wrapper
    assert "--bodyrig-revision $initialHead" in wrapper
    assert "promotion_eligibility.body_anatomy -ne $true" in wrapper
    assert "promotion_eligibility.hair -ne $false" in wrapper
    assert "promotion_eligibility.eyes -ne $false" in wrapper
    assert "production_activation -ne $false" in wrapper
    assert "Remove-Item -LiteralPath $reviewPath -Force" in wrapper

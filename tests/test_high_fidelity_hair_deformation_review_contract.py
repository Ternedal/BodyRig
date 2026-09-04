from __future__ import annotations

from pathlib import Path

from bodyrig.app import app

ROOT = Path(__file__).resolve().parents[1]


def test_hair_deformation_review_status_route_is_read_only() -> None:
    paths = app.openapi()["paths"]
    route = paths["/api/v1/high-fidelity-preview-jobs/{job_id}/hair-deformation-review"]

    assert "get" in route
    assert "post" not in route
    assert "put" not in route
    assert "patch" not in route
    assert "delete" not in route


def test_person_studio_surfaces_checkout_bound_hair_review_command() -> None:
    gallery = (ROOT / "bodyrig" / "ui" / "body_review_gallery.js").read_text(encoding="utf-8")
    ui = (ROOT / "bodyrig" / "ui" / "high_fidelity_hair_deformation_review.js").read_text(encoding="utf-8")

    assert 'import("/ui/high_fidelity_hair_deformation_review.js")' in gallery
    assert "record-high-fidelity-hair-deformation-review.ps1" in ui
    assert "-PreviewJobId" in ui
    assert "-ConfirmHairDeformationChecklist" in ui
    assert "head-turn" in ui
    assert "attachment" in ui
    assert "clipping" in ui
    assert "restoration" in ui
    assert "Hair promotion-eligible" in ui
    assert "endnu ikke promoted" in ui
    assert "iris authority" in ui
    assert "production_activation=false" in ui


def test_hair_review_wrapper_preserves_exact_checkout_and_non_activation_boundary() -> None:
    wrapper = (ROOT / "record-high-fidelity-hair-deformation-review.ps1").read_text(encoding="utf-8")

    assert "Assert-CheckoutAuthority" in wrapper
    assert "git -C $RepoRoot rev-parse HEAD" in wrapper
    assert "git -C $RepoRoot status --porcelain" in wrapper
    assert "--bodyrig-revision $initialHead" in wrapper
    assert "--confirm-hair-deformation-checklist" in wrapper
    assert "hair_promotion_eligible -ne $true" in wrapper
    assert "human_review_complete -ne $true" in wrapper
    assert "production_activation -ne $false" in wrapper
    assert "Remove-Item -LiteralPath $reviewPath -Force" in wrapper
    assert "no candidate package is mutated" in wrapper

from __future__ import annotations

from pathlib import Path

from bodyrig.app import app

ROOT = Path(__file__).resolve().parents[1]


def test_anatomy_promotion_status_route_is_read_only() -> None:
    paths = app.openapi()["paths"]
    route = paths["/api/v1/high-fidelity-preview-jobs/{job_id}/anatomy-promotion"]

    assert "get" in route
    assert "post" not in route
    assert "put" not in route
    assert "patch" not in route
    assert "delete" not in route


def test_person_studio_surfaces_checkout_bound_anatomy_promotion_command_only_after_review() -> None:
    ui = (ROOT / "bodyrig" / "ui" / "high_fidelity_component_review.js").read_text(encoding="utf-8")

    assert "promote-high-fidelity-anatomy.ps1" in ui
    assert "anatomy-promotion" in ui
    assert 'promotion?.state === "required"' in ui
    assert "body_anatomy=complete" in ui
    assert "Baseline-pakken er urørt" in ui
    assert "runtime deformation authority" in ui
    assert "iris authority" in ui
    assert "production_activation=false" in ui


def test_anatomy_promotion_wrapper_preserves_exact_checkout_and_cleans_new_outputs_on_authority_drift() -> None:
    wrapper = (ROOT / "promote-high-fidelity-anatomy.ps1").read_text(encoding="utf-8")

    assert "Assert-CheckoutAuthority" in wrapper
    assert "git -C $RepoRoot rev-parse HEAD" in wrapper
    assert "git -C $RepoRoot status --porcelain" in wrapper
    assert "--bodyrig-revision $initialHead" in wrapper
    assert 'promotion_component -ne "body_anatomy"' in wrapper
    assert 'components_after.body_anatomy -ne "complete"' in wrapper
    assert "production_activation -ne $false" in wrapper
    assert "Remove-Item -LiteralPath $receiptPath -Force" in wrapper
    assert "Remove-Item -LiteralPath $packagePath -Force" in wrapper

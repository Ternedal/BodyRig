from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_promotion_derives_face_secondary_from_nested_receipt_only() -> None:
    source = (REPO / "bodyrig" / "high_fidelity_face_secondary_promotion.py").read_text(encoding="utf-8")
    assert "with_face_secondary_receipt" in source
    assert 'with_component_status(before, component="face_secondary", status="complete")' not in source
    assert 'semantic_vertex_map_authority="licensed-smplx-verified"' in source
    assert '"sourceDerivedDentalIdentity": False' in source
    assert '"genericSecondaryAnatomy": True' in source
    assert '"productionActivation": False' in source
    assert 'del promoted_bodyrig["faceSecondaryReviewRuntime"]' in source


def test_operator_is_checkout_bound_and_post_write_verified() -> None:
    source = (REPO / "promote-high-fidelity-face-secondary.ps1").read_text(encoding="utf-8")
    assert "status --porcelain" in source
    assert '"promote"' in source
    assert '"verify"' in source
    assert "Remove-Item -LiteralPath $OutputDir -Recurse -Force" in source
    assert "Production: FALSE" in source

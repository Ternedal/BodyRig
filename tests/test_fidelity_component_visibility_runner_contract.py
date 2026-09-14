from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigRendererProbe.cs"
EVALUATOR = ROOT / "bodyrig" / "fidelity_evaluator_cli.py"
CONVERGENCE = ROOT / "run-profiled-fidelity-convergence.ps1"
REANALYSIS = ROOT / "run-fidelity-v5-reanalysis.ps1"


def test_renderer_records_absent_as_well_as_visible_components() -> None:
    source = RENDERER.read_text(encoding="utf-8")
    for marker in (
        '"component-visibility-probe.json"',
        'present_in_avatar_bytes',
        'visible_skinned_renderer',
        'all_required_present_and_visible',
        'new ExpectedRenderPayload("hair", "BodyRigSourceHairReview")',
        'new ExpectedRenderPayload("eyes", "BodyRigSourceEyeReview")',
        'new ExpectedRenderPayload("face-secondary", "BodyRigFaceSecondaryReview")',
        'new ExpectedRenderPayload("fingernails", "BodyRigFingernailPlates")',
        'new ExpectedRenderPayload("toenails", "BodyRigToenailPlates")',
    ):
        assert marker in source
    assert 'if (!present)' in source
    assert 'entries.Add(entry);' in source


def test_fresh_evaluator_is_strict_but_historical_reanalysis_has_explicit_override() -> None:
    evaluator = EVALUATOR.read_text(encoding="utf-8")
    convergence = CONVERGENCE.read_text(encoding="utf-8")
    reanalysis = REANALYSIS.read_text(encoding="utf-8")

    flag = "--allow-incomplete-component-comparison"
    assert flag in evaluator
    assert "_validate_component_visibility(render)" in evaluator
    assert flag not in convergence
    assert flag in reanalysis
    assert "bodyrig.fidelity_evaluator_cli" in convergence
    assert "bodyrig.fidelity_evaluator_cli" in reanalysis


def test_component_visibility_evidence_never_claims_visual_or_release_acceptance() -> None:
    renderer = RENDERER.read_text(encoding="utf-8")
    evaluator = EVALUATOR.read_text(encoding="utf-8")
    semantics = "component-presence-and-runtime-visibility-not-visual-quality-acceptance"
    assert semantics in renderer
    assert semantics in evaluator
    assert "human_visual_authority_required = true" in renderer
    assert "production_activation = false" in renderer

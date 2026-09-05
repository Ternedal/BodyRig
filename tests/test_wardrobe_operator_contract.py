from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "prepare-wardrobe-source-capture.ps1"
RENDER = ROOT / "prepare-wardrobe-render-review.ps1"
REVIEW = ROOT / "record-wardrobe-authority.ps1"
FINALIZE = ROOT / "finalize-wardrobe-authority.ps1"


def test_source_capture_wrapper_is_checkout_bound() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert "git -C $repoRoot status --porcelain" in text
    assert "requires a clean BodyRig checkout" in text
    assert "git -C $repoRoot rev-parse HEAD" in text
    assert 'Join-Path $repoRoot ".venv\\Scripts\\python.exe"' in text
    assert "$env:PYTHONPATH = $repoRoot" in text
    assert "bodyrig.__file__" in text
    assert "-m bodyrig.wardrobe_source_capture_cli" in text
    assert "--bodyrig-revision $revision" in text


def test_render_wrapper_binds_comparison_package_and_deformation() -> None:
    text = RENDER.read_text(encoding="utf-8")
    assert "git -C $repoRoot status --porcelain" in text
    assert "Wardrobe render review requires a clean BodyRig checkout" in text
    assert 'Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1"' in text
    assert "-m bodyrig.wardrobe_package_lineage_cli" in text
    assert '"comparison-authority.json"' in text
    assert '"machine-probe.json"' in text
    assert '"deformation-probe.json"' in text
    assert '"wardrobe-render-set.json"' in text
    assert '"bodyrig-wardrobe-render-authority"' in text
    assert '"humanoid-muscle-sweep-v1"' in text
    assert "deformation_machine_pass = $true" in text
    assert "production_activation = $false" in text


def test_human_review_wrapper_requires_real_operator_note_and_optional_footwear_confirmation() -> None:
    text = REVIEW.read_text(encoding="utf-8")
    assert "git -C $repoRoot status --porcelain" in text
    assert "Wardrobe authority requires a clean BodyRig checkout" in text
    assert "if ($note -match '^<[^>]+>$')" in text
    assert "-m\", \"bodyrig.wardrobe_authority_cli" in text or "bodyrig.wardrobe_authority_cli" in text
    assert "--confirm-wardrobe-checklist" in text
    assert "--confirm-footwear-review" in text
    assert "--bodyrig-revision" in text


def test_finalizer_is_exact_head_bound_and_non_interactive() -> None:
    text = FINALIZE.read_text(encoding="utf-8")
    assert "git -C $repoRoot status --porcelain" in text
    assert "Wardrobe finalization requires a clean BodyRig checkout" in text
    assert "git -C $repoRoot rev-parse HEAD" in text
    assert "bodyrig.wardrobe_release_authority_cli" in text
    assert "--bodyrig-revision $revision" in text
    assert "ConfirmWardrobeChecklist" not in text
    assert "QualityNote" not in text

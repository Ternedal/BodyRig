from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "prepare-hands-feet-nails-source-capture.ps1"
RENDER = ROOT / "prepare-hands-feet-nails-render-review.ps1"
REVIEW = ROOT / "record-hands-feet-nails-authority.ps1"
FINALIZE = ROOT / "finalize-hands-feet-nails-authority.ps1"


def test_source_capture_wrapper_is_checkout_bound_and_clean() -> None:
    text = SOURCE.read_text(encoding="utf-8")

    assert "git -C $repoRoot status --porcelain" in text
    assert "requires a clean BodyRig checkout" in text
    assert "git -C $repoRoot rev-parse HEAD" in text
    assert 'Join-Path $repoRoot ".venv\\Scripts\\python.exe"' in text
    assert "$env:PYTHONPATH = $repoRoot" in text
    assert "bodyrig.__file__" in text
    assert "-m bodyrig.hands_feet_nails_source_capture_cli" in text
    assert "--bodyrig-revision $revision" in text
    assert "--selection-json $selectionPath" in text


def test_render_wrapper_uses_existing_canonical_fidelity_renderer_and_freezes_provenance() -> None:
    text = RENDER.read_text(encoding="utf-8")

    assert "git -C $repoRoot status --porcelain" in text
    assert "requires a clean BodyRig checkout" in text
    assert 'Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1"' in text
    assert "PackagePath = $package" in text
    assert '"hands-feet-nails-render-set.json"' in text
    assert '"bodyrig-hands-feet-nails-render-set"' in text
    assert '"human-review-diagnostic-not-physical-pass"' in text
    assert '@("left_hand", "right_hand", "left_foot", "right_foot")' in text
    assert '"comparison-authority.json"' in text
    assert '"bodyrig-fidelity-comparison-authority"' in text
    assert '"validated-package-comparison-only"' in text
    assert 'format = "bodyrig-hands-feet-nails-render-authority"' in text
    assert "comparison_authority_sha256 = $comparisonSha" in text
    assert "render_manifest_sha256 = $manifestSha" in text
    assert "Move-Item -LiteralPath $attempt -Destination $output" in text
    assert "production_activation = $false" in text


def test_review_wrapper_rejects_placeholder_and_uses_checkout_python() -> None:
    text = REVIEW.read_text(encoding="utf-8")

    assert "git -C $repoRoot status --porcelain" in text
    assert "requires a clean BodyRig checkout" in text
    assert "git -C $repoRoot rev-parse HEAD" in text
    assert 'Join-Path $repoRoot ".venv\\Scripts\\python.exe"' in text
    assert "$env:PYTHONPATH = $repoRoot" in text
    assert "bodyrig.__file__" in text
    assert "if ($note -match '^<[^>]+>$')" in text
    assert "-m bodyrig.hands_feet_nails_authority_cli" in text
    assert "--bodyrig-revision $revision" in text
    assert "--confirm-detail-checklist" in text


def test_finalizer_is_checkout_bound_and_requires_exact_render_revision() -> None:
    text = FINALIZE.read_text(encoding="utf-8")

    assert "git -C $repoRoot status --porcelain" in text
    assert "finalization requires a clean BodyRig checkout" in text
    assert "git -C $repoRoot rev-parse HEAD" in text
    assert '"hands-feet-nails-render-authority.json"' in text
    assert '"bodyrig-hands-feet-nails-render-authority"' in text
    assert "[string]$renderValue.bodyrig_revision -ne $revision" in text
    assert "$renderValue.comparison_only -ne $true" in text
    assert 'Join-Path $repoRoot ".venv\\Scripts\\python.exe"' in text
    assert "$env:PYTHONPATH = $repoRoot" in text
    assert "bodyrig.__file__" in text
    assert "-m bodyrig.hands_feet_nails_release_authority_cli" in text
    assert "--render-authority $renderAuthorityPath" in text

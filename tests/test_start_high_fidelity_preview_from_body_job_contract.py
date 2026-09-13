from pathlib import Path


def test_high_fidelity_preview_wrapper_is_revision_bound_and_state_changing() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "start-high-fidelity-preview-from-body-job.ps1").read_text(encoding="utf-8")

    assert "[ValidateSet('female','male','neutral')]" in source
    assert "[ValidatePattern('^[0-9a-f]{40}$')]" in source
    assert "update-windows.ps1" in source
    assert "-Revision $Revision -NoBrowser" in source
    assert '"$BaseUri/api/v1/health"' in source
    assert '"$BaseUri/api/v1/operator-authority"' in source
    assert 'serviceRevision -ne $Revision' in source
    assert 'body_job_id = $BodyJobId' in source
    assert 'target_family = $TargetFamily' in source
    assert 'body/high-fidelity-preview' in source
    assert "^hfpreview-[0-9a-f]{32}$" in source
    assert 'high-fidelity-preview-jobs/$previewJobId' in source
    assert "@('succeeded','failed','interrupted')" in source
    assert "high-fidelity-physical-status.ps1" in source
    assert "Checkout remains frozen on the historical producer revision" in source


def test_high_fidelity_preview_wrapper_does_not_synthesize_human_or_release_authority() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "start-high-fidelity-preview-from-body-job.ps1").read_text(encoding="utf-8")

    assert "record-high-fidelity-component-review.ps1" not in source
    assert "record-high-fidelity-human-review.ps1" not in source
    assert "complete-reference-acceptance.ps1" not in source
    assert "production_activation = $true" not in source

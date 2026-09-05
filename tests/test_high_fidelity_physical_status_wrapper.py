from pathlib import Path


def test_high_fidelity_physical_status_wrapper_is_checkout_bound_and_read_only() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "high-fidelity-physical-status.ps1").read_text(encoding="utf-8")

    assert "high_fidelity_release_readiness_cli" in source
    assert '"--preview-job-id", $PreviewJobId' in source
    assert '"--operator-root", $repoRoot' in source
    assert '"--quest-serial", $Serial' in source
    assert "if (-not [string]::IsNullOrWhiteSpace($Serial))" in source
    assert "bodyrig.__file__" in source
    assert "PowerShell 7+" in source
    assert "Python 3.11+" in source
    assert "Remove-Item" not in source
    assert "Set-Content" not in source
    assert "Out-File" not in source

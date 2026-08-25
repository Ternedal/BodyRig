from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

WRITERS = {
    "run-windows-renderer-probe.ps1": "New-Item -ItemType Directory -Path $attemptDir",
    "run-quest-renderer-probe.ps1": "New-Item -ItemType Directory -Path $attemptDir",
    "record-renderer-acceptance.ps1": "if ([string]::IsNullOrWhiteSpace($Output))",
    "complete-acceptance.ps1": "if([string]::IsNullOrWhiteSpace($Output))",
}


def test_low_level_evidence_writers_require_windows_ps7_before_output() -> None:
    for name, output_marker in WRITERS.items():
        source = (ROOT / name).read_text(encoding="utf-8")
        windows_gate = source.index("[System.Environment]::OSVersion.Platform")
        version_gate = source.index("$PSVersionTable.PSVersion.Major -lt 7")
        pwsh_resolution = source.index("Get-Command pwsh -ErrorAction SilentlyContinue")
        output_boundary = source.index(output_marker)

        assert windows_gate < version_gate < pwsh_resolution < output_boundary, name
        assert "The canonical BodyRig physical evidence path is Windows-only." in source
        assert "PowerShell 7+ (pwsh) is required for the canonical BodyRig physical evidence path." in source
        assert "PowerShell 7 executable (pwsh) was not found for the canonical BodyRig physical evidence path." in source
        assert "Get-Command powershell" not in source
        assert 'Resolve-CommandPath "powershell"' not in source


def test_executed_release_tamper_suite_runs_on_windows() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    linux_jobs, windows_job = workflow.split("  acceptance-windows:", 1)

    assert "Test final acceptance gate" not in linux_jobs
    assert "runs-on: windows-latest" in windows_job
    assert "Test final acceptance gate on production OS" in windows_job
    assert "./tests/test-complete-acceptance.ps1" in windows_job
    assert "Assert exact checkout authority" in windows_job

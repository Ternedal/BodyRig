from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_gate_a_requires_windows_ps7_before_git_binding_or_acceptance_output() -> None:
    source = (REPO / "accept-physical-clone.ps1").read_text(encoding="utf-8")

    windows_gate = source.index("[System.Environment]::OSVersion.Platform")
    version_gate = source.index("$PSVersionTable.PSVersion.Major -lt 7")
    pwsh_resolution = source.index("Get-Command pwsh -ErrorAction SilentlyContinue")
    repo_binding = source.index("$repoRoot = (Resolve-Path $PSScriptRoot).Path")
    git_binding = source.index("git -C $repoRoot rev-parse HEAD")
    output_creation = source.index("New-Item -ItemType Directory -Path $OutputDir")

    assert windows_gate < version_gate < pwsh_resolution < repo_binding < git_binding < output_creation
    assert "The canonical BodyRig physical acceptance path is Windows-only." in source
    assert "PowerShell 7+ (pwsh) is required for the canonical BodyRig physical acceptance path." in source
    assert "PowerShell 7 executable (pwsh) was not found for the canonical BodyRig physical acceptance path." in source


def test_gate_a_has_no_legacy_powershell_fallback() -> None:
    source = (REPO / "accept-physical-clone.ps1").read_text(encoding="utf-8")
    assert 'Get-Command powershell' not in source
    assert 'Resolve-CommandPath "powershell"' not in source

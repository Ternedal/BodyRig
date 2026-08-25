from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


CANONICAL_EVIDENCE_WRITERS = {
    "run-reference-windows-renderer-probe.ps1": "& $inner @args",
    "run-reference-quest-renderer-probe.ps1": "& $inner @args",
    "record-reference-renderer-acceptance.ps1": "& $recordScript @args",
    "complete-reference-acceptance.ps1": "& $core @args",
}


def test_canonical_reference_evidence_writers_require_windows_ps7_before_delegate() -> None:
    for relative, delegate_token in CANONICAL_EVIDENCE_WRITERS.items():
        source = (REPO / relative).read_text(encoding="utf-8")
        windows_gate = source.index("[System.Environment]::OSVersion.Platform")
        version_gate = source.index("$PSVersionTable.PSVersion.Major -lt 7")
        pwsh_resolution = source.index("Get-Command pwsh -ErrorAction SilentlyContinue")
        repo_binding = source.index("$repoRoot = (Resolve-Path $PSScriptRoot).Path")
        delegate = source.index(delegate_token)

        assert windows_gate < version_gate < pwsh_resolution < repo_binding < delegate
        assert "The canonical BodyRig physical acceptance path is Windows-only." in source
        assert "PowerShell 7+ (pwsh) is required for the canonical BodyRig physical acceptance path." in source
        assert "PowerShell 7 executable (pwsh) was not found for the canonical BodyRig physical acceptance path." in source


def test_canonical_reference_evidence_writers_do_not_offer_legacy_powershell_fallback() -> None:
    for relative in CANONICAL_EVIDENCE_WRITERS:
        source = (REPO / relative).read_text(encoding="utf-8")
        assert 'Get-Command powershell' not in source
        assert 'Resolve-CommandPath "powershell"' not in source

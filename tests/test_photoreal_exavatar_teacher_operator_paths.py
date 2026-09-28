from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "run-photoreal-v2-exavatar-teacher.ps1").read_text(encoding="utf-8")
WORKSPACE_SCRIPT = (ROOT / "prepare-photoreal-exavatar-workspace.ps1").read_text(encoding="utf-8")


def test_exavatar_operator_allows_missing_preflight_output_leaf_only() -> None:
    assert "[switch]$AllowMissingLeaf" in SCRIPT
    assert "$linuxPreflight = Convert-ToWslPath -WindowsPath $strictPreflight -AllowMissingLeaf" in SCRIPT
    assert SCRIPT.count("-AllowMissingLeaf") == 1
    assert 'Translated WSL output parent does not exist' in SCRIPT
    assert '/usr/bin/test -d $candidateParent' in SCRIPT


def test_exavatar_operator_forwards_rebuild_workspace_explicitly() -> None:
    assert "[switch]$RebuildWorkspace" in SCRIPT
    assert "[switch]$RebuildWorkspace" in WORKSPACE_SCRIPT
    assert "RebuildWorkspace = $RebuildWorkspace" in SCRIPT
    assert "& $workspaceOperator @workspaceParams" in SCRIPT

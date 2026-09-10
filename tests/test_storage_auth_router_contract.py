from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS = (ROOT / "bodyrig-status.ps1").read_text(encoding="utf-8")


def test_performer_preflight_requires_reboot_qualified_storage_first() -> None:
    storage_decl = STATUS.index('$storageAuthStatus = Join-Path $repoRoot "storage-auth-status.ps1"')
    performer_block = STATUS.index("if ($hasPerformer -and $hasBodyId)")
    storage_call = STATUS.index("& $storageAuthStatus -PerformerId $PerformerId -Json", performer_block)
    qualification = STATUS.index('$storage.qualified -ne $true', storage_call)
    blocked = STATUS.index("persistent storage authentication is not reboot-qualified", qualification)
    profiled = STATUS.index("Invoke-CanonicalStatus -Script $profiledFirstPhysicalRun", blocked)
    assert storage_decl < performer_block < storage_call < qualification < blocked < profiled


def test_unqualified_storage_routes_next_command_without_starting_source_doctor() -> None:
    performer_block = STATUS.index("if ($hasPerformer -and $hasBodyId)")
    composition_block = STATUS.index("if ($hasComposition)", performer_block)
    segment = STATUS[performer_block:composition_block]
    assert "if ($storage.qualified -ne $true" in segment
    assert "Write-Host ([string]$storage.next_command)" in segment
    assert "exit 3" in segment
    assert segment.index("exit 3") < segment.index("Invoke-CanonicalStatus -Script $profiledFirstPhysicalRun")


def test_qualified_storage_is_visible_before_profiled_preflight() -> None:
    assert "BodyRig persistent storage authentication: QUALIFIED" in STATUS
    assert "cold-boots=" in STATUS

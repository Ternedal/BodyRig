from pathlib import Path


def test_operator_runbook_uses_preflight_status_loop_and_reference_wrappers() -> None:
    root = Path(__file__).resolve().parents[1]
    runbook = (root / "HIGH-FIDELITY-PHYSICAL-RUNBOOK.md").read_text(encoding="utf-8")

    assert "high-fidelity-rig-preflight.ps1" in runbook
    assert "check-reference-renderer-ready.ps1" in runbook
    assert "pinned Unity-SDK `adb.exe`" in runbook
    assert "-RequireQuestConnected" in runbook
    assert "-Serial $questSerial" in runbook
    assert "list-high-fidelity-previews.ps1 -SucceededOnly" in runbook
    assert "high-fidelity-physical-status.ps1 -PreviewJobId $preview" in runbook
    assert "prepare-high-fidelity-physical-acceptance.ps1 -PreviewJobId $preview" in runbook
    assert "physical_windows_acceptance" in runbook
    assert "physical_quest_acceptance" in runbook
    assert "run-reference-windows-renderer-probe.ps1" in runbook
    assert "record-reference-renderer-acceptance.ps1" in runbook
    assert "run-reference-quest-renderer-probe.ps1" in runbook
    assert "complete-reference-acceptance.ps1" in runbook
    assert "reference_acceptance_policy" in runbook
    assert "status layer injects the `adb.exe` from the pinned Unity Android SDK automatically" in runbook
    assert "manually rewrite the generated command" in runbook
    assert "final_release" in runbook
    assert "production_ready=true" in runbook
    assert "production_activation=true" in runbook
    assert "checkout freeze" in runbook.lower()
    assert "Do not edit JSON evidence by hand" in runbook
    assert "accept-reconciled-physical-clone.ps1" in runbook
    assert "Do not call the low-level renderer/core acceptance scripts directly" in runbook


def test_preview_listing_wrapper_is_read_only_checkout_bound_discovery() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "list-high-fidelity-previews.ps1").read_text(encoding="utf-8")

    assert "high_fidelity_preview_list_cli" in source
    assert "bodyrig.__file__" in source
    assert "Remove-Item" not in source
    assert "Set-Content" not in source
    assert "Out-File" not in source

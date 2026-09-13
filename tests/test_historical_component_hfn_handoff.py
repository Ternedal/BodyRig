from __future__ import annotations

import bodyrig.rig_window_component_authority as component


OLD = "b" * 40
HEAD = "a" * 40
PREVIEW = "hfpreview-" + "3" * 32


def test_historical_status_stays_legacy_until_component_chain_is_complete() -> None:
    command = component._historical_status_command(
        revision=OLD,
        preview_job_id=PREVIEW,
        head=HEAD,
    )

    assert f"update-windows.ps1 -Revision '{OLD}' -NoBrowser -SkipPlan" in command
    assert f"high-fidelity-physical-status.ps1 -PreviewJobId '{PREVIEW}' -Json" in command
    assert "$legacyStatus.high_fidelity_complete -eq $true" in command
    assert "update-windows.ps1 -NoBrowser -SkipPlan" in command
    assert command.count(f"high-fidelity-physical-status.ps1 -PreviewJobId '{PREVIEW}'") == 3


def test_current_revision_status_does_not_reenter_historical_checkout() -> None:
    command = component._historical_status_command(
        revision=HEAD,
        preview_job_id=PREVIEW,
        head=HEAD,
    )

    assert command == f".\\high-fidelity-physical-status.ps1 -PreviewJobId '{PREVIEW}'"

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "update-windows.ps1").read_text(encoding="utf-8")


def test_update_never_reuses_powershell_pid_constant_as_loop_variable() -> None:
    assert "foreach ($pid " not in SCRIPT.lower()
    assert "foreach ($ownerprocessid in $listenerpids)" in SCRIPT.lower()


def test_update_verifies_service_before_stopping_listener() -> None:
    assert '[string]$health.service -ne "bodyrig"' in SCRIPT
    assert "Refuserer at stoppe en ukendt proces" in SCRIPT
    assert "Stop-Process -Id ([int]$ownerProcessId)" in SCRIPT


def test_update_fetches_target_branch_explicitly_before_checkout() -> None:
    assert '$sourceRef = "refs/heads/$Branch"' in SCRIPT
    assert '$remoteRef = "refs/remotes/$Remote/$Branch"' in SCRIPT
    assert '& git fetch $Remote "$sourceRef`:$remoteRef"' in SCRIPT
    assert '& git checkout --detach $target' in SCRIPT


def test_update_installs_only_after_old_service_has_been_stopped() -> None:
    stop_index = SCRIPT.index("Stop-VerifiedBodyRigService")
    install_index = SCRIPT.index(' -m pip install --disable-pip-version-check -e ".[test]"')
    assert stop_index < install_index


def test_update_verifies_running_revision_after_restart() -> None:
    assert '[string]$state.revision -ne $target' in SCRIPT
    assert 'Write-Host "BodyRig update: READY"' in SCRIPT

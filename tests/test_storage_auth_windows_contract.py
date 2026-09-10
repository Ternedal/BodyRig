from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = (ROOT / "setup-storage-auth-windows.ps1").read_text(encoding="utf-8")
TEST = (ROOT / "test-storage-auth-windows.ps1").read_text(encoding="utf-8")
VERIFY = (ROOT / "verify-storage-auth-after-reboot.ps1").read_text(encoding="utf-8")


def test_setup_uses_native_windows_credential_manager_without_cli_password() -> None:
    lowered = SETUP.lower()
    assert 'entrypoint = "credwritew"' in lowered
    assert "credential.type = 2" in lowered
    assert "credential.persist = 2" in lowered
    assert "get-credential" in lowered
    assert "cmdkey" not in lowered
    assert "/pass:" not in lowered
    assert "net use" not in lowered
    assert 'password_persisted_in_config = $false' in lowered
    assert 'credential_store = "windows-credential-manager-domain-password"' in lowered


def test_setup_binds_credential_target_to_exact_saved_stash_host() -> None:
    assert "$StorageHost = Resolve-StorageHost" in SETUP
    assert "$target = $StorageHost.ToLowerInvariant()" in SETUP
    assert "Saved Stash URL has no host" in SETUP
    assert 'credential_target = $target' in SETUP


def test_fresh_session_test_resets_smb_and_decodes_real_stash_source() -> None:
    lowered = TEST.lower()
    assert "[switch]$resetconnections" in lowered
    assert "get-smbconnection" in lowered
    assert "net.exe" in lowered
    assert "configure-stash-path-map.ps1" in lowered
    assert "-forcerrefresh" not in lowered  # typo guard
    assert "-forcerefresh" in lowered
    assert "bodyrig.stash_cli" in lowered
    assert "probe" in lowered
    assert "--performer-id" in lowered
    assert "--ffmpeg" in lowered
    assert 'real_stash_source_decode = $true' in lowered
    assert 'credential_prompt_used = $false' in lowered
    assert 'secret_persisted_in_proof = $false' in lowered


def test_fresh_session_test_refuses_storage_host_alias_drift() -> None:
    assert "does not match the host used by Stash" in TEST
    assert "Storage credential target does not exactly match the UNC host authority" in TEST


def test_pre_reboot_mark_requires_fresh_smb_session() -> None:
    assert "if ($MarkPreReboot -and -not $ResetConnections)" in TEST
    assert "fresh_smb_session_proved = $true" in TEST
    assert "required_distinct_post_reboot_boots = 2" in TEST


def test_post_reboot_verifier_requires_a_new_boot_and_two_unique_passes() -> None:
    lowered = VERIFY.lower()
    assert "lastbootuptime" in lowered
    assert "windows has not rebooted since the pre-reboot proof" in lowered
    assert "this windows boot session has already been counted" in lowered
    assert "required_distinct_post_reboot_boots" in lowered
    assert "successful_boot_count" in lowered
    assert "qualified = [bool]$qualified" in lowered
    assert "credential_prompt_permitted = $false" in lowered
    assert "real_stash_source_decode_required = $true" in lowered
    assert "secret_persisted_in_proof = $false" in lowered


def test_post_reboot_verifier_never_requests_credentials() -> None:
    lowered = VERIFY.lower()
    assert "get-credential" not in lowered
    assert "cmdkey" not in lowered
    assert "/pass:" not in lowered
    assert "test-storage-auth-windows.ps1" in lowered

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NATIVE = (ROOT / "storage-auth-native.ps1").read_text(encoding="utf-8")
SETUP = (ROOT / "setup-storage-auth-windows.ps1").read_text(encoding="utf-8")
TEST = (ROOT / "test-storage-auth-windows.ps1").read_text(encoding="utf-8")
STATUS = (ROOT / "storage-auth-status.ps1").read_text(encoding="utf-8")
VERIFY = (ROOT / "verify-storage-auth-after-reboot.ps1").read_text(encoding="utf-8")


def test_native_helper_uses_windows_credential_manager_domain_password() -> None:
    lowered = NATIVE.lower()
    assert 'entrypoint = "credwritew"' in lowered
    assert 'entrypoint = "credreadw"' in lowered
    assert 'entrypoint = "credgetsessiontypes"' in lowered
    assert "credential.type = 2" in lowered
    assert "credential.persist = 2" in lowered
    assert "values[2]" in lowered
    assert "set-bodyrigdomaincredential" in lowered
    assert "test-bodyrigdomaincredential" in lowered
    assert "get-bodyrigdomaincredentialmaxpersist" in lowered
    assert "cmdkey" not in lowered
    assert "/pass:" not in lowered


def test_setup_uses_shared_native_helper_without_cli_password() -> None:
    lowered = SETUP.lower()
    assert '"storage-auth-native.ps1"' in lowered
    assert ". $nativehelper" in lowered
    assert "get-bodyrigdomaincredentialmaxpersist" in lowered
    assert "set-bodyrigdomaincredential" in lowered
    assert "test-bodyrigdomaincredential" in lowered
    assert "get-credential" in lowered
    assert "cmdkey" not in lowered
    assert "/pass:" not in lowered
    assert "net use" not in lowered
    assert 'password_persisted_in_config = $false' in lowered
    assert 'credential_store = "windows-credential-manager-domain-password"' in lowered
    assert 'requested_persist = "local-machine"' in lowered


def test_setup_binds_credential_target_to_exact_saved_stash_host() -> None:
    assert "$StorageHost = Resolve-StorageHost" in SETUP
    assert "$target = $StorageHost.ToLowerInvariant()" in SETUP
    assert "Saved Stash URL has no host" in SETUP
    assert 'credential_target = $target' in SETUP


def test_new_or_replaced_credential_starts_a_new_qualification_generation() -> None:
    lowered = SETUP.lower()
    assert '$credentialgeneration = [guid]::newguid().tostring("d").tolowerinvariant()' in lowered
    assert "storage-session-proof.json" in lowered
    assert "storage-pre-reboot-proof.json" in lowered
    assert "storage-cold-boot-proof.json" in lowered
    assert "remove-item" in lowered
    assert "credential_generation = $credentialgeneration" in lowered
    assert "prior proofs:" in lowered
    credential_write = lowered.index("set-bodyrigdomaincredential")
    proof_clear = lowered.index("storage-session-proof.json", credential_write)
    config_generation = lowered.index("credential_generation = $credentialgeneration", proof_clear)
    assert credential_write < proof_clear < config_generation


def test_fresh_session_test_resets_smb_and_decodes_real_stash_source() -> None:
    lowered = TEST.lower()
    assert '"storage-auth-native.ps1"' in lowered
    assert ". $nativehelper" in lowered
    assert "test-bodyrigdomaincredential" in lowered
    assert "get-bodyrigdomaincredentialmaxpersist" in lowered
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


def test_fresh_session_test_refuses_storage_host_alias_and_generation_drift() -> None:
    assert "does not match the host used by Stash" in TEST
    assert "Storage credential target does not exactly match the UNC host authority" in TEST
    assert "credential_generation" in TEST
    assert "canonical credential generation" in TEST


def test_pre_reboot_mark_requires_fresh_smb_session_and_resets_old_cold_counter() -> None:
    assert "if ($MarkPreReboot -and -not $ResetConnections)" in TEST
    assert "fresh_smb_session_proved = $true" in TEST
    assert "required_distinct_post_reboot_boots = 2" in TEST
    mark = TEST.index("if ($MarkPreReboot)")
    clear = TEST.index("Remove-Item -LiteralPath $coldProofPath", mark)
    write = TEST.index("storage-pre-reboot-proof", clear)
    assert mark < clear < write


def test_status_uses_shared_native_helper_and_never_reads_secret() -> None:
    lowered = STATUS.lower()
    assert '"storage-auth-native.ps1"' in lowered
    assert ". $nativehelper" in lowered
    assert "test-bodyrigdomaincredential" in lowered
    assert "get-bodyrigdomaincredentialmaxpersist" in lowered
    assert "credential_generation" in lowered
    assert "get-credential" not in lowered
    assert "securestringtobstr" not in lowered
    assert "cmdkey" not in lowered


def test_post_reboot_verifier_requires_new_boot_two_unique_passes_and_same_generation() -> None:
    lowered = VERIFY.lower()
    assert "lastbootuptime" in lowered
    assert "windows has not rebooted since the pre-reboot proof" in lowered
    assert "this windows boot session has already been counted" in lowered
    assert "required_distinct_post_reboot_boots" in lowered
    assert "successful_boot_count" in lowered
    assert "qualified = [bool]$qualified" in lowered
    assert "credential_generation" in lowered
    assert "different credential generation" in lowered
    assert "credential_prompt_permitted = $false" in lowered
    assert "real_stash_source_decode_required = $true" in lowered
    assert "secret_persisted_in_proof = $false" in lowered


def test_post_reboot_verifier_never_requests_credentials() -> None:
    lowered = VERIFY.lower()
    assert "get-credential" not in lowered
    assert "cmdkey" not in lowered
    assert "/pass:" not in lowered
    assert "test-storage-auth-windows.ps1" in lowered

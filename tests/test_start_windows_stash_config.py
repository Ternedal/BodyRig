from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "start-windows.ps1").read_text(encoding="utf-8")


def test_start_windows_persists_stash_auth_outside_repo_with_dpapi() -> None:
    assert 'Join-Path $ConfigDir "stash.json"' in SCRIPT
    assert 'format = "bodyrig-local-stash-config"' in SCRIPT
    assert "ConvertFrom-SecureString $secure" in SCRIPT
    assert "ConvertTo-SecureString ([string]$config.api_key_dpapi)" in SCRIPT
    assert "SecureStringToBSTR" in SCRIPT
    assert "ZeroFreeBSTR" in SCRIPT


def test_start_windows_never_serializes_plaintext_stash_key() -> None:
    config_block = SCRIPT.split('format = "bodyrig-local-stash-config"', 1)[1].split("function Restore-StashLocalConfig", 1)[0]
    assert "api_key_dpapi" in config_block
    assert "STASH_API_KEY =" not in config_block

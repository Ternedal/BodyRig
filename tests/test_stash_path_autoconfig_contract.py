from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "configure-stash-path-map.ps1").read_text(encoding="utf-8")


def test_stash_path_autoconfig_uses_saved_dpapi_credentials_without_printing_key() -> None:
    assert 'bodyrig-local-stash-config' in SCRIPT
    assert 'ConvertTo-SecureString $protectedKey' in SCRIPT
    assert 'SecureStringToBSTR' in SCRIPT
    assert 'ZeroFreeBSTR' in SCRIPT
    assert 'Write-Host $apiKey' not in SCRIPT


def test_stash_path_autoconfig_discovers_actual_stash_scene_paths() -> None:
    assert 'BodyRigPathDiscovery' in SCRIPT
    assert 'findScenes' in SCRIPT
    assert 'files { path }' in SCRIPT
    assert 'performers { id }' in SCRIPT
    assert 'scene_filter: {performers:' in SCRIPT
    assert 'scene_filter: {performer_id:' in SCRIPT


def test_stash_path_autoconfig_only_accepts_concrete_readable_files() -> None:
    assert 'Test-Path -LiteralPath $shareRoot -PathType Container' in SCRIPT
    assert 'Test-Path -LiteralPath $candidate -PathType Leaf' in SCRIPT
    assert '$bestHits -gt 0' in SCRIPT
    assert 'kunne ikke bevise en læsbar SMB-mapping' in SCRIPT


def test_stash_path_autoconfig_targets_same_stash_host_vr_drive_shares() -> None:
    assert '$hostName = [string]$stashUri.Host' in SCRIPT
    assert '$shareRoot = "\\\\$hostName\\VR_$drive"' in SCRIPT
    assert 'BODYRIG_STASH_PATH_MAP' in SCRIPT


def test_stash_path_autoconfig_persists_non_secret_verified_mapping() -> None:
    assert '[Environment]::SetEnvironmentVariable("BODYRIG_STASH_PATH_MAP"' in SCRIPT
    assert 'stash-path-map.json' in SCRIPT
    assert 'verified_files' in SCRIPT
    assert 'candidate_files' in SCRIPT

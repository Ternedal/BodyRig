from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "configure-stash-path-map.ps1").read_text(encoding="utf-8")


def test_stash_path_autoconfig_uses_saved_dpapi_credentials_without_printing_key() -> None:
    assert 'bodyrig-local-stash-config' in SCRIPT
    assert 'ConvertTo-SecureString $protectedKey' in SCRIPT
    assert 'SecureStringToBSTR' in SCRIPT
    assert 'ZeroFreeBSTR' in SCRIPT
    assert 'Write-Host $apiKey' not in SCRIPT


def test_stash_path_autoconfig_checks_cache_before_decrypting_or_querying_stash() -> None:
    cache = SCRIPT.index('bodyrig.stash_path_cache')
    decrypt = SCRIPT.index('ConvertTo-SecureString $protectedKey')
    graphql = SCRIPT.index('function Invoke-StashGraphQl')
    assert cache < decrypt < graphql
    assert 'CACHE HIT' in SCRIPT
    assert 'cache MISS; refreshing from Stash' in SCRIPT
    assert '[switch]$ForceRefresh' in SCRIPT


def test_stash_path_autoconfig_cache_is_bound_to_current_performer_scope() -> None:
    cache = SCRIPT.index('bodyrig.stash_path_cache')
    assert '[string]$PerformerId = ""' in SCRIPT
    assert '$hasExplicitPerformer = -not [string]::IsNullOrWhiteSpace($PerformerId)' in SCRIPT
    assert '$performerIds = @($PerformerId.Trim())' in SCRIPT
    assert 'performer-scoped discovery/cache' in SCRIPT
    assert '$cacheArgs += @("--performer-id", [string]$performerIdItem)' in SCRIPT
    assert 'stash_origin = $stashOrigin' in SCRIPT
    assert 'performer_ids = @($performerIds)' in SCRIPT
    assert 'version = 2' in SCRIPT
    assert SCRIPT.index('$performerIds = @($PerformerId.Trim())') < cache


def test_unscoped_stash_path_autoconfig_still_uses_person_profiles() -> None:
    assert 'Get-ChildItem -LiteralPath $PeopleDir -Filter "*.json"' in SCRIPT
    assert '$profilePerformerId = [string](Get-OptionalPropertyValue -Object $source -Name "performer_id")' in SCRIPT
    assert '$kind -eq "stash-performer"' in SCRIPT
    assert 'Sort-Object -Unique' in SCRIPT


def test_explicit_performer_does_not_require_existing_people_directory() -> None:
    guard = 'if (-not $hasExplicitPerformer -and -not (Test-Path -LiteralPath $PeopleDir -PathType Container))'
    assert guard in SCRIPT


def test_stash_path_autoconfig_discovers_actual_stash_scene_paths() -> None:
    assert 'BodyRigPathDiscovery' in SCRIPT
    assert 'findScenes' in SCRIPT
    assert 'files { path }' in SCRIPT
    assert 'performers { id }' in SCRIPT
    assert 'scene_filter: {performers:' in SCRIPT
    assert 'scene_filter: {performer_id:' in SCRIPT
    assert 'foreach ($performerIdItem in $performerIds)' in SCRIPT
    assert '$variables = @{ id = $performerIdItem; limit = 200 }' in SCRIPT


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
    assert 'api_key_dpapi = ' not in SCRIPT[SCRIPT.index('$evidence = [ordered]@{'):]


def test_stash_path_autoconfig_cache_hit_returns_before_full_discovery() -> None:
    cache_hit = SCRIPT.index('Write-Host "BodyRig Stash path map: CACHE HIT')
    return_after_hit = SCRIPT.index('\n                    return\n', cache_hit)
    current_query = SCRIPT.index("$currentQuery = @'")
    assert cache_hit < return_after_hit < current_query

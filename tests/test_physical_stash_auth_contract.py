from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = (ROOT / "stash-auth-local.ps1").read_text(encoding="utf-8")
PROFILED = (ROOT / "prepare-profiled-first-physical-run.ps1").read_text(encoding="utf-8")
DOCTOR = (ROOT / "prepare-first-physical-run.ps1").read_text(encoding="utf-8")
READINESS = (ROOT / "check-rig-ready.ps1").read_text(encoding="utf-8")


def test_saved_stash_auth_helper_uses_dpapi_and_never_accepts_secret_arguments() -> None:
    assert 'BodyRig\\config\\stash.json' in HELPER
    assert 'format -ne "bodyrig-local-stash-config"' in HELPER
    assert "ConvertTo-SecureString $protectedKey" in HELPER
    assert "SecureStringToBSTR" in HELPER
    assert "ZeroFreeBSTR" in HELPER
    assert '[Environment]::SetEnvironmentVariable("STASH_URL", $savedUrl, "Process")' in HELPER
    assert '[Environment]::SetEnvironmentVariable($ApiKeyEnv, $apiKey, "Process")' in HELPER
    assert "Requested Stash URL differs from saved BodyRig Stash authority." in HELPER
    assert "param(" in HELPER
    assert "ApiKey =" not in HELPER
    assert "Password =" not in HELPER


def test_profiled_preflight_restores_auth_before_path_map_and_isolated_doctor() -> None:
    helper = PROFILED.index(". $stashAuthHelper")
    imported = PROFILED.index("$null = Import-BodyRigSavedStashAuth", helper)
    path_map = PROFILED.index("& $pathMapConfig -PerformerId $PerformerId", imported)
    doctor = PROFILED.index("$attempt = Invoke-CanonicalDoctorProcess", path_map)
    assert helper < imported < path_map < doctor


def test_first_physical_doctor_binds_explicit_or_implicit_url_to_saved_auth() -> None:
    helper = DOCTOR.index(". $stashAuthHelper")
    imported = DOCTOR.index("$StashUrl = Import-BodyRigSavedStashAuth -ExpectedUrl $StashUrl -ApiKeyEnv $ApiKeyEnv", helper)
    renderer = DOCTOR.index('Write-Host "Checking Unity/Quest reference-renderer toolchain..."', imported)
    readiness = DOCTOR.index("& $powerShellExe @readinessArgs", renderer)
    performer_probe = DOCTOR.index('"bodyrig.stash_cli", "probe"', readiness)
    assert helper < imported < renderer < readiness < performer_probe
    assert "--api-key" not in DOCTOR


def test_live_readiness_self_restores_saved_auth_before_graphql_health() -> None:
    helper = READINESS.index(". $stashAuthHelper")
    imported = READINESS.index("$StashUrl = Import-BodyRigSavedStashAuth -ExpectedUrl $StashUrl -ApiKeyEnv $ApiKeyEnv", helper)
    health = READINESS.index('"bodyrig.stash_cli", "health"', imported)
    assert helper < imported < health
    assert "--api-key" not in READINESS

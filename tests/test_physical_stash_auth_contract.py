from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = (ROOT / "stash-auth-local.ps1").read_text(encoding="utf-8")
PROFILED = (ROOT / "prepare-profiled-first-physical-run.ps1").read_text(encoding="utf-8")
DOCTOR = (ROOT / "prepare-first-physical-run.ps1").read_text(encoding="utf-8")
READINESS = (ROOT / "check-rig-ready.ps1").read_text(encoding="utf-8")
PROFILED_CLONE = (ROOT / "clone-body-from-stash-profiled-ready.ps1").read_text(encoding="utf-8")
READY_CLONE = (ROOT / "clone-body-from-stash-ready.ps1").read_text(encoding="utf-8")


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
    renderer_call = "& $rendererReadinessScript"
    renderer_tail = DOCTOR[DOCTOR.index(renderer_call):DOCTOR.index(renderer_call) + 220]
    assert "$LASTEXITCODE" not in renderer_tail



def test_live_readiness_self_restores_saved_auth_before_graphql_health() -> None:
    helper = READINESS.index(". $stashAuthHelper")
    imported = READINESS.index("$StashUrl = Import-BodyRigSavedStashAuth -ExpectedUrl $StashUrl -ApiKeyEnv $ApiKeyEnv", helper)
    health = READINESS.index('"bodyrig.stash_cli", "health"', imported)
    assert helper < imported < health
    assert "--api-key" not in READINESS


def test_profiled_production_clone_restores_saved_auth_before_profile_lookup() -> None:
    helper = PROFILED_CLONE.index(". $stashAuthHelper")
    imported = PROFILED_CLONE.index("$StashUrl = Import-BodyRigSavedStashAuth -ExpectedUrl $StashUrl -ApiKeyEnv $ApiKeyEnv", helper)
    profile = PROFILED_CLONE.index('"bodyrig.stash_performer_profile"', imported)
    ready = PROFILED_CLONE.index("& $readyScript @forward", profile)
    assert helper < imported < profile < ready
    tail = PROFILED_CLONE[ready:ready + 220]
    assert "$LASTEXITCODE" not in tail
    assert "--api-key" not in PROFILED_CLONE


def test_ready_production_clone_self_restores_saved_auth_before_session_start() -> None:
    helper = READY_CLONE.index(". $stashAuthHelper")
    imported = READY_CLONE.index("$StashUrl = Import-BodyRigSavedStashAuth -ExpectedUrl $StashUrl -ApiKeyEnv $ApiKeyEnv", helper)
    session = READY_CLONE.index('Invoke-SessionCommand -Arguments @(', imported)
    assert helper < imported < session
    assert '"stash-auth-local.ps1"' in READY_CLONE
    assert "--api-key" not in READY_CLONE

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _launcher() -> str:
    return (ROOT / "clone-body-from-stash-ready.ps1").read_text(encoding="utf-8")


def test_ready_launcher_uses_master_report_live_readiness_and_existing_stash_pipeline():
    text = _launcher()
    assert "BODYRIG_RIG_SETUP_REPORT" in text
    assert "-m bodyrig.rig_setup $RigSetupReport" in text
    assert "-m bodyrig.sith_setup $sithReport" in text
    assert "check-rig-ready.ps1" in text
    assert "clone-body-from-stash.ps1" in text
    assert '"-RigSetupReport", $RigSetupReport' in text
    assert '"-BodyRigPython", $BodyRigPython' in text
    assert '"-WslExe", $WslExe' in text
    assert '"-ExternalPython", $externalPython' in text
    assert '"-FourDHumansRepo", $fourDHumansRepo' in text
    assert '"-BodyId", $BodyId' in text


def test_ready_launcher_requires_readiness_before_clone():
    text = _launcher()
    readiness_call = text.index("& $powerShellExe @readinessArgs")
    readiness_failure = text.index("clone not started")
    clone_call = text.index("& $powerShellExe @cloneArgs")
    assert readiness_call < readiness_failure < clone_call
    assert "Live readiness: PASS" in text
    assert "source + binary + models" in text


def test_ready_launcher_requires_windows_powershell_7_and_pwsh_before_session_creation():
    text = _launcher()
    windows_gate = text.index("[System.Environment]::OSVersion.Platform")
    version_gate = text.index("$PSVersionTable.PSVersion.Major -lt 7")
    pwsh_resolution = text.index('Resolve-CommandPath "pwsh"')
    git_binding = text.index("git -C $repoRoot rev-parse HEAD")
    session_start = text.index("Invoke-SessionCommand -Arguments @(")

    assert windows_gate < version_gate < pwsh_resolution < git_binding < session_start
    assert "PowerShell 7+ (pwsh) is required" in text
    assert "PowerShell 7 executable (pwsh) was not found" in text
    assert 'Resolve-CommandPath "powershell"' not in text


def test_ready_launcher_rehydrates_all_builtin_sith_settings():
    text = _launcher()
    for setting in (
        "BODYRIG_SITH_SETUP_REPORT",
        "BODYRIG_SITH_DISTRIBUTION",
        "BODYRIG_SITH_REPO",
        "BODYRIG_SITH_PYTHON",
        "BODYRIG_SITH_OPENPOSE_REPO",
        "BODYRIG_SITH_OPENPOSE",
        "BODYRIG_SITH_OPENPOSE_SHA256",
        "BODYRIG_SITH_OPENPOSE_MODELS_SHA256",
        "BODYRIG_SITH_DIFFUSION_MODEL",
        "BODYRIG_SITH_DIFFUSION_SHA256",
    ):
        assert setting in text


def test_ready_launcher_does_not_duplicate_clone_engine():
    text = _launcher()
    assert "bodyrig.recover_cli" not in text
    assert "bodyrig.observation_cli" not in text
    assert "bodyrig.identity_capture_cli" not in text
    assert "bodyrig.external_fitter_cli" not in text
    assert "bodyrig.stash_cli" not in text

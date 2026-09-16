from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "run-photoreal-p0-reference-windows.ps1").read_text(encoding="utf-8")


def test_reference_p0_wrapper_preflights_before_configs_and_stash_runner() -> None:
    preflight = SCRIPT.index("bodyrig.photoreal_reference_vision_preflight")
    config = SCRIPT.index("bodyrig.photoreal_reference_vision_config")
    runner = SCRIPT.index("=== START ISOLATED 16-STAGE P0 ===")
    assert preflight < config < runner


def test_reference_p0_wrapper_is_fail_closed_and_never_reconstructs() -> None:
    assert "Photoreal reference P0 requires an exact clean BodyRig checkout." in SCRIPT
    assert 'Write-Host "Reconstruction:    FALSE"' in SCRIPT
    assert 'Write-Host "Photoreal accept:  FALSE"' in SCRIPT
    assert 'Write-Host "Production:        FALSE"' in SCRIPT
    assert "bodyrig.sith_" not in SCRIPT
    assert "reference-renderer" not in SCRIPT
    assert "Vrm" not in SCRIPT


def test_reference_p0_wrapper_generates_ephemeral_configs_only() -> None:
    assert "bodyrig-photoreal-reference-" in SCRIPT
    assert '$identityConfig = Join-Path $tempRoot "identity-extractor.json"' in SCRIPT
    assert '$frameConfig = Join-Path $tempRoot "frame-analyzer.json"' in SCRIPT
    assert "Remove-Item -LiteralPath $tempRoot -Recurse -Force" in SCRIPT
    assert '"-IdentityExtractorConfig", $identityConfig' in SCRIPT
    assert '"-FrameAnalyzerConfig", $frameConfig' in SCRIPT


def test_reference_p0_wrapper_passes_same_model_root_to_preflight_config_and_runner() -> None:
    assert "--model-root $ModelRoot" in SCRIPT
    assert '"-ModelRoot", $ModelRoot' in SCRIPT
    assert "--distribution $Distribution" in SCRIPT
    assert "--linux-python $LinuxPython" in SCRIPT
    assert "--device $VisionDevice" in SCRIPT


def test_reference_p0_wrapper_runs_p0_in_isolated_pwsh_process() -> None:
    assert '$pwsh = Need-File -Path (Join-Path $PSHOME "pwsh.exe")' in SCRIPT
    assert '"-NoLogo", "-NoProfile", "-File", $runner' in SCRIPT
    assert "& $pwsh @runnerArgs" in SCRIPT
    assert "$exitCode = $LASTEXITCODE" in SCRIPT
    assert "& $runner @runnerArgs" not in SCRIPT
    assert "exit $exitCode" not in SCRIPT


def test_reference_p0_wrapper_never_claims_success_when_preflight_config_or_p0_fail() -> None:
    assert 'if ($preflightExit -ne 0) { throw "Photoreal reference vision preflight failed with exit code $preflightExit." }' in SCRIPT
    assert 'if ($configExit -ne 0) { throw "Photoreal reference vision config generation failed with exit code $configExit." }' in SCRIPT
    assert 'if ($exitCode -eq 2)' in SCRIPT
    assert "was blocked by a fail-closed gate" in SCRIPT
    assert "BodyRig Photoreal reference P0 failed unexpectedly with original child exit code $exitCode" in SCRIPT
    assert "Do not reuse partial outputs as authority" in SCRIPT
    assert "bodyrig.photoreal_p0_crash_receipt_cli" in SCRIPT

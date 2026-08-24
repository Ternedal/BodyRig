from __future__ import annotations

from pathlib import Path


def _wrapper() -> str:
    return (Path(__file__).resolve().parents[1] / "clone-body-from-stash.ps1").read_text(encoding="utf-8")


def _generic_clone() -> str:
    return (Path(__file__).resolve().parents[1] / "clone-body.ps1").read_text(encoding="utf-8")


def test_stash_wrapper_defaults_identity_capture_without_weakening_clone_contract():
    text = _wrapper()

    assert '[string]$IdentityCaptureConfig = ""' in text
    assert '$usingBuiltInIdentityCapture = [string]::IsNullOrWhiteSpace($IdentityCaptureConfig)' in text
    assert '"-m", "bodyrig.identity_capture_preflight"' in text
    assert 'adapter = "opencv-identity-rgba"' in text
    assert 'revision = "1"' in text
    assert 'bodyrig\\bridges\\opencv_identity_capture.py' in text
    assert '"-IdentityCaptureConfig", $IdentityCaptureConfig' in text


def test_stash_wrapper_preserves_custom_identity_capture_escape_hatch():
    text = _wrapper()

    assert 'Resolve-InputFile -Path $IdentityCaptureConfig -Label "Identity capture config"' in text
    assert 'Write-Host "Identity capture: custom config"' in text


def test_stash_wrapper_defaults_to_builtin_sith_fitter_but_generic_clone_stays_strict():
    wrapper = _wrapper()
    generic = _generic_clone()

    assert '[string]$FitterConfig = ""' in wrapper
    assert '$usingBuiltInFitter = [string]::IsNullOrWhiteSpace($FitterConfig)' in wrapper
    assert 'adapter = "sith-smplx-vrm"' in wrapper
    assert 'revision = "1"' in wrapper
    assert '"-m", "bodyrig.sith_fitter_orchestrator"' in wrapper
    assert 'visual_identity = $true' in wrapper
    assert 'textures = $true' in wrapper
    assert 'clothing = $true' in wrapper
    assert 'hair = $false' in wrapper
    assert 'timeout_seconds = 86400' in wrapper
    assert '"-FitterConfig", $FitterConfig' in wrapper

    assert '[Parameter(Mandatory = $true)]\n    [string]$FitterConfig' in generic
    assert '$FitterConfig = Resolve-InputFile -Path $FitterConfig -Label "High-fidelity fitter config"' in generic


def test_builtin_sith_fitter_fails_fast_on_authority_and_model_digest():
    text = _wrapper()

    assert '"-m", "bodyrig.sith_preflight"' in text
    assert '"-m", "bodyrig.sith_model"' in text
    assert 'BODYRIG_SITH_DISTRIBUTION' in text
    assert 'BODYRIG_SITH_REPO' in text
    assert 'BODYRIG_SITH_PYTHON' in text
    assert 'BODYRIG_SITH_OPENPOSE' in text
    assert 'BODYRIG_SITH_DIFFUSION_MODEL' in text
    assert 'BODYRIG_SITH_DIFFUSION_SHA256' in text
    assert '$SithDiffusionModelSha256 = $SithDiffusionModelSha256.ToLowerInvariant()' in text
    assert 'SiTH diffusion model SHA-256 mismatch' in text
    assert '"--seed", [string]$SithSeed' in text

    preflight = text.index('"-m", "bodyrig.sith_preflight"')
    digest = text.index('"-m", "bodyrig.sith_model"')
    discovery = text.index('"-m", "bodyrig.stash_cli", "select"')
    assert preflight < discovery
    assert digest < discovery


def test_production_stash_selection_uses_cli_decode_gate_by_default():
    wrapper = _wrapper()
    cli = (Path(__file__).resolve().parents[1] / "bodyrig" / "stash_cli.py").read_text(encoding="utf-8")

    assert '$Ffmpeg = Resolve-Executable -Value $Ffmpeg -Fallback "ffmpeg" -Label "FFmpeg"' in wrapper
    assert '"-m", "bodyrig.stash_cli", "select"' in wrapper
    assert 'select.add_argument(\n        "--skip-decode-probe"' in cli
    assert 'if not args.skip_decode_probe:' in cli
    assert '_filter_decodable_sources(' in cli
    # Canonical wrapper must not opt out of the decode gate.
    assert '"--skip-decode-probe"' not in wrapper


def test_stash_wrapper_preserves_custom_fitter_escape_hatch():
    text = _wrapper()

    assert 'Resolve-InputFile -Path $FitterConfig -Label "High-fidelity fitter config"' in text
    assert 'Write-Host "High-fidelity fitter: custom config"' in text
    assert 'Write-Host "High-fidelity fitter: built-in sith-smplx-vrm v1' in text


def test_stash_wrapper_derives_smplx_assets_inside_pinned_sith_orchestrator():
    text = _wrapper()

    assert '--smplx-model-dir' not in text
    assert 'BODYRIG_SITH_SMPLX' not in text


def test_stash_wrapper_does_not_copy_build_configs_as_clone_evidence():
    text = _wrapper()

    assert 'Copy-Item -LiteralPath $IdentityCaptureConfig' not in text
    assert 'Copy-Item -LiteralPath $FitterConfig' not in text
    assert 'bodyrig-observation-evidence.json' in text

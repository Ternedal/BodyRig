from __future__ import annotations

from pathlib import Path


def _wrapper() -> str:
    return (Path(__file__).resolve().parents[1] / "clone-body-from-stash.ps1").read_text(encoding="utf-8")


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


def test_stash_wrapper_does_not_copy_identity_capture_config_as_clone_evidence():
    text = _wrapper()

    assert 'Copy-Item -LiteralPath $IdentityCaptureConfig' not in text
    assert 'bodyrig-observation-evidence.json' in text

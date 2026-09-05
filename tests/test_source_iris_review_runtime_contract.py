from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_operator_builds_sidecar_bound_byte_identical_review_runtime() -> None:
    text = (ROOT / "build-source-iris-reviewed-runtime.ps1").read_text(encoding="utf-8")
    assert "Windows-only" in text
    assert "PowerShell 7+" in text
    assert "status --porcelain" in text
    assert "bodyrig.source_iris_review_runtime_cli build" in text
    assert "--bodyrig-revision $head" in text
    assert "--base-runtime-dir $baseRoot" in text
    assert "--iris-candidate-dir $irisRoot" in text
    assert "--source-eye-appearance-dir $sourceRoot" in text
    assert "--reviewed-runtime-dir $OutputDir" in text
    assert "reviewed_vrm_sha256 -ne [string]$result.base_review_vrm_sha256" in text
    assert "$result.runtime_bytes_unchanged -ne $true" in text
    assert "$result.source_eye_pixels_unchanged -ne $true" in text
    assert "$result.iris_identity_isolated -ne $true" in text
    assert "$result.eyes_promotion_eligible -ne $false" in text
    assert "$result.eye_component_authority -ne $false" in text
    assert "$result.production_activation -ne $false" in text
    assert "VRM bytes:          UNCHANGED" in text
    assert "Source eye pixels:  UNCHANGED" in text
    assert "it does not make eyes complete" in text


def test_checkout_race_cleanup_only_removes_new_reviewed_runtime_output() -> None:
    text = (ROOT / "build-source-iris-reviewed-runtime.ps1").read_text(encoding="utf-8")
    assert "Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head" in text
    assert "Remove-Item -LiteralPath $OutputDir -Recurse -Force" in text
    assert "removed only the newly created reviewed-runtime directory" in text
    assert "Remove-Item -LiteralPath $baseRoot" not in text
    assert "Remove-Item -LiteralPath $irisRoot" not in text
    assert "Remove-Item -LiteralPath $sourceRoot" not in text


def test_runtime_module_never_rewrites_eye_pixels_or_grants_eye_authority() -> None:
    text = (ROOT / "bodyrig" / "source_iris_review_runtime.py").read_text(encoding="utf-8")
    assert "shutil.copyfile(base_vrm, output_vrm)" in text
    assert "output_vrm.read_bytes() != base_vrm.read_bytes()" in text
    assert '"runtimeBytesUnchanged": True' in text
    assert '"sourceEyePixelsUnchanged": True' in text
    assert '"embeddedEyeRuntimeStillReviewPending": True' in text
    assert '"irisReviewOverlayApplied": True' in text
    assert '"irisIdentityIsolated": True' in text
    assert '"eyeComponentAuthority": False' in text
    assert '"eyesPromotionEligible": False' in text
    assert '"productionActivation": False' in text
    assert "_write_glb" not in text
    assert "Image.open" not in text

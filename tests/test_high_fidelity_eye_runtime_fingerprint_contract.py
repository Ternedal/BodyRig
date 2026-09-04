from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "bodyrig" / "high_fidelity_eye_runtime_fingerprint.py"
CLI = ROOT / "bodyrig" / "high_fidelity_eye_runtime_fingerprint_cli.py"
WRAPPER = ROOT / "record-high-fidelity-eye-runtime-fingerprint.ps1"


def test_fingerprint_layer_never_rewrites_runtime_or_package() -> None:
    source = MODULE.read_text(encoding="utf-8")

    for forbidden in (
        "_write_glb",
        "zipfile",
        "validate_package",
        "with_component_status",
        "shutil.copyfile",
        '"eyesPromoted": True',
        '"eyeComponentAuthority": True',
        '"packageMutationPerformed": True',
        '"productionActivation": True',
    ):
        assert forbidden not in source

    for required in (
        "semantic_eye_runtime_fingerprint",
        "index-and-buffer-offset-independent-eye-stage-v1",
        "payloadSha256",
        "sourceImageSha256",
        "canonicalEyeBakeSha256",
        "eyeAppearanceReceiptSha256",
        '"eyesPromotionEligibilityVerified": True',
        '"eyeComponentAuthority": False',
        '"packageMutationPerformed": False',
        '"eyesPromoted": False',
        '"productionActivation": False',
    ):
        assert required in source


def test_fingerprint_contract_covers_all_rendered_eye_primitive_roles() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert 'PRIMITIVE_ROLES = ("left_surface", "left_cornea", "right_surface", "right_cornea")' in source
    assert 'ATTRIBUTE_ORDER = ("POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0")' in source
    assert 'SOURCE_MATERIAL_NAME = "BodyRigSourceEyeSurface"' in source
    assert 'CORNEA_MATERIAL_NAME = "BodyRigCorneaReview"' in source
    assert 'SOURCE_IMAGE_NAME = "BodyRigSourceEyeBake"' in source
    assert 'metadata["canonicalEyeBakeSha256"] != source_image_sha' in source


def test_cli_exposes_separate_record_and_verify_modes() -> None:
    source = CLI.read_text(encoding="utf-8")

    assert 'for name in ("record", "verify")' in source
    assert "write_fingerprint" in source
    assert "read_fingerprint" in source
    assert '"index_independent": value["indexIndependent"]' in source
    assert '"buffer_offset_independent": value["bufferOffsetIndependent"]' in source
    assert '"package_mutation_performed": value["packageMutationPerformed"]' in source


def test_windows_operator_is_clean_checkout_bound_and_cleanup_is_receipt_only() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    for required in (
        "PowerShell 7+ is required.",
        "git -C $RepoRoot rev-parse HEAD",
        "git -C $RepoRoot status --porcelain",
        "exact clean BodyRig checkout",
        "high_fidelity_eye_runtime_fingerprint_cli record",
        "--bodyrig-revision $head",
        "$result.index_independent -ne $true",
        "$result.buffer_offset_independent -ne $true",
        "$result.eye_component_authority -ne $false",
        "$result.package_mutation_performed -ne $false",
        "$result.eyes_promoted -ne $false",
        "$result.production_activation -ne $false",
        "Remove-Item -LiteralPath $receiptPath",
        "removed only the newly created fingerprint receipt",
        "rebuild an eye-only runtime and require this exact semantic fingerprint",
    ):
        assert required in source

    assert "Remove-Item -LiteralPath $ReviewedRuntimeDir" not in source
    assert "Remove-Item -LiteralPath $IrisCandidateDir" not in source
    assert "Remove-Item -LiteralPath $SourceEyeAppearanceDir" not in source

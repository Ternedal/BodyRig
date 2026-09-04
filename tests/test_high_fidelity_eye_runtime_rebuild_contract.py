from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bodyrig" / "bridges" / "sith_eye_review_runtime.py"
MODULE = ROOT / "bodyrig" / "high_fidelity_eye_runtime_rebuild.py"
CLI = ROOT / "bodyrig" / "high_fidelity_eye_runtime_rebuild_cli.py"
WRAPPER = ROOT / "build-source-eye-only-review-runtime.ps1"


def test_eye_only_bridge_reuses_exact_eye_math_without_hair_build() -> None:
    source = BRIDGE.read_text(encoding="utf-8")

    for required in (
        "combined._validate_eye_inputs",
        "combined._eye_geometry_runtime",
        "combined._primitive_arrays",
        "combined.SURFACE_SCALE",
        "combined.CORNEA_SCALE",
        '"BodyRigSourceEyeSurface"',
        '"BodyRigCorneaReview"',
        '"BodyRigSourceEyeReviewMesh"',
        '"BodyRigSourceEyeReview"',
        '"sourceHairRuntimeApplied": False',
        '"sourceEyeSurfaceApplied": True',
        '"eyeComponentAuthority": False',
        '"productionActivation": False',
    ):
        assert required in source

    for forbidden in (
        "hair.build(",
        "source-hair-review.vrm",
        '"sourceHairRuntimeApplied": True',
        '"eyeComponentAuthority": True',
        '"productionActivation": True',
    ):
        assert forbidden not in source


def test_rebuild_controller_requires_exact_fingerprint_match_and_never_mutates_package() -> None:
    source = MODULE.read_text(encoding="utf-8")

    for required in (
        "semantic_eye_runtime_fingerprint(vrm_bytes)",
        'rebuilt.get("fingerprintSha256") != source_sha',
        'rebuilt.get("payload") != source_fingerprint.get("fingerprint")',
        '"fingerprintMatch": True',
        '"sourceHairRuntimeImported": False',
        '"eyeOnlyRuntimeVerified": True',
        '"eyeComponentAuthority": False',
        '"packageMutationPerformed": False',
        '"eyesPromoted": False',
        '"productionActivation": False',
        '"BodyRigSourceHairReview"',
    ):
        assert required in source

    for forbidden in (
        "with_component_status",
        "_write_glb",
        '"eyeComponentAuthority": True',
        '"packageMutationPerformed": True',
        '"eyesPromoted": True',
        '"productionActivation": True',
    ):
        assert forbidden not in source


def test_rebuild_cli_has_prepare_finalize_verify_separation() -> None:
    source = CLI.read_text(encoding="utf-8")

    for required in (
        'sub.add_parser("prepare")',
        'sub.add_parser("finalize")',
        'sub.add_parser("verify")',
        "prepare_rebuild",
        "finalize_rebuild",
        "read_rebuild",
        '"fingerprint_match": value["fingerprintMatch"]',
        '"source_hair_runtime_imported": value["sourceHairRuntimeImported"]',
        '"package_mutation_performed": value["packageMutationPerformed"]',
    ):
        assert required in source


def test_windows_rebuild_operator_is_clean_checkout_bound_and_staged() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    for required in (
        "PowerShell 7+ is required.",
        "git -C $RepoRoot rev-parse HEAD",
        "git -C $RepoRoot status --porcelain",
        "exact clean BodyRig checkout",
        "high_fidelity_eye_runtime_rebuild_cli\", \"prepare",
        "sith_eye_review_runtime.py",
        "high_fidelity_eye_runtime_rebuild_cli\", \"finalize",
        "$final.fingerprint_match -ne $true",
        "$final.source_hair_runtime_imported -ne $false",
        "$final.eye_component_authority -ne $false",
        "$final.package_mutation_performed -ne $false",
        "$final.eyes_promoted -ne $false",
        "$final.production_activation -ne $false",
        "Move-Item -LiteralPath $partial -Destination $OutputDir",
        "Remove-Item -LiteralPath $partial -Recurse -Force",
        "a separate package materializer may consume only this fingerprint-matched eye-only runtime",
    ):
        assert required in source

    assert "Move-Item -LiteralPath $PackagePath" not in source
    assert "Remove-Item -LiteralPath $PackagePath" not in source

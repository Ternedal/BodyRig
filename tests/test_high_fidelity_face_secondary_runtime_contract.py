from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "bodyrig" / "high_fidelity_face_secondary_runtime.py"
CLI = ROOT / "bodyrig" / "high_fidelity_face_secondary_runtime_cli.py"
WRAPPER = ROOT / "build-high-fidelity-face-secondary-review-runtime.ps1"


def test_runtime_module_is_review_only_and_keeps_all_five_components_partial() -> None:
    source = MODULE.read_text(encoding="utf-8")
    for required in (
        '"eyebrow_appearance": "partial"',
        '"lip_boundary": "partial"',
        '"mouth_interior": "partial"',
        '"teeth": "partial"',
        '"eyelashes": "partial"',
        '"genericSecondaryAnatomy": True',
        '"sourceDerivedIdentitySynthesis": False',
        '"generativeIdentitySynthesis": False',
        '"faceSecondaryComponentAuthority": False',
        '"packageMutationPerformed": False',
        '"productionActivation": False',
        '"licensed-smplx-joint-topology-v1"',
    ):
        assert required in source
    assert '"faceSecondaryComponentAuthority": True' not in source
    assert '"productionActivation": True' not in source


def test_cli_exposes_build_and_verify_only() -> None:
    source = CLI.read_text(encoding="utf-8")
    assert 'sub.add_parser("build")' in source
    assert 'sub.add_parser("verify")' in source
    assert "build_runtime" in source
    assert "read_runtime" in source


def test_windows_wrapper_is_clean_checkout_bound_and_cleans_only_new_output() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    for required in (
        "PowerShell 7+ is required.",
        "git -C $RepoRoot rev-parse HEAD",
        "git -C $RepoRoot status --porcelain",
        "exact clean BodyRig checkout",
        "high_fidelity_face_secondary_runtime_cli build",
        "$result.face_secondary_component_authority -ne $false",
        "$result.package_mutation_performed -ne $false",
        "$result.production_activation -ne $false",
        "Remove-Item -LiteralPath $OutputDir -Recurse -Force",
        "Mouth interior:   GENERIC SECONDARY ANATOMY / REVIEW REQUIRED",
        "Eyelashes:        SMPL-X ANCHORED / REVIEW REQUIRED",
    ):
        assert required in source
    assert "Remove-Item -LiteralPath $PackagePath" not in source

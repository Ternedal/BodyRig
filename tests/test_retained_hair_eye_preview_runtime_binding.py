from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-retained-hair-eye-preview.ps1"


def test_retained_preview_passes_exact_identity_workspace_to_runtime_builder() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "$runtimeArgs.CandidateWorkspace = $IdentityWorkspace" in text
    assert "$runtimeArgs.PackagePath = $PackagePath" in text
    assert "$runtimeArgs.HairCandidateDir = $hairDir" in text
    assert "$runtimeArgs.EyeGeometryDir = $eyeDir" in text
    assert "$runtimeArgs.EyeAppearanceDir = $eyeAppearanceDir" in text

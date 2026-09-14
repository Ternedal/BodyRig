from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-retained-hair-eye-preview.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_retained_preview_reuses_exact_reconstruction_without_rerun() -> None:
    text = source()

    assert '$stage = Need-Directory -Path (Join-Path $IdentityWorkspace "sith-input-v1")' in text
    for exact_input in (
        'Join-Path $stage "reconstruction.json"',
        'Join-Path $stage "reconstruction-authority.json"',
        'Join-Path $stage "meshes\\000_reco.obj"',
        'Join-Path $stage "smplx\\000_smplx.obj"',
        'Join-Path $stage "smplx\\000_fit.json"',
    ):
        assert exact_input in text

    assert "reconstruction_rerun = $false" in text
    assert "SiTH reconstruction rerun: FALSE" in text
    assert "clone-body-from-stash" not in text
    assert "run-profiled-fidelity-convergence" not in text
    assert "sith_reconstruct" not in text
    assert "reconstruction_rerun = $true" not in text


def test_retained_preview_builds_source_hair_eye_runtime_and_physical_preview() -> None:
    text = source()

    for operator in (
        "extract-retained-hair.ps1",
        "extract-eye-components.ps1",
        "extract-eye-appearance.ps1",
        "build-source-hair-eye-review-runtime.ps1",
        "run-source-hair-eye-windows-preview.ps1",
    ):
        assert operator in text

    assert "$runtimeReceipt.sourceHairRuntimeApplied -ne $true" in text
    assert "$runtimeReceipt.sourceEyeSurfaceApplied -ne $true" in text
    assert '[string]$runtimeReceipt.cornealMaterialStatus -ne "runtime-applied"' in text
    assert '[string]$runtimeReceipt.irisAppearanceStatus -ne "review-pending"' in text
    assert '[string]$runtimeReceipt.eyelashStatus -ne "missing"' in text
    assert "$comparison.hair_deformation_machine_pass -ne $true" in text


def test_retained_preview_fails_closed_if_any_input_authority_bytes_change() -> None:
    text = source()

    for before_hash in (
        "$packageShaBefore = Sha256 $PackagePath",
        "$reconstructionShaBefore = Sha256 $reconstructionPath",
        "$reconstructionAuthorityShaBefore = Sha256 $reconstructionAuthorityPath",
        "$sourceMeshShaBefore = Sha256 $sourceMeshPath",
        "$donorShaBefore = Sha256 $donorObj",
        "$fitShaBefore = Sha256 $fitParams",
    ):
        assert before_hash in text

    assert "Retained reconstruction/package authority changed during hair+eye preview continuation." in text
    assert "Move-Item -LiteralPath $attempt -Destination $OutputRoot" in text
    assert "if (-not $committed" in text


def test_retained_preview_never_claims_full_fidelity_or_release_authority() -> None:
    text = source()

    assert 'format = "bodyrig-retained-hair-eye-preview"' in text
    assert "full_fidelity_component_complete = $false" in text
    assert "comparison_only = $true" in text
    assert "human_review_required = $true" in text
    assert "production_activation = $false" in text
    assert 'semantics = "retained-reconstruction-hair-eye-physical-preview-not-full-fidelity-acceptance"' in text
    assert 'Write-Host "Full fidelity:   FALSE - inspect this preview before further composition"' in text

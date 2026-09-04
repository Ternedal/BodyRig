from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "run-subject-component-discovery.ps1"


def test_subject_component_discovery_is_bound_to_exact_anatomy_candidate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    required = (
        'Subject anatomy physical gate was produced by a different BodyRig revision.',
        '$summary.candidate_gross_anatomy_pass -ne $true',
        '[string]$summary.package_sha256 -ne $packageSha',
        '[string]$packageResult.package_sha256 -ne $packageSha',
        '[string]$workspaceReceipt.candidateReconstructionSha256 -ne $candidateReconstructionSha',
        '[string]$workspaceReceipt.candidateReconstructionAuthoritySha256 -ne $candidateReconstructionAuthoritySha',
        '[string]$packageResult.candidate_reconstruction_sha256 -ne $candidateReconstructionSha',
        '[string]$candidateReconstructionAuthority.reconstruction_sha256 -ne $candidateReconstructionSha',
        '[string]$refit.derivedSmplxObjSha256 -ne $donorSha',
        '[string]$candidateAudit.donorObjSha256 -ne $donorSha',
        '[string]$hair.donorObjSha256 -ne $donorSha',
        '[string]$hair.sourceReconstructionSha256 -ne $candidateReconstructionSha',
        '[string]$eyes.donorObjSha256 -ne $donorSha',
        '[string]$eyeAppearance.donorObjSha256 -ne $donorSha',
        '[string]$eyeAppearance.sourceReconstructionSha256 -ne $candidateReconstructionSha',
        '$summary.reconstruction_rerun -ne $false',
        '$summary.production_activation -ne $false',
        'candidate_reconstruction_authority_sha256 = $candidateReconstructionAuthoritySha',
        'high_fidelity_ready = $false',
        'production_activation = $false',
    )
    for marker in required:
        assert marker in source


def test_source_appearance_discovery_uses_gate_candidate_workspace_not_parent_workspace() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '$candidateWorkspace = Need-Directory -Path (Join-Path $packageDir "candidate-workspace")' in source
    assert 'must not fall back to the parent retained identity workspace' in source
    assert '$hairArgs.IdentityWorkspace = $candidateWorkspace' in source
    assert '$eyeAppearanceArgs.IdentityWorkspace = $candidateWorkspace' in source
    assert '$hairArgs.IdentityWorkspace = $IdentityWorkspace' not in source
    assert '$eyeAppearanceArgs.IdentityWorkspace = $IdentityWorkspace' not in source

    eye_start = source.index('$eyeArgs = $common.Clone()')
    eye_end = source.index('Invoke-Checked -Script $eyeScript', eye_start)
    eye_geometry_block = source[eye_start:eye_end]
    assert 'IdentityWorkspace' not in eye_geometry_block
    assert '$eyeArgs.DonorObj = $donorObj' in eye_geometry_block
    assert '$eyeArgs.TargetFamily = $targetFamily' in eye_geometry_block


def test_candidate_workspace_authority_is_revalidated_before_any_component_extraction() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    authority_check = source.index('Candidate reconstruction authority does not authorize the exact anatomy candidate workspace.')
    hair_call = source.index('Invoke-Checked -Script $hairScript')
    eye_call = source.index('Invoke-Checked -Script $eyeScript')
    appearance_call = source.index('Invoke-Checked -Script $eyeAppearanceScript')

    assert authority_check < hair_call < eye_call < appearance_call
    assert 'candidate_package_sha256 = $packageSha' in source
    assert 'candidate_workspace = $candidateWorkspace' in source
    assert 'candidate_reconstruction_sha256 = $candidateReconstructionSha' in source


def test_subject_component_discovery_keeps_incomplete_eye_truth_explicit() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '$eyes.sourceDerivedIrisAppearance -ne $false' in source
    assert '$eyeAppearance.sourceDerivedEyeSurfaceAppearance -ne $true' in source
    assert '$eyeAppearance.irisIdentityIsolated -ne $false' in source
    assert '[string]$eyeAppearance.irisAppearanceStatus -ne "review-pending"' in source
    assert 'source_derived_eye_surface_appearance = $true' in source
    assert 'source_derived_iris_appearance = $false' in source
    assert 'iris_identity_isolated = $false' in source
    assert 'Iris identity:  REVIEW-PENDING (not isolated)' in source
    assert 'Human review:   REQUIRED' in source


def test_subject_component_discovery_builds_visible_hair_eye_runtime_after_candidates() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    hair_call = source.index('Invoke-Checked -Script $hairScript')
    eye_call = source.index('Invoke-Checked -Script $eyeScript')
    appearance_call = source.index('Invoke-Checked -Script $eyeAppearanceScript')
    runtime_call = source.index('Invoke-Checked -Script $runtimeScript')

    assert hair_call < eye_call < appearance_call < runtime_call
    assert '$runtimeScript = Need-File -Path (Join-Path $repoRoot "build-source-hair-eye-review-runtime.ps1")' in source
    assert '$runtimeArgs.PackagePath = $packagePath' in source
    assert '$runtimeArgs.HairCandidateDir = $hairDir' in source
    assert '$runtimeArgs.EyeGeometryDir = $eyesDir' in source
    assert '$runtimeArgs.EyeAppearanceDir = $eyeAppearanceDir' in source
    assert '$runtimeArgs.CandidateWorkspace = $candidateWorkspace' in source
    assert 'source-hair-eye-review.vrm' in source
    assert '[string]$runtime.runtimeIntegrationStatus -ne "hair-and-eyes-review-artifact-ready"' in source
    assert '$runtime.sourceHairRuntimeApplied -ne $true' in source
    assert '$runtime.sourceEyeSurfaceApplied -ne $true' in source
    assert '[string]$runtime.cornealMaterialStatus -ne "runtime-applied"' in source
    assert 'review_vrm_sha256 = (Sha256 $runtimeVrmPath)' in source
    assert 'VISIBLE REVIEW RUNTIME READY' in source

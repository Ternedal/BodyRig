param(
    [Parameter(Mandatory = $true)][string]$AnatomyRunRoot,
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$InstallRoot = "",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Read-Json {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
    catch { throw "$Label is unreadable JSON: $Path" }
}
function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Invoke-Checked {
    param([Parameter(Mandatory = $true)][string]$Script,[Parameter(Mandatory = $true)][hashtable]$Arguments,[Parameter(Mandatory = $true)][string]$Label)
    & $Script @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE" }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig subject component discovery is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Subject component discovery requires an exact clean BodyRig checkout." }

$AnatomyRunRoot = Need-Directory -Path $AnatomyRunRoot -Label "Subject anatomy physical run"
$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Retained identity workspace"
$summaryPath = Need-File -Path (Join-Path $AnatomyRunRoot "subject-anatomy-physical-gate.json") -Label "Subject anatomy physical gate summary"
$summary = Read-Json -Path $summaryPath -Label "Subject anatomy physical gate summary"

if ([string]$summary.format -ne "bodyrig-subject-anatomy-physical-gate" -or [int]$summary.version -ne 1) {
    throw "Subject anatomy physical gate summary has an unsupported contract."
}
if ([string]$summary.bodyrig_revision -ne $head) {
    throw "Subject anatomy physical gate was produced by a different BodyRig revision."
}
$targetFamily = ([string]$summary.target_model_family).Trim().ToLowerInvariant()
if ($targetFamily -notin @("female", "male", "neutral")) { throw "Subject anatomy target family is invalid." }
if ($summary.candidate_gross_anatomy_pass -ne $true -or
    $summary.bodyprint_adjustment -ne $false -or
    $summary.reconstruction_rerun -ne $false -or
    $summary.comparison_only -ne $true -or
    $summary.human_review_required -ne $true -or
    $summary.production_activation -ne $false) {
    throw "Subject anatomy physical gate is not a valid comparison-only machine PASS."
}

$refitEvidencePath = Need-File -Path ([string]$summary.subject_refit_evidence) -Label "Subject anatomy refit evidence"
$candidateAuditPath = Need-File -Path ([string]$summary.candidate_anatomy_evidence) -Label "Candidate anatomy audit evidence"
$donorObj = Need-File -Path (Join-Path $AnatomyRunRoot "subject-refit\subject_smplx.obj") -Label "Exact subject donor OBJ"
$refit = Read-Json -Path $refitEvidencePath -Label "Subject anatomy refit evidence"
$candidateAudit = Read-Json -Path $candidateAuditPath -Label "Candidate anatomy audit evidence"
$donorSha = Sha256 $donorObj

if ([string]$refit.format -ne "bodyrig-subject-anatomy-refit" -or [int]$refit.version -ne 1 -or
    [string]$refit.targetModelFamily -ne $targetFamily -or
    [string]$refit.derivedSmplxObjSha256 -ne $donorSha -or
    $refit.retainedReconstructionModified -ne $false -or
    $refit.reconstructionRerun -ne $false -or
    $refit.generativeGeometry -ne $false -or
    $refit.comparisonOnly -ne $true -or
    $refit.humanReviewRequired -ne $true -or
    $refit.productionReady -ne $false) {
    throw "Subject anatomy refit evidence does not bind the exact comparison donor."
}
if ([string]$candidateAudit.format -ne "bodyrig-anatomy-geometry-audit" -or [int]$candidateAudit.version -ne 1 -or
    [string]$candidateAudit.donorObjSha256 -ne $donorSha -or
    $candidateAudit.grossAnatomyPass -ne $true -or
    $candidateAudit.humanReviewRequired -ne $true) {
    throw "Candidate anatomy audit does not authorize component discovery from the exact donor."
}

$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $OutputRoot) { throw "Subject component discovery output already exists: $OutputRoot" }
New-Item -ItemType Directory -Path $OutputRoot | Out-Null
$hairDir = Join-Path $OutputRoot "hair"
$eyesDir = Join-Path $OutputRoot "eyes"
$receiptPath = Join-Path $OutputRoot "subject-component-discovery.json"

$hairScript = Need-File -Path (Join-Path $repoRoot "extract-retained-hair.ps1") -Label "Source hair discovery operator"
$eyeScript = Need-File -Path (Join-Path $repoRoot "extract-eye-components.ps1") -Label "Eye component discovery operator"
$common = @{
    Distribution = $Distribution
    InstallRoot = $InstallRoot
    WslExe = $WslExe
}

Write-Host "BodyRig subject component discovery"
Write-Host "Revision:       $head"
Write-Host "Target family:  $targetFamily"
Write-Host "Donor SHA:      $donorSha"
Write-Host "Anatomy gate:   MACHINE PASS"
Write-Host "Production:     FALSE"
Write-Host ""

$hairArgs = $common.Clone()
$hairArgs.IdentityWorkspace = $IdentityWorkspace
$hairArgs.DonorObj = $donorObj
$hairArgs.OutputDir = $hairDir
Invoke-Checked -Script $hairScript -Arguments $hairArgs -Label "Source-derived hair discovery"

$eyeArgs = $common.Clone()
$eyeArgs.DonorObj = $donorObj
$eyeArgs.TargetFamily = $targetFamily
$eyeArgs.OutputDir = $eyesDir
Invoke-Checked -Script $eyeScript -Arguments $eyeArgs -Label "Explicit eye geometry discovery"

$hairEvidencePath = Need-File -Path (Join-Path $hairDir "source-hair-candidate.json") -Label "Hair candidate evidence"
$eyeEvidencePath = Need-File -Path (Join-Path $eyesDir "eye-component-candidate.json") -Label "Eye candidate evidence"
$hair = Read-Json -Path $hairEvidencePath -Label "Hair candidate evidence"
$eyes = Read-Json -Path $eyeEvidencePath -Label "Eye candidate evidence"

if ([string]$hair.format -ne "bodyrig-source-hair-candidate" -or [int]$hair.version -ne 1 -or
    [string]$hair.donorObjSha256 -ne $donorSha -or
    $hair.sourceDerived -ne $true -or $hair.generativeGeometry -ne $false -or
    $hair.bodyTopologyModified -ne $false -or $hair.comparisonOnly -ne $true -or
    $hair.humanReviewRequired -ne $true -or $hair.productionReady -ne $false) {
    throw "Hair discovery evidence is not bound to the exact subject donor/authority boundary."
}
if ([string]$eyes.format -ne "bodyrig-eye-component-candidate" -or [int]$eyes.version -ne 1 -or
    [string]$eyes.donorObjSha256 -ne $donorSha -or
    [string]$eyes.targetModelFamily -ne $targetFamily -or
    $eyes.explicitEyeGeometry -ne $true -or $eyes.sourceDerivedIrisAppearance -ne $false -or
    [string]$eyes.componentStatus -ne "partial" -or $eyes.bodyTopologyModified -ne $false -or
    $eyes.generativeIdentitySynthesis -ne $false -or $eyes.comparisonOnly -ne $true -or
    $eyes.humanReviewRequired -ne $true -or $eyes.productionReady -ne $false) {
    throw "Eye discovery evidence is not bound to the exact subject donor/authority boundary."
}

$result = [ordered]@{
    format = "bodyrig-subject-component-discovery"
    version = 1
    bodyrig_revision = $head
    target_model_family = $targetFamily
    donor_obj = $donorObj
    donor_obj_sha256 = $donorSha
    anatomy_gate_summary_sha256 = (Sha256 $summaryPath)
    subject_refit_evidence_sha256 = (Sha256 $refitEvidencePath)
    candidate_anatomy_evidence_sha256 = (Sha256 $candidateAuditPath)
    hair = [ordered]@{
        status = "candidate"
        evidence = $hairEvidencePath
        evidence_sha256 = (Sha256 $hairEvidencePath)
        selected_face_count = [int]$hair.selectedFaceCount
        source_derived = $true
        human_review_required = $true
    }
    eyes = [ordered]@{
        status = "partial"
        evidence = $eyeEvidencePath
        evidence_sha256 = (Sha256 $eyeEvidencePath)
        left_face_count = [int]$eyes.leftEyeFaceCount
        right_face_count = [int]$eyes.rightEyeFaceCount
        explicit_geometry = $true
        source_derived_iris_appearance = $false
        corneal_material_status = [string]$eyes.cornealMaterialStatus
        eyelash_status = [string]$eyes.eyelashStatus
        human_review_required = $true
    }
    body_topology_modified = $false
    reconstruction_rerun = $false
    generative_identity_synthesis = $false
    comparison_only = $true
    human_review_required = $true
    high_fidelity_ready = $false
    production_activation = $false
}
$result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $receiptPath -Encoding UTF8

Write-Host ""
Write-Host "BodyRig subject component discovery: CANDIDATES READY"
Write-Host "Hair faces:     $([int]$hair.selectedFaceCount)"
Write-Host "Eye faces L/R:  $([int]$eyes.leftEyeFaceCount) / $([int]$eyes.rightEyeFaceCount)"
Write-Host "Iris:           MISSING"
Write-Host "Cornea:         $([string]$eyes.cornealMaterialStatus)"
Write-Host "Eyelashes:      $([string]$eyes.eyelashStatus)"
Write-Host "Human review:   REQUIRED"
Write-Host "High fidelity:  FALSE"
Write-Host "Production:     FALSE"
exit 0

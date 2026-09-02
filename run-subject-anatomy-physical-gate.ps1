param(
    [Parameter(Mandatory = $true)][string]$BaselineCloneOutput,
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][ValidateSet("female", "male", "neutral")][string]$TargetFamily,
    [Parameter(Mandatory = $true)][string]$RunRoot,
    [ValidatePattern('^$|^[a-z0-9æøå_-]{1,160}$')][string]$BodyId = "",
    [Parameter(Mandatory = $true)][ValidateLength(1, 160)][string]$Name,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$InstallRoot = "",
    [string]$WslExe = "wsl.exe",
    [string]$BodyRigPython = "",
    [string]$UnityExe = "",
    [switch]$SkipRendererBuild
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
function Invoke-GateScript {
    param(
        [Parameter(Mandatory = $true)][string]$Script,
        [Parameter(Mandatory = $true)][hashtable]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label,
        [int[]]$AllowedExitCodes = @(0)
    )
    & $Script @Arguments
    $code = $LASTEXITCODE
    if ($code -notin $AllowedExitCodes) { throw "$Label failed with exit code $code" }
    return $code
}
function Write-Summary {
    param([Parameter(Mandatory = $true)]$Value,[Parameter(Mandatory = $true)][string]$Path)
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig subject anatomy physical gate is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Subject anatomy physical gate requires an exact clean BodyRig checkout." }

$BaselineCloneOutput = Need-Directory -Path $BaselineCloneOutput -Label "Baseline clone output"
$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Retained identity workspace"
$RunRoot = [IO.Path]::GetFullPath($RunRoot)
if (Test-Path -LiteralPath $RunRoot) { throw "Subject anatomy physical run root already exists: $RunRoot" }
New-Item -ItemType Directory -Path $RunRoot | Out-Null

$familyScript = Need-File -Path (Join-Path $repoRoot "audit-retained-smplx-family.ps1") -Label "SMPL-X family audit operator"
$baselineAuditScript = Need-File -Path (Join-Path $repoRoot "audit-retained-anatomy.ps1") -Label "Retained anatomy audit operator"
$refitScript = Need-File -Path (Join-Path $repoRoot "refit-subject-anatomy.ps1") -Label "Subject anatomy refit operator"
$candidateAuditScript = Need-File -Path (Join-Path $repoRoot "audit-anatomy-candidate.ps1") -Label "Candidate anatomy audit operator"
$buildScript = Need-File -Path (Join-Path $repoRoot "build-subject-anatomy-candidate.ps1") -Label "Subject anatomy package builder"
$renderScript = Need-File -Path (Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1") -Label "Canonical Windows comparison renderer"

$familyEvidence = Join-Path $RunRoot "retained-smplx-family.json"
$baselineEvidence = Join-Path $RunRoot "retained-anatomy.json"
$refitDir = Join-Path $RunRoot "subject-refit"
$candidateEvidence = Join-Path $RunRoot "candidate-anatomy.json"
$packageDir = Join-Path $RunRoot "candidate-package"
$renderDir = Join-Path $RunRoot "comparison-render"
$summaryPath = Join-Path $RunRoot "subject-anatomy-physical-gate.json"

$commonWsl = @{
    IdentityWorkspace = $IdentityWorkspace
    Distribution = $Distribution
    InstallRoot = $InstallRoot
    WslExe = $WslExe
}

Write-Host "BodyRig subject anatomy physical gate"
Write-Host "Revision:      $head"
Write-Host "Target family: $TargetFamily"
Write-Host "Run root:      $RunRoot"
Write-Host "Alias:         $(if ([string]::IsNullOrWhiteSpace($BodyId)) { 'portable identity authority' } else { $BodyId })"
Write-Host "SiTH rerun:    FALSE"
Write-Host "Production:    FALSE"
Write-Host ""

$familyArgs = $commonWsl.Clone()
$familyArgs.OutputFile = $familyEvidence
[void](Invoke-GateScript -Script $familyScript -Arguments $familyArgs -Label "Retained SMPL-X family audit")

$baselineArgs = $commonWsl.Clone()
$baselineArgs.OutputFile = $baselineEvidence
$baselineCode = Invoke-GateScript -Script $baselineAuditScript -Arguments $baselineArgs -Label "Retained anatomy audit" -AllowedExitCodes @(0, 2)

$refitArgs = $commonWsl.Clone()
$refitArgs.Remove("OutputFile") | Out-Null
$refitArgs.TargetFamily = $TargetFamily
$refitArgs.OutputDir = $refitDir
$refitCode = Invoke-GateScript -Script $refitScript -Arguments $refitArgs -Label "Subject anatomy refit" -AllowedExitCodes @(0, 2)
if ($refitCode -eq 2) {
    Write-Summary -Path $summaryPath -Value ([ordered]@{
        format = "bodyrig-subject-anatomy-physical-gate"
        version = 1
        bodyrig_revision = $head
        target_model_family = $TargetFamily
        retained_family_evidence = $familyEvidence
        retained_anatomy_evidence = $baselineEvidence
        baseline_gross_mismatch = ($baselineCode -eq 2)
        subject_refit = "regressed"
        candidate_anatomy = "not-run"
        package_built = $false
        render_run = $false
        reconstruction_rerun = $false
        human_review_required = $true
        production_activation = $false
    })
    Write-Host "BodyRig subject anatomy physical gate: REFIT REGRESSED; evidence preserved"
    exit 2
}

$candidateObj = Need-File -Path (Join-Path $refitDir "subject_smplx.obj") -Label "Derived subject SMPL-X OBJ"
$candidateArgs = $commonWsl.Clone()
$candidateArgs.CandidateDonorObj = $candidateObj
$candidateArgs.OutputFile = $candidateEvidence
$candidateCode = Invoke-GateScript -Script $candidateAuditScript -Arguments $candidateArgs -Label "Candidate anatomy audit" -AllowedExitCodes @(0, 2)
if ($candidateCode -eq 2) {
    Write-Summary -Path $summaryPath -Value ([ordered]@{
        format = "bodyrig-subject-anatomy-physical-gate"
        version = 1
        bodyrig_revision = $head
        target_model_family = $TargetFamily
        retained_family_evidence = $familyEvidence
        retained_anatomy_evidence = $baselineEvidence
        baseline_gross_mismatch = ($baselineCode -eq 2)
        subject_refit = "non-regressed"
        candidate_anatomy = "gross-mismatch"
        candidate_anatomy_evidence = $candidateEvidence
        package_built = $false
        render_run = $false
        reconstruction_rerun = $false
        human_review_required = $true
        production_activation = $false
    })
    Write-Host "BodyRig subject anatomy physical gate: CANDIDATE GROSS MISMATCH; no appearance package built"
    exit 2
}

$buildArgs = @{
    BaselineCloneOutput = $BaselineCloneOutput
    IdentityWorkspace = $IdentityWorkspace
    SubjectRefitDir = $refitDir
    OutputDir = $packageDir
    Name = $Name
}
if (-not [string]::IsNullOrWhiteSpace($BodyId)) { $buildArgs.BodyId = $BodyId }
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $buildArgs.BodyRigPython = $BodyRigPython }
[void](Invoke-GateScript -Script $buildScript -Arguments $buildArgs -Label "Subject anatomy package build")

$packageResultPath = Need-File -Path (Join-Path $packageDir "subject-anatomy-candidate-result.json") -Label "Subject anatomy package result"
try { $packageResult = Get-Content -LiteralPath $packageResultPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Subject anatomy package result is unreadable." }
$packagePath = Need-File -Path (Join-Path $packageDir ([string]$packageResult.package)) -Label "Subject anatomy comparison package"

$renderArgs = @{
    PackagePath = $packagePath
    OutputDir = $renderDir
}
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $renderArgs.BodyRigPython = $BodyRigPython }
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $renderArgs.UnityExe = $UnityExe }
if ($SkipRendererBuild) { $renderArgs.SkipBuild = $true }
[void](Invoke-GateScript -Script $renderScript -Arguments $renderArgs -Label "Canonical Windows comparison render")

try { $family = Get-Content -LiteralPath $familyEvidence -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Retained family evidence became unreadable." }
try { $baseline = Get-Content -LiteralPath $baselineEvidence -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Retained anatomy evidence became unreadable." }
try { $candidate = Get-Content -LiteralPath $candidateEvidence -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Candidate anatomy evidence became unreadable." }

$summary = [ordered]@{
    format = "bodyrig-subject-anatomy-physical-gate"
    version = 1
    bodyrig_revision = $head
    target_model_family = $TargetFamily
    retained_model_family = [string]$family.authorityModelFamily
    requested_alias = [string]$packageResult.requested_alias
    retained_family_evidence = $familyEvidence
    retained_anatomy_evidence = $baselineEvidence
    retained_gross_anatomy_pass = [bool]$baseline.grossAnatomyPass
    subject_refit_evidence = (Join-Path $refitDir "subject-anatomy-refit.json")
    candidate_anatomy_evidence = $candidateEvidence
    candidate_gross_anatomy_pass = [bool]$candidate.grossAnatomyPass
    package = $packagePath
    package_sha256 = [string]$packageResult.package_sha256
    canonical_body_id = [string]$packageResult.canonical_body_id
    comparison_render = $renderDir
    snapshots = (Join-Path $renderDir "snapshots")
    bodyprint_adjustment = $false
    reconstruction_rerun = $false
    comparison_only = $true
    human_review_required = $true
    production_activation = $false
}
Write-Summary -Path $summaryPath -Value $summary

Write-Host ""
Write-Host "BodyRig subject anatomy physical gate: MACHINE PASS"
Write-Host "Retained family: $([string]$family.authorityModelFamily)"
Write-Host "Target family:   $TargetFamily"
Write-Host "Alias:           $([string]$packageResult.requested_alias)"
Write-Host "Baseline gross:  $([bool]$baseline.grossAnatomyPass)"
Write-Host "Candidate gross: $([bool]$candidate.grossAnatomyPass)"
Write-Host "Package SHA:     $([string]$packageResult.package_sha256)"
Write-Host "Snapshots:       $(Join-Path $renderDir 'snapshots')"
Write-Host "Human review:    REQUIRED"
Write-Host "Production:      FALSE"
Write-Host "SiTH rerun:      FALSE"
exit 0

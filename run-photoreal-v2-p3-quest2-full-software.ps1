param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$DistillationPlan,
    [string]$P2Root = "",
    [string]$WorkRoot = "",
    [string]$CanonicalUvTemplate = "",
    [string]$WindowsPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-WindowsPython {
    param([string]$Requested,[string]$RepoRoot)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return Need-File -Path $Requested -Label "Windows Python"
    }
    $venv = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) {
        return (Resolve-Path -LiteralPath $venv).Path
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Windows Python not found. Pass -WindowsPython explicitly."
    }
    return $command.Source
}

function Resolve-PowerShellHost {
    $name = if ($PSVersionTable.PSEdition -eq "Core") {
        "pwsh.exe"
    } else {
        "powershell.exe"
    }
    $candidate = Join-Path $PSHOME $name
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Could not resolve an isolated PowerShell host."
    }
    return $command.Source
}

function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Run-ChildStage {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$PowerShellHost,
        [Parameter(Mandatory = $true)][string]$Script,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    Write-Host ""
    Write-Host "=== $Label ==="
    & $PowerShellHost -NoProfile -File $Script @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Quest2 full software pipeline requires an exact clean BodyRig checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "BodyRig HEAD is invalid."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$DistillationPlan = Need-File -Path $DistillationPlan -Label "P3 distillation plan"
$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot
$powerShellHost = Resolve-PowerShellHost

if ([string]::IsNullOrWhiteSpace($WorkRoot)) {
    $WorkRoot = Join-Path (Split-Path -Parent $DistillationPlan) "quest2-full-software"
} else {
    $WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot)
}
if (Test-Path -LiteralPath $WorkRoot) {
    throw "Quest2 full software work root already exists: $WorkRoot"
}
New-Item -ItemType Directory -Path $WorkRoot | Out-Null
$WorkRoot = Need-Directory -Path $WorkRoot -Label "Quest2 full software work root"

$candidateRoot = Join-Path $WorkRoot "candidate"
$continuationRoot = Join-Path $WorkRoot "continuation"
$summaryPath = Join-Path $WorkRoot "p3-quest2-full-software.json"

$candidateScript = Need-File -Path (Join-Path $repoRoot "run-photoreal-v2-p3-quest2-refined-candidate.ps1") -Label "Refined Quest2 candidate operator"
$continuationScript = Need-File -Path (Join-Path $repoRoot "run-photoreal-v2-p3-quest2-modular-continuation.ps1") -Label "Quest2 modular continuation operator"

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 FULL SOFTWARE PIPELINE"
Write-Host "Revision:              $head"
Write-Host "Teacher work root:     $TeacherWorkRoot"
Write-Host "P3 plan:               $DistillationPlan"
Write-Host "Work root:             $WorkRoot"
Write-Host "Teacher authority:     REFINED ExAvatar"
Write-Host "Stages:                candidate -> eyes -> hair -> fidelity -> final -> review plan"
Write-Host "Physical PASS/FAIL:    NOT RUN"
Write-Host "Production activation: FALSE"
Write-Host "============================================================"

$candidateArgs = @(
    "-TeacherWorkRoot", $TeacherWorkRoot,
    "-DistillationPlan", $DistillationPlan,
    "-CandidateWorkspace", $candidateRoot,
    "-WindowsPython", $python
)
if (-not [string]::IsNullOrWhiteSpace($P2Root)) {
    $candidateArgs += @("-P2Root", [System.IO.Path]::GetFullPath($P2Root))
}
if (-not [string]::IsNullOrWhiteSpace($CanonicalUvTemplate)) {
    $candidateArgs += @("-CanonicalUvTemplate", $CanonicalUvTemplate)
}
Run-ChildStage -Label "Refined ExAvatar Quest2 candidate" -PowerShellHost $powerShellHost -Script $candidateScript -Arguments $candidateArgs

$candidateReceipt = Need-File -Path (Join-Path $candidateRoot "p3-quest2-student-candidate-receipt.json") -Label "Refined Quest2 candidate receipt"
$candidateManifest = Need-File -Path (Join-Path $candidateRoot "output\quest2-student-candidate.json") -Label "Refined Quest2 candidate manifest"

$continuationArgs = @(
    "-TeacherWorkRoot", $TeacherWorkRoot,
    "-CandidateWorkspace", $candidateRoot,
    "-DistillationPlan", $DistillationPlan,
    "-WorkRoot", $continuationRoot,
    "-WindowsPython", $python
)
Run-ChildStage -Label "Quest2 modular continuation" -PowerShellHost $powerShellHost -Script $continuationScript -Arguments $continuationArgs

$continuationSummary = Need-File -Path (Join-Path $continuationRoot "p3-quest2-modular-continuation.json") -Label "Quest2 modular continuation summary"
$runtimeReviewPlan = Need-File -Path (Join-Path $continuationRoot "runtime-review\p3-device-runtime-review-plan.json") -Label "Quest2 runtime review plan"
$physicalTemplate = Need-File -Path (Join-Path $continuationRoot "runtime-review\p3-physical-runtime-evidence.template.json") -Label "Quest2 physical evidence template"
$finalReceipt = Need-File -Path (Join-Path $continuationRoot "final-distillation\p3-device-distillation-execution-receipt.json") -Label "Final P3 execution receipt"

$continuation = Get-Content -LiteralPath $continuationSummary -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    $continuation.software_continuation_complete -ne $true -or
    $continuation.physical_device_evidence_present -ne $false -or
    $continuation.physical_runtime_review_complete -ne $false -or
    $continuation.runtime_acceptance_authority -ne $false -or
    $continuation.photoreal_acceptance_authority -ne $false -or
    $continuation.production_activation -ne $false
) {
    throw "Quest2 modular continuation crossed the full-software authority boundary."
}

$summary = [ordered]@{
    format = "bodyrig-photoreal-p3-quest2-full-software"
    version = 1
    bodyrig_revision = $head
    teacher_work_root = $TeacherWorkRoot
    p3_device_distillation_plan_sha256 = Sha256 $DistillationPlan
    candidate_workspace = $candidateRoot
    candidate_manifest_sha256 = Sha256 $candidateManifest
    candidate_receipt_sha256 = Sha256 $candidateReceipt
    continuation_workspace = $continuationRoot
    continuation_summary_sha256 = Sha256 $continuationSummary
    final_execution_receipt_sha256 = Sha256 $finalReceipt
    runtime_review_plan_sha256 = Sha256 $runtimeReviewPlan
    physical_evidence_template_sha256 = Sha256 $physicalTemplate
    refined_candidate_complete = $true
    software_pipeline_complete = $true
    physical_device_evidence_present = $false
    physical_runtime_review_complete = $false
    runtime_acceptance_authority = $false
    photoreal_acceptance_authority = $false
    production_activation = $false
}
$summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host ""
Write-Host "Quest2 full software pipeline: COMPLETE"
Write-Host "Candidate receipt:      $candidateReceipt"
Write-Host "Final P3 receipt:       $finalReceipt"
Write-Host "Runtime review plan:    $runtimeReviewPlan"
Write-Host "Physical template:      $physicalTemplate"
Write-Host "Summary:                $summaryPath"
Write-Host "Physical PASS/FAIL:     NOT RUN"
Write-Host "Photoreal acceptance:   FALSE"
Write-Host "Production activation:  FALSE"
exit 0

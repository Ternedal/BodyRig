param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$CandidateWorkspace,
    [Parameter(Mandatory = $true)][string]$DistillationPlan,
    [string]$WorkRoot = "",
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

function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Resolve-PowerShellHost {
    $name = if ($PSVersionTable.PSEdition -eq "Core") { "pwsh.exe" } else { "powershell.exe" }
    $candidate = Join-Path $PSHOME $name
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Could not resolve an isolated PowerShell host for stage operators."
    }
    return $command.Source
}

function Run-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    Write-Host ""
    Write-Host "=== $Label ==="
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Quest2 modular continuation requires an exact clean BodyRig checkout."
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
$CandidateWorkspace = Need-Directory -Path $CandidateWorkspace -Label "Quest2 candidate workspace"
$DistillationPlan = Need-File -Path $DistillationPlan -Label "P3 distillation plan"
$candidateReceipt = Need-File -Path (Join-Path $CandidateWorkspace "p3-quest2-student-candidate-receipt.json") -Label "Quest2 candidate receipt"
$candidateOutput = Need-Directory -Path (Join-Path $CandidateWorkspace "output") -Label "Quest2 candidate output"
$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot
$powerShellHost = Resolve-PowerShellHost

if ([string]::IsNullOrWhiteSpace($WorkRoot)) {
    $WorkRoot = Join-Path (Split-Path -Parent $CandidateWorkspace) "p3-quest2-modular-continuation"
} else {
    $WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot)
}
if (Test-Path -LiteralPath $WorkRoot) {
    throw "Quest2 modular continuation work root already exists: $WorkRoot"
}
New-Item -ItemType Directory -Path $WorkRoot | Out-Null
$WorkRoot = Need-Directory -Path $WorkRoot -Label "Quest2 modular continuation work root"

$eyeRoot = Join-Path $WorkRoot "eyes"
$hairEnvelopeDir = Join-Path $WorkRoot "hair-envelope"
$hairEnvelope = Join-Path $hairEnvelopeDir "p3-quest2-teacher-hair-envelope.json"
$hairRoot = Join-Path $WorkRoot "hair"
$fidelityDir = Join-Path $WorkRoot "fidelity"
$fidelityEvidence = Join-Path $fidelityDir "p3-quest2-fidelity-delta-evidence.json"
$finalRoot = Join-Path $WorkRoot "final-distillation"
$reviewRoot = Join-Path $WorkRoot "runtime-review"
$templatePath = Join-Path $reviewRoot "p3-physical-runtime-evidence.template.json"
$summaryPath = Join-Path $WorkRoot "p3-quest2-modular-continuation.json"

$hairScript = Need-File -Path (Join-Path $repoRoot "run-photoreal-v2-p3-quest2-teacher-hair.ps1") -Label "Quest2 hair operator"
$fidelityScript = Need-File -Path (Join-Path $repoRoot "run-photoreal-v2-p3-quest2-fidelity-delta.ps1") -Label "Quest2 fidelity operator"
$finalScript = Need-File -Path (Join-Path $repoRoot "run-photoreal-v2-p3-quest2-final-manifest.ps1") -Label "Quest2 final manifest operator"
$reviewScript = Need-File -Path (Join-Path $repoRoot "prepare-photoreal-v2-p3-quest2-runtime-review.ps1") -Label "Quest2 runtime review operator"
$templateScript = Need-File -Path (Join-Path $repoRoot "prepare-photoreal-v2-p3-quest2-physical-evidence-template.ps1") -Label "Quest2 physical evidence template operator"

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 MODULAR SOFTWARE CONTINUATION"
Write-Host "Revision:              $head"
Write-Host "Candidate workspace:   $CandidateWorkspace"
Write-Host "Distillation plan:     $DistillationPlan"
Write-Host "Teacher work root:     $TeacherWorkRoot"
Write-Host "Work root:             $WorkRoot"
Write-Host "Stages:                eyes -> hair -> fidelity -> final manifest -> review plan"
Write-Host "Physical PASS/FAIL:    NOT RUN"
Write-Host "Production activation: FALSE"
Write-Host "============================================================"

Run-Checked -Label "Specialized eyes" -Action {
    $eyeArgs = @(
        "-m", "bodyrig.photoreal_p3_quest2_eye_student_runner",
        "--candidate-receipt", $candidateReceipt,
        "--candidate-output-root", $candidateOutput,
        "--output-root", $eyeRoot
    )
    & $python @eyeArgs
}
$eyeReceipt = Need-File -Path (Join-Path $eyeRoot "p3-quest2-eye-student-receipt.json") -Label "Quest2 eye receipt"

New-Item -ItemType Directory -Path $hairEnvelopeDir | Out-Null
Run-Checked -Label "Teacher-derived hair" -Action {
    $hairArgs = @(
        "-TeacherWorkRoot", $TeacherWorkRoot,
        "-CandidateWorkspace", $CandidateWorkspace,
        "-EyeOutputRoot", $eyeRoot,
        "-HairEnvelope", $hairEnvelope,
        "-OutputRoot", $hairRoot,
        "-WindowsPython", $python
    )
    & $powerShellHost -NoProfile -File $hairScript @hairArgs
}
$hairEnvelope = Need-File -Path $hairEnvelope -Label "Quest2 hair envelope"
$hairReceipt = Need-File -Path (Join-Path $hairRoot "p3-quest2-hair-student-receipt.json") -Label "Quest2 hair receipt"

Run-Checked -Label "Teacher-to-student fidelity delta" -Action {
    $fidelityArgs = @(
        "-TeacherWorkRoot", $TeacherWorkRoot,
        "-CandidateWorkspace", $CandidateWorkspace,
        "-HairOutputRoot", $hairRoot,
        "-Output", $fidelityEvidence,
        "-WindowsPython", $python
    )
    & $powerShellHost -NoProfile -File $fidelityScript @fidelityArgs
}
$fidelityEvidence = Need-File -Path $fidelityEvidence -Label "Quest2 fidelity evidence"

Run-Checked -Label "Final P3 distillation manifest" -Action {
    $finalArgs = @(
        "-CandidateWorkspace", $CandidateWorkspace,
        "-HairOutputRoot", $hairRoot,
        "-FidelityEvidence", $fidelityEvidence,
        "-Workspace", $finalRoot,
        "-WindowsPython", $python
    )
    & $powerShellHost -NoProfile -File $finalScript @finalArgs
}
$finalReceipt = Need-File -Path (Join-Path $finalRoot "p3-device-distillation-execution-receipt.json") -Label "Final P3 execution receipt"
$finalWorkspaceReceipt = Need-File -Path (Join-Path $finalRoot "p3-quest2-final-workspace-receipt.json") -Label "Final Quest2 workspace receipt"

Run-Checked -Label "Physical runtime review plan" -Action {
    $reviewArgs = @(
        "-DistillationPlan", $DistillationPlan,
        "-FinalWorkspace", $finalRoot,
        "-ReviewWorkspace", $reviewRoot,
        "-WindowsPython", $python
    )
    & $powerShellHost -NoProfile -File $reviewScript @reviewArgs
}
$runtimeReviewPlan = Need-File -Path (Join-Path $reviewRoot "p3-device-runtime-review-plan.json") -Label "Quest2 runtime review plan"

Run-Checked -Label "Non-authoritative physical evidence template" -Action {
    $templateArgs = @(
        "-RuntimeReviewWorkspace", $reviewRoot,
        "-Output", $templatePath
    )
    & $powerShellHost -NoProfile -File $templateScript @templateArgs
}
$templatePath = Need-File -Path $templatePath -Label "Quest2 physical evidence template"

$summary = [ordered]@{
    format = "bodyrig-photoreal-p3-quest2-modular-continuation"
    version = 1
    bodyrig_revision = $head
    candidate_workspace = $CandidateWorkspace
    candidate_receipt_sha256 = Sha256 $candidateReceipt
    eye_output_root = $eyeRoot
    eye_receipt_sha256 = Sha256 $eyeReceipt
    hair_envelope_sha256 = Sha256 $hairEnvelope
    hair_output_root = $hairRoot
    hair_receipt_sha256 = Sha256 $hairReceipt
    fidelity_evidence_sha256 = Sha256 $fidelityEvidence
    final_workspace = $finalRoot
    final_execution_receipt_sha256 = Sha256 $finalReceipt
    final_workspace_receipt_sha256 = Sha256 $finalWorkspaceReceipt
    runtime_review_workspace = $reviewRoot
    runtime_review_plan_sha256 = Sha256 $runtimeReviewPlan
    physical_evidence_template_sha256 = Sha256 $templatePath
    software_continuation_complete = $true
    physical_device_evidence_present = $false
    physical_runtime_review_complete = $false
    runtime_acceptance_authority = $false
    photoreal_acceptance_authority = $false
    production_activation = $false
}
$summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host ""
Write-Host "Quest2 modular software continuation: COMPLETE"
Write-Host "Runtime review plan:   $runtimeReviewPlan"
Write-Host "Evidence template:     $templatePath"
Write-Host "Summary:               $summaryPath"
Write-Host "Physical PASS/FAIL:    NOT RUN"
Write-Host "Production activation: FALSE"
exit 0

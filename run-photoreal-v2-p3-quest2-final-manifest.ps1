param(
    [Parameter(Mandatory = $true)][string]$CandidateWorkspace,
    [Parameter(Mandatory = $true)][string]$HairOutputRoot,
    [Parameter(Mandatory = $true)][string]$FidelityEvidence,
    [string]$Workspace = "",
    [string]$WindowsPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
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

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Quest2 final manifest requires an exact clean BodyRig checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "BodyRig HEAD is invalid."
}

$CandidateWorkspace = Need-Directory -Path $CandidateWorkspace -Label "Quest2 candidate workspace"
$HairOutputRoot = Need-Directory -Path $HairOutputRoot -Label "Quest2 hair output root"
$FidelityEvidence = Need-File -Path $FidelityEvidence -Label "Quest2 fidelity evidence"
$candidateRequest = Need-File -Path (Join-Path $CandidateWorkspace "request.json") -Label "P3 candidate request"
$hairReceipt = Need-File -Path (Join-Path $HairOutputRoot "p3-quest2-hair-student-receipt.json") -Label "Quest2 hair receipt"

if ([string]::IsNullOrWhiteSpace($Workspace)) {
    $Workspace = Join-Path (Split-Path -Parent $HairOutputRoot) "p3-quest2-final-distillation"
} else {
    $Workspace = [System.IO.Path]::GetFullPath($Workspace)
}
if (Test-Path -LiteralPath $Workspace) {
    throw "Quest2 final workspace already exists: $Workspace"
}

$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 FINAL P3 MANIFEST"
Write-Host "Revision:             $head"
Write-Host "Candidate workspace:  $CandidateWorkspace"
Write-Host "Candidate request:    $candidateRequest"
Write-Host "Hair output:          $HairOutputRoot"
Write-Host "Hair receipt:         $hairReceipt"
Write-Host "Fidelity evidence:    $FidelityEvidence"
Write-Host "Final workspace:      $Workspace"
Write-Host "Student copy:         BYTE-IDENTICAL REQUIRED"
Write-Host "Core validation:      REQUIRED"
Write-Host "Distillation complete: TARGET TRUE"
Write-Host "Physical review:      STILL REQUIRED"
Write-Host "Photoreal acceptance: FALSE"
Write-Host "Production:           FALSE"
Write-Host "============================================================"

$args = @(
    "-m", "bodyrig.photoreal_p3_quest2_final_manifest",
    "--candidate-workspace", $CandidateWorkspace,
    "--hair-output-root", $HairOutputRoot,
    "--fidelity-evidence", $FidelityEvidence,
    "--workspace", $Workspace
)
& $python @args
if ($LASTEXITCODE -ne 0) {
    throw "Quest2 final P3 manifest failed with exit code $LASTEXITCODE."
}

$manifest = Need-File -Path (Join-Path $Workspace "output\distillation-manifest.json") -Label "Final P3 distillation manifest"
$executionReceipt = Need-File -Path (Join-Path $Workspace "p3-device-distillation-execution-receipt.json") -Label "Final P3 execution receipt"
$workspaceReceipt = Need-File -Path (Join-Path $Workspace "p3-quest2-final-workspace-receipt.json") -Label "Final Quest2 workspace receipt"

$receipt = Get-Content -LiteralPath $executionReceipt -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    $receipt.distillation_complete -ne $true -or
    $receipt.artifact_bytes_verified_by_core -ne $true -or
    $receipt.human_runtime_visual_acceptance_required -ne $true -or
    $receipt.runtime_acceptance_authority -ne $false -or
    $receipt.photoreal_acceptance_authority -ne $false -or
    $receipt.production_activation -ne $false
) {
    throw "Final P3 execution receipt crossed the expected authority boundary."
}

Write-Host ""
Write-Host "Quest2 P3 distillation manifest materialized."
Write-Host "Manifest:             $manifest"
Write-Host "Execution receipt:    $executionReceipt"
Write-Host "Workspace receipt:    $workspaceReceipt"
Write-Host "Distillation complete: TRUE"
Write-Host "Physical review:       STILL REQUIRED"
Write-Host "Photoreal acceptance:  FALSE"
Write-Host "Production:            FALSE"
exit 0

param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string[]]$Decision,
    [Parameter(Mandatory = $true)][string[]]$QualityCheck,
    [Parameter(Mandatory = $true)][string]$ReviewedBy,
    [Parameter(Mandatory = $true)][string]$ReviewNotes,
    [Parameter(Mandatory = $true)][switch]$ConfirmReviewComplete,
    [string]$P2Root = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-BodyRigPython {
    param([string]$Requested,[Parameter(Mandatory = $true)][string]$RepoRoot)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return Need-File -Path $Requested -Label "BodyRig Python"
    }
    $venv = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return (Resolve-Path -LiteralPath $venv).Path }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "Python not found. Pass -BodyRigPython explicitly." }
    return $command.Source
}

if (-not $ConfirmReviewComplete) {
    throw "Explicit -ConfirmReviewComplete is required to persist a P2 animated human review."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branch = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $branch.Count -ne 1 -or ([string]$branch[0]).Trim() -ne "main") {
    throw "P2 HELD-OUT animated human review recording requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 HELD-OUT animated human review recording requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"
$reviewRoot = Need-Directory -Path (Join-Path $P2Root "animated-review\human-review") -Label "P2 animated human review root"
$outputPath = Join-Path $P2Root "animated-review\p2-heldout-animated-human-review.json"
if (Test-Path -LiteralPath $outputPath) {
    throw "P2 animated human review receipt already exists: $outputPath"
}
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

$argsList = @(
    "-m", "bodyrig.photoreal_p2_heldout_animated_human_review",
    "record",
    "--review-root", $reviewRoot,
    "--reviewed-by", $ReviewedBy,
    "--review-notes", $ReviewNotes,
    "--confirm-review-complete",
    "--out", $outputPath
)
foreach ($item in $Decision) { $argsList += @("--decision", $item) }
foreach ($item in $QualityCheck) { $argsList += @("--quality-check", $item) }

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - RECORD HUMAN ANIMATED REVIEW"
Write-Host "Review root:           $reviewRoot"
Write-Host "Dimension decisions:   $($Decision.Count)"
Write-Host "Quality decisions:     $($QualityCheck.Count)"
Write-Host "Reviewer:              $ReviewedBy"
Write-Host "Production:            FALSE"
Write-Host "============================================================"

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P2 animated human review recording failed with code $code."
}

$receipt = Get-Content -LiteralPath (Need-File -Path $outputPath -Label "P2 animated human review receipt") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ($receipt.human_animated_review_complete -isnot [bool] -or $receipt.human_animated_review_complete -ne $true) {
    throw "P2 animated human review receipt is not complete."
}
if ($receipt.production_activation -isnot [bool] -or $receipt.production_activation -ne $false) {
    throw "P2 animated human review receipt crossed production authority."
}
if ($receipt.photoreal_acceptance_authority -isnot [bool] -or $receipt.photoreal_acceptance_authority -ne $false) {
    throw "P2 animated human review receipt crossed broader photoreal authority."
}
$status = ([string]$receipt.human_animated_review_status).ToLowerInvariant()
if ($status -eq "pass") {
    foreach ($field in @(
        "animated_teacher_photoreal_accepted",
        "p2_animated_teacher_acceptance_authority",
        "p3_device_distillation_authorized",
        "quest_distillation_authorized"
    )) {
        if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $true) {
            throw "P2 PASS receipt authority missing: $field"
        }
    }
} elseif ($status -eq "fail") {
    foreach ($field in @(
        "animated_teacher_photoreal_accepted",
        "p2_animated_teacher_acceptance_authority",
        "p3_device_distillation_authorized",
        "quest_distillation_authorized"
    )) {
        if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $false) {
            throw "P2 FAIL receipt unexpectedly grants authority: $field"
        }
    }
} else {
    throw "P2 animated human review receipt status is invalid: $status"
}

Write-Host ""
Write-Host "Human P2 animated review: $($status.ToUpperInvariant())"
Write-Host "P2 animated acceptance:   $($receipt.p2_animated_teacher_acceptance_authority)"
Write-Host "P3 / Quest authorized:    $($receipt.p3_device_distillation_authorized)"
Write-Host "Broader photoreal:        FALSE"
Write-Host "Production:               FALSE"
Write-Host "Receipt: $outputPath"
exit 0
